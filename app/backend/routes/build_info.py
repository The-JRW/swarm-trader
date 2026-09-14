"""Deploy verification — returns git/build stamp (no secrets)."""

from fastapi import APIRouter
import os

router = APIRouter()

@router.get("/build-info")
async def build_info():
    return {
        "service": "swarm-trader-backend",
        "git_sha": os.environ.get("GIT_SHA", "unknown"),
        "image_tag": os.environ.get("IMAGE_TAG", "unknown"),
        "features": ["strategies-ux", "alpaca-sip"],
    }
