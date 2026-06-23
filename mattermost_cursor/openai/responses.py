"""OpenAI /v1/responses handler (Responses API).

mattermost-plugin-agents' bifrost gateway calls this endpoint whenever the
provider service type is "OpenAI" (or a feature needs the Responses API), even
when "Use Responses API" is off for chat. It is a thin shim over the same agent
loop as ``chat_completions.py`` — only the request parsing and the SSE event
shapes differ (named ``response.*`` events instead of ``chat.completion.chunk``).
"""
from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from aiohttp import web

from ..cursor.agent_context import augment_user_message_for_plugin
from ..cursor.stream_sink import TextBufferSink, dispatch_stream_event
from ..provider import active_model
from .messages import last_user_message, system_instructions

if TYPE_CHECKING:
    from ..approval.manager import ApprovalManager
    from ..config import AppEnv
    from ..history.base import HistoryStore
    from ..util.logger import Logger
    from .sessions import OpenAISessionPool


def _input_to_messages(input_val: Any) -> list[dict[str, Any]]:
    """Normalize the Responses ``input`` (string or list of items) to chat-style
    ``{role, content}`` dicts so the shared message helpers apply."""
    if isinstance(input_val, str):
        return [{"role": "user", "content": input_val}]
    if isinstance(input_val, list):
        return [it for it in input_val if isinstance(it, dict)]
    return []


def _message_item(msg_id: str, status: str, text: str | None) -> dict[str, Any]:
    content = [] if text is None else [{"type": "output_text", "text": text, "annotations": []}]
    return {
        "id": msg_id,
        "type": "message",
        "status": status,
        "role": "assistant",
        "content": content,
    }


def _response_obj(
    resp_id: str, msg_id: str, model: str, status: str, text: str | None, created_at: int,
) -> dict[str, Any]:
    output = [] if text is None else [_message_item(msg_id, "completed", text)]
    obj: dict[str, Any] = {
        "id": resp_id,
        "object": "response",
        "created_at": created_at,
        "status": status,
        "model": model,
        "output": output,
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "max_output_tokens": None,
        "metadata": {},
        "parallel_tool_calls": True,
        "previous_response_id": None,
        "reasoning": {"effort": None, "summary": None},
        "store": False,
        "temperature": 1.0,
        "text": {"format": {"type": "text"}},
        "tool_choice": "auto",
        "tools": [],
        "top_p": 1.0,
        "truncation": "disabled",
        "user": None,
        "usage": None,
    }
    if status == "completed":
        obj["usage"] = {
            "input_tokens": 0,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 0,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 0,
        }
    return obj


async def _emit(res: web.StreamResponse, seq: int, event_type: str, payload: dict[str, Any]) -> int:
    data = {"type": event_type, "sequence_number": seq, **payload}
    await res.write(f"event: {event_type}\ndata: {json.dumps(data)}\n\n".encode())
    return seq + 1


