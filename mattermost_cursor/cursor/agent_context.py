"""System-context augmentation for agent turns (port of cursor/agent-context.ts)."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from ..gitlab.mr_policy import gitlab_mr_target_branch_instructions
from ..mattermost.message_format import (
    detect_reply_language,
    mattermost_formatting_instructions,
    reply_language_instruction,
)

if TYPE_CHECKING:
    from ..config import AppEnv

_CURRENT_REQUEST = re.compile(r"## Current request\s*\n+([\s\S]*)$", re.IGNORECASE)


def extract_current_request(user_text: str) -> str:
    """Text of the latest user message from a composed thread prompt."""
    m = _CURRENT_REQUEST.search(user_text)
    return (m.group(1) if m else user_text).strip()


def build_agent_context_footer(env: "AppEnv", variant: Literal["standalone", "plugin"]) -> str:
    """Shared system context appended to every Cursor agent user turn."""
    channel = (
        "You are replying in Mattermost via the Agents plugin."
        if variant == "plugin"
        else "Mattermost bot context:"
    )

    return f"""---
**{channel}** You can use MCP tools for GitLab (including creating merge requests), Jira, Confluence, and Figma (when configured — use `get_figma_data` with a frame/group link from Figma). When you finish implementation work, open a merge request on the configured GitLab project when appropriate. Summarize links (MR URL, Jira key) in your final reply.

Only one run executes at a time per thread; additional user messages are queued. Users can reply `queue`, `cancel queue`, `cancel <id>`, or `cancel run`. When invoked in a thread, the full thread transcript (chronological) is included in the prompt — use it for context and implementation decisions.

{mattermost_formatting_instructions()}

{gitlab_mr_target_branch_instructions(env)}"""


def _augment_with_footer(
    env: "AppEnv", text: str, variant: Literal["standalone", "plugin"]
) -> str:
    latest = extract_current_request(text)
    lang = detect_reply_language(latest)
    return f"""{text}

{build_agent_context_footer(env, variant)}

{reply_language_instruction(lang)}"""


def augment_user_message(env: "AppEnv", text: str) -> str:
    return _augment_with_footer(env, text, "standalone")


def augment_user_message_for_plugin(env: "AppEnv", user_text: str, system: str) -> str:
    parts: list[str] = []
    if system.strip():
        parts.append(system.strip())
    parts.append(user_text)
    body = "\n\n".join(parts)
    lang = detect_reply_language(user_text)
    return f"""{body}

{build_agent_context_footer(env, "plugin")}

{reply_language_instruction(lang)}"""
