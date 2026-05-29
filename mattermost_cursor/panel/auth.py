"""Panel session-cookie auth with HMAC signatures (port of panel/auth.ts)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

SESSION_TTL_MS = 7 * 24 * 60 * 60 * 1000
SESSION_COOKIE = "mm_cursor_panel"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_equal(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a.encode(), b.encode())


def check_credentials(
    username: str, password: str, expected_user: str, expected_pass: str,
) -> bool:
    return _safe_equal(username, expected_user) and _safe_equal(password, expected_pass)


def _sign(secret: str, payload: str) -> str:
    digest = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def create_session_token(secret: str) -> str:
    """``expiry.base64url(hmac)``"""
    expiry = str(_now_ms() + SESSION_TTL_MS)
    sig = _sign(secret, expiry)
    return f"{expiry}.{sig}"


def verify_session_token(secret: str, token: str | None) -> bool:
    if not token:
        return False
    parts = token.split(".")
    if len(parts) < 2:
        return False
    expiry, sig = parts[0], parts[1]
    if not expiry or not sig:
        return False
    try:
        exp = int(expiry)
    except ValueError:
        return False
    if exp < _now_ms():
        return False
    expected = _sign(secret, expiry)
    return hmac.compare_digest(sig, expected)


def parse_cookies(header: str | None) -> dict[str, str]:
    from urllib.parse import unquote

    out: dict[str, str] = {}
    if not header:
        return out
    for part in header.split(";"):
        kv = part.strip().split("=")
        k = kv[0]
        if not k:
            continue
        out[k] = unquote("=".join(kv[1:]))
    return out
