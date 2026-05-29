"""Replace ${VAR_NAME} placeholders using os.environ (and optional overrides)."""
from __future__ import annotations

import os
import re
from typing import Mapping

_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}", re.IGNORECASE)


def expand_env_placeholders(
    text: str, extra: Mapping[str, str | None] | None = None,
) -> str:
    extra = extra or {}

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        value = extra.get(name)
        if value is None:
            value = os.environ.get(name)
        return value if value is not None else ""

    return _PLACEHOLDER.sub(repl, text)
