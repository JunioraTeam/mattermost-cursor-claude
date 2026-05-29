"""HTTP server for Mattermost interactive message / menu actions (port of approval/http-server.ts).

Configure ``APPROVAL_PUBLIC_BASE_URL`` and point an integration action URL to ``/actions``.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from aiohttp import web

from ..util.server import ServerHandle, start_app

if TYPE_CHECKING:
    from ..util.logger import Logger
    from .manager import ApprovalManager


async def start_approval_http_server(
    *,
    port: int,
    log: "Logger",
    approvals: "ApprovalManager",
    secret: str | None = None,
) -> ServerHandle | None:
    if not port or port <= 0:
        log.info("Approval HTTP server disabled (APPROVAL_HTTP_PORT=0)")
        return None

    async def health(_req: web.Request) -> web.Response:
        return web.Response(text="ok", content_type="text/plain")

    async def actions(req: web.Request) -> web.Response:
        try:
            raw = await req.text()
            body: dict[str, Any] = {}
            ct = req.headers.get("content-type", "")
            if "application/json" in ct:
                body = json.loads(raw or "{}")
            else:
                params = parse_qs(raw)
                ctx_str = params.get("context", [None])[0]
                if ctx_str:
                    try:
                        body = json.loads(ctx_str)
                    except Exception:
                        body = {}

            ctx = body["context"] if isinstance(body.get("context"), dict) else body

            if secret:
                tok = str(ctx.get("token") or ctx.get("action_secret") or body.get("token") or "")
                if tok != secret:
                    return web.Response(status=401, text="unauthorized", content_type="text/plain")

            action = str(ctx.get("action") or body.get("action") or "")
            approval_token = str(ctx.get("approval_token") or body.get("approval_token") or "")
            if action == "approve":
                approvals.resolve(approval_token, True)
            elif action == "deny":
                approvals.resolve(approval_token, False)

            return web.json_response({"update": {"message": "Recorded.", "props": {}}})
        except Exception as e:
            log.error("approval http error", err=str(e))
            return web.Response(status=500)

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/actions", actions)

    handle = await start_app(app, port)
    log.info("Approval HTTP listening", port=port)
    return handle
