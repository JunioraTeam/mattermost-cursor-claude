"""Reply language detection + Mattermost markdown formatting (port of mattermost/message-format.ts)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

ReplyLanguage = Literal["en", "fa"]

_RTL = re.compile(
    "[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]"
)
_PARA_SPLIT = re.compile(r"\n{2,}")
_MULTISPACE = re.compile(r"[ \t]{2,}")
_CODE_FENCE = re.compile(r"(```.*?```)", re.DOTALL)
_EMOJI = re.compile(r"(?<!`)(:[a-z0-9_+-]+:)(?!`)", re.IGNORECASE)


def detect_reply_language(text: str) -> ReplyLanguage:
    """Pick reply language from the latest user message (Persian/Arabic script -> fa)."""
    sample = text[-4000:]
    return "fa" if _RTL.search(sample) else "en"


def reply_language_instruction(lang: ReplyLanguage) -> str:
    if lang == "fa":
        return (
            "**Language:** Reply in Persian (فارسی) unless the user explicitly asks "
            "for another language."
        )
    return "**Language:** Reply in English unless the user explicitly asks for another language."


def mattermost_formatting_instructions() -> str:
    return (
        "**Mattermost reply formatting:** Write flowing prose — do not put each phrase on its "
        "own line. Separate paragraphs with a blank line (two newline characters). "
        "Use single backticks for inline code. Use triple-backtick fences for multi-line code "
        "blocks. Wrap `:emoji_name:` in single backticks when it must appear literally and not "
        "as an emoji."
    )


def merge_assistant_stream_text(previous: str, incoming: str) -> str:
    """Merge cumulative or delta assistant stream chunks."""
    if not incoming:
        return previous
    if not previous:
        return incoming
    if incoming.startswith(previous):
        return incoming
    if previous.startswith(incoming):
        return previous
    return previous + incoming


@dataclass
class _Segment:
    type: str  # "prose" | "code"
    content: str


def _split_code_fences(text: str) -> list[_Segment]:
    parts = _CODE_FENCE.split(text)
    out: list[_Segment] = []
    for part in parts:
        if part.startswith("```") and part.endswith("```"):
            out.append(_Segment("code", part))
        else:
            out.append(_Segment("prose", part))
    return out


def normalize_prose_newlines(prose: str) -> str:
    """Collapse stray single newlines inside paragraphs (Mattermost treats them as hard breaks)."""
    paras = []
    for para in _PARA_SPLIT.split(prose):
        collapsed = _MULTISPACE.sub(" ", para.replace("\n", " ")).strip()
        if collapsed:
            paras.append(collapsed)
    return "\n\n".join(paras)


def protect_emoji_shortcodes(prose: str) -> str:
    """Wrap :shortcode: patterns not already in backticks or code."""
    return _EMOJI.sub(lambda m: f"`{m.group(1)}`", prose)


def _format_prose(prose: str) -> str:
    return protect_emoji_shortcodes(normalize_prose_newlines(prose))


def format_mattermost_assistant_text(raw: str) -> str:
    """Format assistant reply text for Mattermost markdown rendering."""
    trimmed = raw.strip()
    if not trimmed:
        return ""
    return "".join(
        seg.content if seg.type == "code" else _format_prose(seg.content)
        for seg in _split_code_fences(trimmed)
    )
