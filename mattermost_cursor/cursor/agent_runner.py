"""Runs one user turn, streaming Cursor SDK output to a sink (port of cursor/agent-runner.ts)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from cursor_sdk import CursorAgentError

from .agent_context import augment_user_message
from .stream_sink import dispatch_stream_event

if TYPE_CHECKING:
    from ..approval.manager import ApprovalManager
    from ..config import AppEnv
    from ..mattermost.streaming_post import StreamingPost
    from ..util.logger import Logger


@dataclass
class TurnResult:
    ok: bool
    detail: str


def _cloud_mcp_hint(env: "AppEnv", mcp_servers: dict[str, Any], message: str) -> str | None:
    if env.CURSOR_RUNTIME != "cloud":
        return None
    m = message.lower()
    if "validation" not in m and "invalid_argument" not in m:
        return None
    if mcp_servers:
        return (
            "_Tip:_ Cloud rejected part of the request. Use **HTTP** or **SSE** MCP URLs only "
            "(run zereight/gitlab-mcp and sooperset/mcp-atlassian with streamable HTTP per their "
            "docs). Use an **HTTPS** `url` in `CURSOR_CLOUD_REPOS_JSON` and ensure GitLab is "
            "connected in Cursor."
        )
    return (
        "_Tip:_ For cloud, set `MCP_GITLAB_HTTP_URL`, `MCP_ATLASSIAN_HTTP_URL`, or "
        "`MCP_SERVERS_JSON` with HTTP MCP. Stdio (`npx` / `uvx`) only works with "
        "`CURSOR_RUNTIME=local`."
    )


async def run_cursor_turn(
    *,
    env: "AppEnv",
    log: "Logger",
    agent: Any,
    mcp_servers: dict[str, Any],
    user_text: str,
    streamer: "StreamingPost",
    approvals: "ApprovalManager",
    on_run_started: Callable[[Any], None | Awaitable[None]] | None = None,
) -> TurnResult:
    user_text = augment_user_message(env, user_text)

    try:
        send_opts = {"mcp_servers": mcp_servers} if mcp_servers else None
        run = await agent.send(user_text, send_opts)
    except CursorAgentError as e:
        log.error(
            "Cursor agent failed to start run",
            err=str(e),
            code=getattr(e, "code", None),
            isRetryable=getattr(e, "is_retryable", None),
        )
        detail = f"Cursor could not start: {e}"
        hint = _cloud_mcp_hint(env, mcp_servers, str(e))
        if hint:
            detail += f"\n\n{hint}"
        return TurnResult(ok=False, detail=detail)

    log.info(
        "Cursor run started",
        runId=run.run_id,
        agentId=getattr(run, "agent_id", None),
    )
    if on_run_started is not None:
        result = on_run_started(run)
        if hasattr(result, "__await__"):
            await result

    try:
        async for event in run.messages():
            await dispatch_stream_event(
                event,
                sink=streamer,
                approvals=approvals,
                agent=agent,
                mcp_servers=mcp_servers,
                env=env,
                log=log,
                run=run,
            )
    except Exception as e:
        log.error("Stream error", err=str(e))
        await streamer.append(f"\n\n_Stream error: {e}_\n")
    finally:
        await streamer.clear_transient_run_status()

    result = await run.wait()
    if result.status == "error":
        await streamer.append("\n\n**Run finished with error.**\n")
        return TurnResult(ok=False, detail=result.result or "error")
    if result.status == "cancelled":
        await streamer.append("\n\n_Run cancelled._\n")
        return TurnResult(ok=False, detail="cancelled")

    git = getattr(result, "git", None)
    branches = getattr(git, "branches", None) if git else None
    if branches:
        lines = "\n".join(
            f"- {b.repo_url}"
            f"{f' ({b.branch})' if b.branch else ''}"
            f"{f' → {b.pr_url}' if b.pr_url else ''}"
            for b in branches
        )
        await streamer.append(f"\n\n**Git / MR:**\n{lines}\n")

    return TurnResult(ok=True, detail=result.result or "finished")
