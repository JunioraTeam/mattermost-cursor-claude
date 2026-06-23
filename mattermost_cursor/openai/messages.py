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


def render_conversation(messages: list[dict[str, Any]]) -> str:
    """Chronological transcript of prior user/assistant turns plus the latest user
    message marked as the current request.

    mattermost-plugin-agents is stateless — it resends the whole thread on every
    call — so this request is the bot's only source of thread history. System turns
    are excluded (handled separately as instructions). Returns the bare latest
    message when there is no prior context.
    """
    last_user_idx = None
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], dict) and messages[i].get("role") == "user":
            last_user_idx = i
            break
    if last_user_idx is None:
        return ""

    current = extract_text_content(messages[last_user_idx].get("content")).strip()

    prior: list[str] = []
    for i, m in enumerate(messages):
        if i == last_user_idx or not isinstance(m, dict):
            continue
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        text = extract_text_content(m.get("content")).strip()
        if not text:
            continue
        prior.append(f"**{'User' if role == 'user' else 'Assistant'}:** {text}")

    if not prior:
        return current
    transcript = "\n\n".join(prior)
    return f"## Conversation so far\n\n{transcript}\n\n## Current request\n\n{current}"
