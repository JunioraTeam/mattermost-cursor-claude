"""Application entry point (port of index.ts)."""
from __future__ import annotations

import asyncio
import json
import signal
import sys
from typing import Any

from .approval.http_server import start_approval_http_server
from .approval.manager import ApprovalManager
from .bot.app import CursorMattermostBot
from .config import load_env
from .cursor.client import create_client
from .history.store import HistoryStore
from .mattermost.types import MattermostPost
from .mattermost.websocket import MattermostWebSocket
from .openai.server import start_openai_api_server
from .panel.server import start_panel_server
from .util.logger import create_logger


def _parse_posted_post(data: dict[str, Any]) -> MattermostPost | None:
    raw = data.get("post")
    if not isinstance(raw, str):
        return None
    try:
        return MattermostPost.from_json(json.loads(raw))
    except Exception:
        return None


async def _run() -> None:
    env = load_env()
    log = create_logger(env.LOG_LEVEL)
    approvals = ApprovalManager(log)
    history = HistoryStore()

    run_standalone = env.BOT_MODE in ("standalone", "both")
    run_openai = env.BOT_MODE in ("openai", "both")

    client = await create_client(env, log)

    ws: MattermostWebSocket | None = None
    bot: CursorMattermostBot | None = None
    if run_standalone:
        bot = CursorMattermostBot(env, log, approvals, history, client)
        await bot.init()

        def on_event(raw: dict[str, Any]) -> None:
            if raw.get("event") == "posted":
                data = raw.get("data")
                if not isinstance(data, dict):
                    return
                post = _parse_posted_post(data)
                if post and bot is not None:
                    asyncio.ensure_future(bot.handle_posted(post))

        ws = MattermostWebSocket(env.MATTERMOST_URL, env.MATTERMOST_BOT_TOKEN, log, on_event)
        ws.connect()
        log.info("Standalone Mattermost WebSocket bot started")

    http_server = (
        await start_approval_http_server(
            port=env.APPROVAL_HTTP_PORT,
            log=log,
            approvals=approvals,
            secret=env.APPROVAL_ACTION_SECRET,
        )
        if run_standalone and env.APPROVAL_HTTP_PORT > 0
        else None
    )

    openai_server = (
        await start_openai_api_server(
            env=env, log=log, approvals=approvals, history=history, client=client
        )
        if run_openai
        else None
    )

    panel_server = await start_panel_server(env=env, log=log, history=history)

    stop_event = asyncio.Event()

    async def shutdown() -> None:
        log.info("Shutting down")
        if ws is not None:
            await ws.aclose()
        if http_server is not None:
            await http_server.close()
        if openai_server is not None:
            await openai_server.close()
        if panel_server is not None:
            await panel_server.close()
        if bot is not None:
            await bot.aclose()
        try:
            await client.aclose()
        except Exception:
            pass
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(shutdown()))
        except NotImplementedError:  # pragma: no cover (e.g. Windows)
            pass

    await stop_event.wait()


def main() -> None:
    try:
        asyncio.run(_run())
    except Exception as e:  # pragma: no cover
        print(e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
