"""Admin panel HTTP server (port of panel/server.ts)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web

from ..util.server import ServerHandle, start_app
from .auth import (
    SESSION_COOKIE,
    check_credentials,
    create_session_token,
    parse_cookies,
    verify_session_token,
)
from .ui import PANEL_HTML

if TYPE_CHECKING:
    from ..config import AppEnv
    from ..history.base import HistoryStore
    from ..util.logger import Logger


def _session_secret(env: "AppEnv") -> str:
    return env.PANEL_SECRET or f"{env.PANEL_USERNAME}:{env.PANEL_PASSWORD}:panel"


def _is_authed(request: web.Request, env: "AppEnv") -> bool:
    cookies = parse_cookies(request.headers.get("Cookie"))
    return verify_session_token(_session_secret(env), cookies.get(SESSION_COOKIE))


async def start_panel_server(
    *, env: "AppEnv", log: "Logger", history: "HistoryStore",
) -> ServerHandle | None:
    port = env.PANEL_PORT
    if not port or port <= 0:
        log.info("Admin panel disabled (PANEL_PORT=0)")
        return None
    if not env.PANEL_USERNAME or not env.PANEL_PASSWORD:
        raise RuntimeError("PANEL_USERNAME and PANEL_PASSWORD are required when PANEL_PORT > 0")

    def _html() -> web.Response:
        return web.Response(text=PANEL_HTML, content_type="text/html", charset="utf-8")

    async def health(_req: web.Request) -> web.Response:
        return web.Response(text="ok", content_type="text/plain")

    async def login(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "bad request"}, status=400)
        username = body.get("username") or ""
        password = body.get("password") or ""
        if not check_credentials(username, password, env.PANEL_USERNAME, env.PANEL_PASSWORD):
            return web.json_response({"error": "invalid credentials"}, status=401)
        token = create_session_token(_session_secret(env))
        res = web.json_response({"ok": True})
        res.headers["Set-Cookie"] = (
            f"{SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Strict; "
            f"Max-Age={7 * 24 * 3600}"
        )
        return res

    async def logout(_req: web.Request) -> web.Response:
        res = web.json_response({"ok": True})
        res.headers["Set-Cookie"] = f"{SESSION_COOKIE}=; HttpOnly; Path=/; Max-Age=0"
        return res

    async def index(request: web.Request) -> web.Response:
        return _html()

    async def api_runs(request: web.Request) -> web.Response:
        if not _is_authed(request, env):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response(await history.list_runs(200))

    async def api_users(request: web.Request) -> web.Response:
        if not _is_authed(request, env):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response(await history.list_users())

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/api/login", login)
    app.router.add_post("/api/logout", logout)
    app.router.add_get("/api/runs", api_runs)
    app.router.add_get("/api/users", api_users)
    app.router.add_get("/", index)
    app.router.add_get("/index.html", index)

    handle = await start_app(app, port)
    log.info("Admin panel listening", port=port)
    return handle
