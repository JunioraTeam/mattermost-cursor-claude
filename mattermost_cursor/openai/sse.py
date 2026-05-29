"""OpenAI SSE streaming helpers (port of openai/sse.ts).

Writers target an aiohttp ``StreamResponse`` and are awaited.
"""
from __future__ import annotations

import json
import time
from typing import Any

from aiohttp import web


async def write_sse_chunk(res: web.StreamResponse, data: Any) -> None:
    await res.write(f"data: {json.dumps(data)}\n\n".encode())


async def write_sse_done(res: web.StreamResponse) -> None:
    await res.write(b"data: [DONE]\n\n")


def sse_chunk(
    id: str, model: str, content: str, finish_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content} if content else {},
                "finish_reason": finish_reason,
            }
        ],
    }


def sse_role_chunk(id: str, model: str) -> dict[str, Any]:
    return {
        "id": id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}
        ],
    }
