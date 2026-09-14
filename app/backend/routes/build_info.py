"""Deploy verification — returns git/build stamp (no secrets)."""

from fastapi import APIRouter
import os

router = APIRouter()

_PLACEHOLDER_SHAS = {
    "",
    "unknown",
    "fix-api-base",
    "latest",
    "dev",
    "local",
}


def _resolve_git_sha() -> str:
    """Prefer a real GIT_SHA from the environment over placeholder defaults.

    Dockerfile.backend bakes ARG GIT_SHA into ENV at image build time; compose
    may also inject GIT_SHA at runtime. Empty / placeholder values → "unknown".
    """
    for key in ("GIT_SHA", "COMMIT_SHA", "SOURCE_VERSION", "ELASTIC_COMMIT", "VERCEL_GIT_COMMIT_SHA"):
        val = (os.environ.get(key) or "").strip()
        if val and val.lower() not in _PLACEHOLDER_SHAS:
            return val
    return "unknown"


@router.get("/build-info")
async def build_info():
    return {
        "service": "swarm-trader-backend",
        "git_sha": _resolve_git_sha(),
        "image_tag": os.environ.get("IMAGE_TAG", "unknown"),
        "features": [
            "strategies-ux",
            "alpaca-sip",
            "api-keys-env-sync",
            "perf-dashboard",
            "components-click-add",
            "orders-closing-pnl",
            "phase3-gui-wave1",
            "a1-a2-automation",
        ],
    }
