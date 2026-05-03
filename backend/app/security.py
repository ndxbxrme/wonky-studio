from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def make_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sign_state(payload: dict[str, Any], secret: str, expires_in_minutes: int = 10) -> str:
    data = {
        **payload,
        "exp": utc_iso(now_utc() + timedelta(minutes=expires_in_minutes)),
        "nonce": secrets.token_urlsafe(12),
    }
    body = base64.urlsafe_b64encode(
        json.dumps(data, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    signature = _signature(body, secret)
    return f"{body}.{signature}"


def verify_state(state: str, secret: str) -> dict[str, Any] | None:
    try:
        body, signature = state.split(".", 1)
    except ValueError:
        return None

    if not hmac.compare_digest(signature, _signature(body, secret)):
        return None

    try:
        payload = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
        expires_at = datetime.fromisoformat(payload["exp"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return None

    if expires_at < now_utc():
        return None

    return payload


def _signature(body: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256)
    return base64.urlsafe_b64encode(digest.digest()).decode("ascii").rstrip("=")