async def handle_responses(
    request: web.Request,
    *,
    env: "AppEnv",
    log: "Logger",
    sessions: "OpenAISessionPool",
    approvals: "ApprovalManager",
    history: "HistoryStore",
) -> web.StreamResponse:
    try:
        body = json.loads(await request.text())
    except Exception:
        return web.json_response({"error": {"message": "Invalid JSON body"}}, status=400)

    msgs = _input_to_messages(body.get("input"))
    user_text = last_user_message(msgs)
    if not user_text.strip():
        # Responses can also pass a bare prompt string via "input"; already handled,
        # but a list with no user turn (e.g. only assistant items) lands here.
        return web.json_response(
            {"error": {"message": "No user message in request"}}, status=400
        )

    model = body.get("model") or active_model(env)
    session_key = (body.get("user") or "").strip() or "default"
    user_id = session_key
    session = await sessions.get(session_key)
    agent, mcp_servers = session.agent, session.mcp_servers

    # System text comes from the top-level "instructions" and/or system input items.
    instr = (body.get("instructions") or "").strip() if isinstance(body.get("instructions"), str) else ""
    system = "\n\n".join(p for p in (instr, system_instructions(msgs)) if p)
    prompt = augment_user_message_for_plugin(env, user_text, system)

    await history.record_user_event(
        userId=user_id,
        username=session_key if session_key != "default" else None,
        type="message",
        preview=user_text,
    )
    history_id = await history.start_run(
        source="openai",
        userId=user_id,
        username=session_key if session_key != "default" else None,
        messagePreview=user_text,
    )

    try:
        send_opts = {"mcp_servers": mcp_servers} if mcp_servers else None
        run = await agent.send(prompt, send_opts)
        await history.update_run(
            history_id, cursorRunId=run.run_id, agentId=getattr(run, "agent_id", None)
        )
    except Exception as e:
        await history.finish_run(history_id, ok=False, detail=str(e))
        return web.json_response({"error": {"message": str(e)}}, status=502)

    resp_id = f"resp_{run.run_id}"
    msg_id = f"msg_{run.run_id}"
    created_at = int(time.time())
    auto_approve = env.CURSOR_AUTO_APPROVE_REQUESTS
    stream = bool(body.get("stream"))

    if not stream:
        async def _noop(_full: str) -> None:
            return

        sink = TextBufferSink(_noop)
        try:
            async for event in run.messages():
                await dispatch_stream_event(
                    event,
                    sink=sink,
                    approvals=approvals,
                    agent=agent,
                    mcp_servers=mcp_servers,
                    env=env,
                    log=log,
                    run=run,
                    auto_approve_requests=auto_approve,
                )
        except Exception as e:
            log.error("OpenAI responses non-stream error", err=str(e))
        finally:
            await sink.clear_transient_run_status()
        result = await run.wait()
        await history.finish_run(
            history_id,
            ok=result.status not in ("error", "cancelled"),
            detail=result.result or result.status,
            status="cancelled" if result.status == "cancelled" else None,
        )
        text = sink.text or ""
        return web.json_response(_response_obj(resp_id, msg_id, model, "completed", text, created_at))

    res = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await res.prepare(request)

    seq = 0
    seq = await _emit(res, seq, "response.created", {"response": _response_obj(resp_id, msg_id, model, "in_progress", None, created_at)})
    seq = await _emit(res, seq, "response.in_progress", {"response": _response_obj(resp_id, msg_id, model, "in_progress", None, created_at)})
    seq = await _emit(res, seq, "response.output_item.added", {"output_index": 0, "item": _message_item(msg_id, "in_progress", None)})
    seq = await _emit(res, seq, "response.content_part.added", {"item_id": msg_id, "output_index": 0, "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}})

    last_sent = ""

    async def on_delta(full: str) -> None:
        nonlocal last_sent, seq
        if len(full) <= len(last_sent):
            return
        delta = full[len(last_sent):]
        last_sent = full
        seq = await _emit(res, seq, "response.output_text.delta", {"item_id": msg_id, "output_index": 0, "content_index": 0, "delta": delta})

    sink = TextBufferSink(on_delta)

    try:
        async for event in run.messages():
            await dispatch_stream_event(
                event,
                sink=sink,
                approvals=approvals,
                agent=agent,
                mcp_servers=mcp_servers,
                env=env,
                log=log,
                run=run,
                auto_approve_requests=auto_approve,
            )
        result = await run.wait()
        await history.finish_run(
            history_id,
            ok=result.status not in ("error", "cancelled"),
            detail=result.result or result.status,
            status="cancelled" if result.status == "cancelled" else None,
        )
        git = getattr(result, "git", None)
        branches = getattr(git, "branches", None) if git else None
        if branches:
            lines = "\n".join(
                f"- {b.repo_url}"
                f"{f' ({b.branch})' if b.branch else ''}"
                f"{f' → {b.pr_url}' if b.pr_url else ''}"
                for b in branches
            )
            await sink.append(f"\n\n**Git / MR:**\n{lines}\n")
    except Exception as e:
        log.error("OpenAI responses stream error", err=str(e))
        await history.finish_run(history_id, ok=False, detail=str(e))
        await sink.append(f"\n\n_Stream error: {e}_\n")
    finally:
        await sink.clear_transient_run_status()

    final_text = last_sent
    seq = await _emit(res, seq, "response.output_text.done", {"item_id": msg_id, "output_index": 0, "content_index": 0, "text": final_text})
    seq = await _emit(res, seq, "response.content_part.done", {"item_id": msg_id, "output_index": 0, "content_index": 0, "part": {"type": "output_text", "text": final_text, "annotations": []}})
    seq = await _emit(res, seq, "response.output_item.done", {"output_index": 0, "item": _message_item(msg_id, "completed", final_text)})
    seq = await _emit(res, seq, "response.completed", {"response": _response_obj(resp_id, msg_id, model, "completed", final_text, created_at)})
    await res.write_eof()
    return res
