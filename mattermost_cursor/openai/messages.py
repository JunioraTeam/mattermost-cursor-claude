"""OpenAI chat message parsing (port of openai/messages.ts)."""
from __future__ import annotations

from typing import Any


def extract_text_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for p in content:
            if isinstance(p, dict) and "text" in p:
                out.append(str(p.get("text") or ""))
        return "".join(out)
    return str(content)


def last_user_message(messages: list[dict[str, Any]]) -> str:
    """Last user message text, or empty if none."""
    for m in reversed(messages):
        if m.get("role") == "user":
            return extract_text_content(m.get("content"))
    return ""


def system_instructions(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for m in messages:
        if m.get("role") == "system":
            t = extract_text_content(m.get("content")).strip()
            if t:
                parts.append(t)
    return "\n\n".join(parts)
