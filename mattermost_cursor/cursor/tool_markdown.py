"""Tool execution markdown lines with risk hints (port of cursor/tool-markdown.ts)."""
from __future__ import annotations


def tool_risk_hint(name: str) -> str | None:
    n = name.lower()
    if "shell" in n or "terminal" in n or "run_" in n or "bash" in n:
        return "shell / command"
    if "delete" in n or "remove" in n or "unlink" in n:
        return "destructive file operation"
    if "merge_merge_request" in n or "cancel_pipeline" in n:
        return "potentially disruptive GitLab operation"
    return None


def format_tool_running(name: str) -> str:
    hint = tool_risk_hint(name)
    return f"\n> **Tool** `{name}`{f' — _{hint}_' if hint else ''} …\n"


def format_tool_completed(name: str, status: str) -> str:
    return f"\n> **Tool** `{name}` → **{status}**\n"
