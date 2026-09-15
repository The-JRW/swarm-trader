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
            "control-wave-b",
            "ops-recipe",
            "durable-run-history",
            "conviction-digest",
            "performance-snapshots",
            "mode-override-ux",
            "wave-c-orchestrator",
            "swarm-scan",
            "swarm-scan-apply",
            "swarm-scan-launch",
            "swarm-scan-cron",
            "swarm-scan-audit",
            "wave-d-strategies-ia",
            "run-book-tabs",
            "risk-policy-glance",
            "sector-aware-apply",
            "conviction-recipe-hints",
            "dry-run-streak-checklist",
            "perf-snapshot-details",
            "session-digest-center",
            "mode-auto-resolver",
            "empty-book-redeploy-assist",
            "autoresearch-review-queue",
            # Wave F — HIT (High-frequency Intraday Turnover). Paper-only.
            # NOT true HFT: no co-location, no LOB imbalance engine, no
            # maker/taker rebates. See docs/WAVE_F_HIT.md.
            "hit-mode",
            "hit-cost-gate",
            "hit-pulse-cron",
            "hit-ops-strip",
            "hit-dry-run-streak",
            # Wave G — latency-max paper HIT (still NOT colocated µs HFT).
            # See docs/WAVE_G_LATENCY_MAX.md.
            "hit-fast-path",
            "hit-quote-freshness-gate",
            "hit-quote-ws-optional",
            "hit-latency-observatory",
            # G2 Ops-visible amendment (Reviewer CHANGES_REQUIRED follow-up,
            # strategies-ux-16) — fast/slow HIT path now has an Ops/UI badge,
            # labeled analyst set, and read-only run controls on the
            # Strategies HIT ops strip. See docs/WAVE_G_LATENCY_MAX.md.
            "hit-fast-path-ops-visible",
        ],
    }
