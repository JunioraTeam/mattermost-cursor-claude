"""OpenAI /v1/chat/completions handler (port of openai/chat-completions.ts)."""
from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from aiohttp import web

from ..cursor.agent_context import augment_user_message_for_plugin
from ..cursor.stream_sink import TextBufferSink, dispatch_stream_event
from ..provider import active_model
from .messages import last_user_message, system_instructions
from .sse import sse_chunk, sse_role_chunk, write_sse_chunk, write_sse_done

if TYPE_CHECKING:
    from ..approval.manager import ApprovalManager
    from ..config import AppEnv
    from ..history.base import HistoryStore
    from ..util.logger import Logger
    from .sessions import OpenAISessionPool


async def handle_chat_completions(
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

    messages = body.get("messages") or []
    user_text = last_user_message(messages)
    if not user_text.strip():
        return web.json_response(
            {"error": {"message": "No user message in request"}}, status=400
        )

    model = body.get("model") or active_model(env)
    session_key = (body.get("user") or "").strip() or "default"
    user_id = session_key
    session = await sessions.get(session_key)
    agent, mcp_servers = session.agent, session.mcp_servers
    prompt = augment_user_message_for_plugin(env, user_text, system_instructions(messages))

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

    completion_id = f"chatcmpl-{run.run_id}"
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
            log.error("OpenAI non-stream error", err=str(e))
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
        return web.json_response(
            {
                "id": completion_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
            }
        )

    res = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await res.prepare(request)

    await write_sse_chunk(res, sse_role_chunk(completion_id, model))

    last_sent = ""

    async def on_delta(full: str) -> None:
        nonlocal last_sent
        if len(full) <= len(last_sent):
            return
        delta = full[len(last_sent):]
        last_sent = full
        await write_sse_chunk(res, sse_chunk(completion_id, model, delta))

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
        log.error("OpenAI stream error", err=str(e))
        await history.finish_run(history_id, ok=False, detail=str(e))
        await sink.append(f"\n\n_Stream error: {e}_\n")
    finally:
        await sink.clear_transient_run_status()

    await write_sse_chunk(res, sse_chunk(completion_id, model, "", "stop"))
    await write_sse_done(res)
    await res.write_eof()
    return res
