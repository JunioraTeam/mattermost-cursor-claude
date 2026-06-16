"""Build agent options and create Cursor SDK agents (port of cursor/create-agent.ts)."""
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from cursor_sdk import AsyncAgent

from .mcp_servers import build_mcp_servers, filter_mcp_servers_for_cloud

if TYPE_CHECKING:
    from cursor_sdk import AsyncClient

    from ..config import AppEnv
    from ..util.logger import Logger


def _parse_repos_json(raw: str | None, log: "Logger") -> list[dict[str, Any]]:
    if not raw or not raw.strip():
        log.warning("CURSOR_CLOUD_REPOS_JSON empty — cloud agent needs at least one repo")
        return []
    try:
        v = json.loads(raw)
        if not isinstance(v, list):
            return []
        repos: list[dict[str, Any]] = []
        for r in v:
            if not isinstance(r, dict):
                continue
            repo: dict[str, Any] = {"url": r.get("url", "")}
            starting_ref = r.get("startingRef") or r.get("starting_ref")
            if starting_ref:
                repo["starting_ref"] = starting_ref
            pr_url = r.get("prUrl") or r.get("pr_url")
            if pr_url:
                repo["pr_url"] = pr_url
            repos.append(repo)
        return repos
    except Exception as e:
        log.error("Invalid CURSOR_CLOUD_REPOS_JSON", err=str(e))
        return []


def _parse_env_vars_json(raw: str | None, log: "Logger") -> dict[str, str] | None:
    if not raw or not raw.strip():
        return None
    try:
        v = json.loads(raw)
        if not isinstance(v, dict):
            return None
        out: dict[str, str] = {}
        for k, val in v.items():
            if k.startswith("CURSOR_"):
                log.warning("Skipping cloud env var: names must not start with CURSOR_", k=k)
                continue
            out[k] = str(val)
        return out
    except Exception as e:
        log.error("Invalid CURSOR_CLOUD_ENV_JSON", err=str(e))
        return None


def build_agent_options(env: "AppEnv", log: "Logger") -> dict[str, Any]:
    mcp_servers = build_mcp_servers(env, log)
    if env.CURSOR_RUNTIME == "cloud":
        mcp_servers = filter_mcp_servers_for_cloud(mcp_servers, log)

    base: dict[str, Any] = {"api_key": env.CURSOR_API_KEY}
    if mcp_servers:
        base["mcp_servers"] = mcp_servers

    if env.CURSOR_RUNTIME == "local":
        base["model"] = {"id": env.CURSOR_MODEL}
        base["local"] = {"cwd": env.CURSOR_LOCAL_CWD or os.getcwd()}
    else:
        repos = _parse_repos_json(env.CURSOR_CLOUD_REPOS_JSON, log)
        for r in repos:
            url = r.get("url", "")
            if url.startswith("git@") or url.startswith("ssh://"):
                log.warning(
                    "Cloud agents typically need an HTTPS clone URL; SSH form may fail "
                    "until converted",
                    url=url,
                )
        env_vars = _parse_env_vars_json(env.CURSOR_CLOUD_ENV_JSON, log)
        cloud: dict[str, Any] = {
            "repos": repos,
            "auto_create_pr": env.CURSOR_CLOUD_AUTO_CREATE_MR,
            "skip_reviewer_request": env.CURSOR_CLOUD_SKIP_REVIEWER_REQUEST,
        }
        if env_vars:
            cloud["env_vars"] = env_vars
        base["cloud"] = cloud

    return base


async def create_cursor_agent(
    env: "AppEnv", log: "Logger", client: "AsyncClient", resume: str | None = None,
) -> tuple[AsyncAgent, dict[str, Any]]:
    # ``resume`` accepted for provider parity; Cursor SDK resume is not wired
    # yet, so a stored token is a no-op here (best-effort — see provider.py).
    if resume:
        log.info("Cursor resume requested but not supported; starting fresh agent")
    opts = build_agent_options(env, log)
    agent = await AsyncAgent.create(opts, client=client)
    mcp_servers: dict[str, Any] = opts.get("mcp_servers") or {}
    log.info(
        "Cursor agent created",
        agentId=getattr(agent, "agent_id", None),
        runtime=env.CURSOR_RUNTIME,
    )
    return agent, mcp_servers
