"""Thread transcript + prompt composition (port of mattermost/thread-context.ts)."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .post_utils import strip_mentions
from .types import MattermostPost, MattermostUser, PostThreadResponse

if TYPE_CHECKING:
    from ..util.logger import Logger
    from .api import MattermostApi

_THINKING_PLACEHOLDER = re.compile(r"^_Thinking…_$")


def _is_noise_post(post: MattermostPost, bot_user_id: str) -> bool:
    if post.type == "system_message":
        return True
    if post.user_id == bot_user_id and _THINKING_PLACEHOLDER.match(post.message.strip()):
        return True
    return False


def _display_name(
    user_id: str,
    bot_user_id: str,
    bot_username: str | None,
    users: dict[str, MattermostUser],
) -> str:
    if user_id == bot_user_id:
        return f"@{bot_username}" if bot_username else "bot"
    u = users.get(user_id)
    return f"@{u.username}" if u else f"user:{user_id[:8]}"


def _format_post_line(
    post: MattermostPost,
    bot_user_id: str,
    bot_username: str | None,
    users: dict[str, MattermostUser],
    trigger_post_id: str,
) -> str | None:
    if _is_noise_post(post, bot_user_id):
        return None
    text = strip_mentions(post.message, bot_user_id, bot_username)
    if not text:
        return None
    who = _display_name(post.user_id, bot_user_id, bot_username, users)
    invoked = " _(invoked you)_" if post.id == trigger_post_id else ""
    return f"**{who}**{invoked}:\n{text}"


def format_thread_transcript(
    *,
    thread: PostThreadResponse,
    bot_user_id: str,
    bot_username: str | None = None,
    trigger_post_id: str,
    users: dict[str, MattermostUser],
) -> str:
    lines: list[str] = []
    for post_id in thread.order:
        post = thread.posts.get(post_id)
        if not post:
            continue
        line = _format_post_line(post, bot_user_id, bot_username, users, trigger_post_id)
        if line:
            lines.append(line)
    return "\n\n".join(lines)


def compose_user_message_with_thread(
    *, transcript: str, current_message: str, max_chars: int,
) -> str:
    current = current_message.strip()
    task_block = f"## Current request\n\n{current}"
    if not transcript.strip():
        return task_block

    header = "## Mattermost thread (chronological, oldest first)\n\n"
    full_transcript = header + transcript
    overhead = len(task_block) + 80
    budget = max(500, max_chars - overhead)

    body = full_transcript
    if len(body) > budget:
        body = (
            "## Mattermost thread (chronological, oldest first)\n\n"
            "_(earlier messages omitted)_\n\n" + transcript[-(budget - 40) :]
        )

    return f"{body}\n\n---\n\n{task_block}"


async def build_user_message_with_thread_context(
    *,
    api: "MattermostApi",
    post: MattermostPost,
    raw_user_text: str,
    bot_user_id: str,
    bot_username: str | None = None,
    max_chars: int,
    log: "Logger",
) -> str:
    root_id = post.root_id or post.id
    try:
        thread = await api.get_post_thread(root_id)
        user_ids = list(dict.fromkeys(p.user_id for p in thread.posts.values()))
        users = await api.get_users_by_ids(user_ids)
        transcript = format_thread_transcript(
            thread=thread,
            bot_user_id=bot_user_id,
            bot_username=bot_username,
            trigger_post_id=post.id,
            users=users,
        )
        return compose_user_message_with_thread(
            transcript=transcript,
            current_message=raw_user_text,
            max_chars=max_chars,
        )
    except Exception as e:
        log.warning("Failed to load thread context; using message only", err=str(e), rootId=root_id)
        return f"## Current request\n\n{raw_user_text.strip()}"
