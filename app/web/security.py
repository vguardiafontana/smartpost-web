from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass


COOKIE_NAME = "smartpost_session"


@dataclass(frozen=True)
class WebSecuritySettings:
    pin: str
    session_secret: str
    session_ttl_seconds: int = 12 * 60 * 60

    @classmethod
    def from_env(cls) -> "WebSecuritySettings":
        pin = (os.environ.get("SMARTPOST_WEB_PIN") or "").strip()
        secret = os.environ.get("SMARTPOST_WEB_SESSION_SECRET") or ""
        if len(pin) < 4:
            raise RuntimeError("Falta SMARTPOST_WEB_PIN o tiene menos de 4 caracteres.")
        if len(secret) < 32:
            raise RuntimeError("Falta SMARTPOST_WEB_SESSION_SECRET o tiene menos de 32 caracteres.")
        ttl = int(os.environ.get("SMARTPOST_WEB_SESSION_TTL_SECONDS") or 12 * 60 * 60)
        return cls(pin=pin, session_secret=secret, session_ttl_seconds=max(300, ttl))


def verify_pin(provided: str, expected: str) -> bool:
    return hmac.compare_digest((provided or "").strip(), (expected or "").strip())


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    pad = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode((text + pad).encode("ascii"))


def create_session_token(secret: str, ttl_seconds: int, now: int | None = None) -> str:
    issued = int(time.time() if now is None else now)
    expires = issued + int(ttl_seconds)
    nonce = secrets.token_hex(12)
    payload = f"{issued}:{expires}:{nonce}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{_b64e(payload)}.{_b64e(sig)}"


def validate_session_token(token: str | None, secret: str, now: int | None = None) -> bool:
    if not token or "." not in token:
        return False
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload = _b64d(payload_b64)
        supplied = _b64d(sig_b64)
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(supplied, expected):
            return False
        _issued, expires, _nonce = payload.decode("utf-8").split(":", 2)
        current = int(time.time() if now is None else now)
        return current <= int(expires)
    except Exception:
        return False
