"""Single-user auth: PBKDF2 password hash + HMAC-signed expiring tokens.

Deliberately dependency-free (hashlib/hmac from stdlib) -- passlib/jwt would
add nothing for a single user. Generate the hash for .env with:
    python -m server.auth <your-password>
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sys
import time

PBKDF2_ITERATIONS = 600_000
TOKEN_TTL_SECONDS = 7 * 24 * 3600


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt_hex, dk_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), dk_hex)
    except (ValueError, AttributeError):
        return False


def _secret() -> bytes:
    return os.environ.get("SESSION_SECRET", "dev-secret-change-me").encode()


def issue_token() -> str:
    payload = f"{int(time.time()) + TOKEN_TTL_SECONDS}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).digest()
    return payload + "." + base64.urlsafe_b64encode(sig).decode().rstrip("=")


def verify_token(token: str) -> bool:
    try:
        payload, sig_b64 = token.split(".", 1)
        expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).digest()
        sig = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
        return hmac.compare_digest(sig, expected) and time.time() < int(payload)
    except (ValueError, TypeError):
        return False


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m server.auth <password>")
        sys.exit(1)
    print("Put this in .env as DASHBOARD_PASSWORD_HASH:")
    print(hash_password(sys.argv[1]))
