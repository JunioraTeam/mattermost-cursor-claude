"""Build the mcp_servers map from env or custom JSON (port of cursor/mcp-servers.ts).

MCP server configs are plain dicts matching the Cursor SDK's accepted shapes:
  stdio: {"type": "stdio", "command": str, "args": [...], "env": {...}}
  http:  {"type": "http"|"sse", "url": str, "headers": {...}}
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from ..util.expand_env import expand_env_placeholders

if TYPE_CHECKING:
    from ..config import AppEnv
    from ..util.logger import Logger

McpServerConfig = dict[str, Any]


def _parse_args_csv(args: str) -> list[str]:
    return [s.strip() for s in args.split(",") if s.strip()]


def _parse_json_record(raw: str | None, log: "Logger") -> dict[str, McpServerConfig] | None:
    if not raw or not raw.strip():
        return None
    try:
        expanded = expand_env_placeholders(raw)
        v = json.loads(expanded)
        if not isinstance(v, dict):
            log.error("MCP_SERVERS_JSON must be a JSON object")
            return None
        return v
    except Exception as e:
        log.error("Failed to parse MCP_SERVERS_JSON", err=str(e))
        return None


def _stdio_gitlab(env: "AppEnv") -> McpServerConfig | None:
    if env.MCP_GITLAB_HTTP_URL:
        return None
    args = _parse_args_csv(env.MCP_GITLAB_ARGS)
    mcp_env: dict[str, str] = {}
    if env.GITLAB_API_URL:
        mcp_env["GITLAB_API_URL"] = env.GITLAB_API_URL
    if env.GITLAB_PERSONAL_ACCESS_TOKEN:
        mcp_env["GITLAB_PERSONAL_ACCESS_TOKEN"] = env.GITLAB_PERSONAL_ACCESS_TOKEN
    return {
        "type": "stdio",
        "command": env.MCP_GITLAB_COMMAND,
        "args": args,
        "env": mcp_env or None,
    }


def _http_gitlab(env: "AppEnv") -> McpServerConfig | None:
    if not env.MCP_GITLAB_HTTP_URL:
        return None
    headers: dict[str, str] | None = None
    if env.MCP_GITLAB_HTTP_HEADERS_JSON:
        try:
            headers = json.loads(expand_env_placeholders(env.MCP_GITLAB_HTTP_HEADERS_JSON))
        except Exception:
            headers = None
    return {"type": "http", "url": env.MCP_GITLAB_HTTP_URL, "headers": headers}


def _stdio_atlassian(env: "AppEnv") -> McpServerConfig | None:
    if env.MCP_ATLASSIAN_HTTP_URL:
        return None
    args = _parse_args_csv(env.MCP_ATLASSIAN_ARGS)
    mcp_env: dict[str, str] = {}
    for k in (
        "JIRA_URL",
        "JIRA_USERNAME",
        "JIRA_API_TOKEN",
        "JIRA_PERSONAL_TOKEN",
        "CONFLUENCE_URL",
        "CONFLUENCE_USERNAME",
        "CONFLUENCE_API_TOKEN",
        "CONFLUENCE_PERSONAL_TOKEN",
    ):
        v = getattr(env, k)
        if v:
            mcp_env[k] = v
    return {
        "type": "stdio",
        "command": env.MCP_ATLASSIAN_COMMAND,
        "args": args,
        "env": mcp_env or None,
    }


def _http_atlassian(env: "AppEnv") -> McpServerConfig | None:
    if not env.MCP_ATLASSIAN_HTTP_URL:
        return None
    headers: dict[str, str] | None = None
    if env.MCP_ATLASSIAN_HTTP_HEADERS_JSON:
        try:
            headers = json.loads(expand_env_placeholders(env.MCP_ATLASSIAN_HTTP_HEADERS_JSON))
        except Exception:
            headers = None
    return {"type": "http", "url": env.MCP_ATLASSIAN_HTTP_URL, "headers": headers}


def _stdio_figma(env: "AppEnv") -> McpServerConfig | None:
    """Framelink MCP for Figma — stdio only; requires FIGMA_PERSONAL_ACCESS_TOKEN."""
    token = (env.FIGMA_PERSONAL_ACCESS_TOKEN or "").strip()
    if not token:
        return None
    args = _parse_args_csv(env.MCP_FIGMA_ARGS)
    return {
        "type": "stdio",
        "command": env.MCP_FIGMA_COMMAND,
        "args": args,
        "env": {"FIGMA_API_KEY": token},
    }


def filter_mcp_servers_for_cloud(
    servers: dict[str, McpServerConfig], log: "Logger",
) -> dict[str, McpServerConfig]:
    """Cloud agents only accept MCP over HTTP/SSE (no stdio in the VM)."""
    out: dict[str, McpServerConfig] = {}
    for name, cfg in servers.items():
        url = cfg.get("url") if isinstance(cfg, dict) else None
        has_url = isinstance(url, str) and len(url) > 0
        t = cfg.get("type") if isinstance(cfg, dict) else None
        ok_type = t is None or t in ("http", "sse")
        if has_url and ok_type:
            out[name] = cfg
            continue
        log.warning(
            "Dropping MCP server: cloud agents require HTTP or SSE MCP (reachable URLs), "
            "not local stdio",
            name=name,
            type=t or ("stdio" if isinstance(cfg, dict) and "command" in cfg else "unknown"),
        )
    return out


def build_mcp_servers(env: "AppEnv", log: "Logger") -> dict[str, McpServerConfig]:
    """Priority: MCP_SERVERS_JSON (optionally merged with presets), else GitLab+Atlassian+Figma."""
    from_file = _parse_json_record(env.MCP_SERVERS_JSON, log)
    if from_file and not env.MCP_MERGE_PRESETS:
        return from_file

    presets: dict[str, McpServerConfig] = {}
    gl = _http_gitlab(env) or _stdio_gitlab(env)
    if gl:
        presets["gitlab"] = gl
    atl = _http_atlassian(env) or _stdio_atlassian(env)
    if atl:
        presets["atlassian"] = atl
    figma = _stdio_figma(env)
    if figma:
        presets["figma"] = figma

    if from_file and env.MCP_MERGE_PRESETS:
        return {**presets, **from_file}
    return presets
