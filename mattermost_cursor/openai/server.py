"""OpenAI-compatible HTTP API for mattermost-plugin-agents (port of openai/server.ts)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aiohttp import web

from ..provider import active_model
from ..util.server import ServerHandle, start_app
from .chat_completions import handle_chat_completions
from .responses import handle_responses
from .sessions import OpenAISessionPool

if TYPE_CHECKING:
    from ..approval.manager import ApprovalManager
    from ..config import AppEnv
    from ..history.base import HistoryStore
    from ..util.logger import Logger


def _check_auth(request: web.Request, env: "AppEnv") -> bool:
    required = (env.OPENAI_API_KEY or "").strip()
    if not required:
        return True
    return request.headers.get("Authorization") == f"Bearer {required}"


async def start_openai_api_server(
    *,
    env: "AppEnv",
    log: "Logger",
    approvals: "ApprovalManager",
    history: "HistoryStore",
    client: Any,
) -> ServerHandle:
    sessions = OpenAISessionPool(env, log, client)

    @web.middleware
    async def log_mw(request: web.Request, handler):
        # Logs every request — including unmatched routes (aiohttp wraps the
        # 404 handler in middlewares) — so a bifrost call to a path we don't
        # serve (e.g. /v1/responses) is visible instead of silently 404ing.
        try:
            resp = await handler(request)
            log.info(
                "OpenAI API request",
                method=request.method,
                path=request.rel_url.path_qs,
                status=resp.status,
            )
            return resp
        except web.HTTPException as e:
            log.info(
                "OpenAI API request",
                method=request.method,
                path=request.rel_url.path_qs,
                status=e.status,
            )
            raise

    @web.middleware
    async def auth_mw(request: web.Request, handler):
        if not _check_auth(request, env):
            return web.json_response({"error": {"message": "Invalid API key"}}, status=401)
        return await handler(request)

    async def health(_req: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def models(_req: web.Request) -> web.Response:
        return web.json_response(
            {
                "object": "list",
                "data": [
                    {
                        "id": active_model(env),
                        "object": "model",
                        "created": 0,
                        "owned_by": env.AI_PROVIDER,
                    }
                ],
            }
        )

    async def chat(request: web.Request) -> web.StreamResponse:
        try:
            return await handle_chat_completions(
                request,
                env=env,
                log=log,
                sessions=sessions,
                approvals=approvals,
                history=history,
            )
        except Exception as e:
            log.error("chat/completions failed", err=str(e))
            return web.json_response({"error": {"message": str(e)}}, status=500)

    async def responses(request: web.Request) -> web.StreamResponse:
        try:
            return await handle_responses(
                request,
                env=env,
                log=log,
                sessions=sessions,
                approvals=approvals,
                history=history,
            )
        except Exception as e:
            log.error("responses failed", err=str(e))
            return web.json_response({"error": {"message": str(e)}}, status=500)

    app = web.Application(middlewares=[log_mw, auth_mw])
    app.router.add_get("/health", health)
    app.router.add_get("/v1/health", health)
    app.router.add_get("/models", models)
    app.router.add_get("/v1/models", models)
    app.router.add_post("/chat/completions", chat)
    app.router.add_post("/v1/chat/completions", chat)
    app.router.add_post("/responses", responses)
    app.router.add_post("/v1/responses", responses)

    handle = await start_app(app, env.OPENAI_API_PORT)
    sessions.start_warming()
    log.info(
        "OpenAI-compatible API listening (for mattermost-plugin-agents)",
        port=env.OPENAI_API_PORT,
        provider=env.AI_PROVIDER,
        model=active_model(env),
    )
    return handle
