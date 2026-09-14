"""Cron route authentication — FAIL_CLOSED without valid SWARM_CRON_SECRET."""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException


HEADER_NAME = "X-Swarm-Cron-Secret"


def require_cron_secret(
    x_swarm_cron_secret: str | None = Header(default=None, alias=HEADER_NAME),
) -> None:
    """Require header X-Swarm-Cron-Secret matching env SWARM_CRON_SECRET.

    FAIL_CLOSED: missing env secret, missing header, or mismatch → 401.
    Never echoes the secret in the response.
    """
    expected = (os.environ.get("SWARM_CRON_SECRET") or "").strip()
    provided = (x_swarm_cron_secret or "").strip()

    if not expected:
        raise HTTPException(
            status_code=401,
            detail="FAIL_CLOSED: SWARM_CRON_SECRET is not configured on the server",
        )
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=401,
            detail="FAIL_CLOSED: invalid or missing X-Swarm-Cron-Secret",
        )
