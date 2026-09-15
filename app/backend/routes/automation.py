"""Public automation / ops status + cron recipe for the Strategies UI.

Does not require SWARM_CRON_SECRET. Never returns secrets — only summaries
written under /app/data/automation/. Recipe is paper-only config (no secrets).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.backend.services.automation_store import (
    APPLY_RECIPE_MAX,
    auto_launch_env_allows,
    cron_execute_env_allows,
    read_cron_recipe,
    read_last_conviction_digest,
    read_ops_status,
    read_scan_history,
    write_cron_recipe,
)
from app.backend.services.autoresearch_review_service import (
    get_review_queue,
    read_recent_runs as read_recent_autoresearch_runs,
    record_review_decision,
)
from app.backend.services.conviction_digest import build_recipe_hints
from app.backend.services.dry_run_streak_service import (
    clear_ack as clear_dry_run_ack,
    read_dry_run_streak,
    record_ack as record_dry_run_ack,
)
from app.backend.services.hit_dry_run_streak_service import (
    clear_ack as clear_hit_streak_ack,
    read_hit_dry_run_streak,
    record_ack as record_hit_streak_ack,
)
from app.backend.services.hit_ops_service import hit_execute_env_allows, read_hit_ops
from app.backend.services.mode_resolver_service import (
    compute_and_persist_mode_resolution,
    read_last_mode_resolution,
)
from app.backend.services.portfolio_monitor_service import monitor_dry_run_env_default
from app.backend.services.redeploy_assist_service import get_redeploy_suggestion
from app.backend.services.risk_policy_service import get_risk_policy
from app.backend.services.session_digest_service import read_session_digests
from app.backend.services.swarm_scan_service import (
    apply_scan_to_recipe,
    get_last_scan_payload,
    launch_analysis_from_recipe,
    run_swarm_scan,
)

router = APIRouter()


class CronRecipeBody(BaseModel):
    tickers: Optional[List[str]] = Field(default=None, description="Tickers for cron defaults")
    preset: Optional[str] = Field(default=None, description="core|value|growth|quant|custom")
    mode: Optional[str] = Field(default=None, description="swing|day|auto")
    execute_trades: Optional[bool] = Field(
        default=None,
        description="Request execute for next cron — still dual-gated by env",
    )

    @field_validator("tickers")
    @classmethod
    def normalize_tickers(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return None
        cleaned: List[str] = []
        for t in v:
            if not t or not str(t).strip():
                continue
            sym = str(t).strip().upper()
            if not sym.replace(".", "").isalnum():
                raise ValueError(f"Invalid ticker: {t}")
            if sym not in cleaned:
                cleaned.append(sym)
        if len(cleaned) > 20:
            raise ValueError("max 20 tickers")
        return cleaned


@router.get("/automation/status")
async def automation_ops_status():
    """Ops/Automation card data — last cron paper-run + monitor + recipe + digest."""
    ops = read_ops_status()
    return {
        "paper_only": True,
        "monitor_dry_run_env": monitor_dry_run_env_default(),
        "cron_execute_env_allows": cron_execute_env_allows(),
        "auto_launch_env_allows": auto_launch_env_allows(),
        "recipe": ops.get("recipe") or read_cron_recipe(),
        "last_paper_run": ops.get("last_paper_run"),
        "last_monitor": ops.get("last_monitor"),
        "last_conviction_digest": ops.get("last_conviction_digest"),
        "last_conviction_digest_meta": ops.get("last_conviction_digest_meta"),
        "last_scan": ops.get("last_scan"),
        "recent_scans": read_scan_history(limit=10),
        "apply_cap": APPLY_RECIPE_MAX,
        "updated_at": ops.get("updated_at"),
        "paths": ops.get("paths"),
    }


@router.get("/automation/recipe")
async def get_automation_recipe():
    """Read cron recipe (no cron secret — not secrets; paper-only)."""
    recipe = read_cron_recipe()
    return {
        **recipe,
        "cron_execute_env_allows": cron_execute_env_allows(),
        "effective_execute_trades": bool(recipe.get("execute_trades"))
        and cron_execute_env_allows(),
        "paper_only": True,
    }


@router.put("/automation/recipe")
@router.post("/automation/recipe")
async def put_automation_recipe(body: CronRecipeBody):
    """Write cron recipe. execute_trades still dual-gated at cron time by env."""
    current = read_cron_recipe()
    patch: Dict[str, Any] = {}
    if body.tickers is not None:
        patch["tickers"] = body.tickers
    if body.preset is not None:
        preset = body.preset.strip().lower()
        if preset not in ("core", "value", "growth", "quant", "hit", "custom"):
            raise HTTPException(status_code=400, detail="preset must be core|value|growth|quant|hit|custom")
        patch["preset"] = preset
    if body.mode is not None:
        mode = body.mode.strip().lower()
        if mode not in ("swing", "day", "hit", "auto"):
            raise HTTPException(status_code=400, detail="mode must be swing|day|hit|auto")
        patch["mode"] = mode
    if body.execute_trades is not None:
        patch["execute_trades"] = bool(body.execute_trades)

    merged = {**current, **patch}
    saved = write_cron_recipe(merged)
    return {
        **saved,
        "cron_execute_env_allows": cron_execute_env_allows(),
        "effective_execute_trades": bool(saved.get("execute_trades"))
        and cron_execute_env_allows(),
        "paper_only": True,
        "note": (
            "execute_trades applies on next cron only if SWARM_CRON_EXECUTE_TRADES is truthy; "
            "otherwise cron forces execute_trades=false"
        ),
    }


class SwarmScanRequest(BaseModel):
    mode: Optional[str] = Field(default=None, description="swing|day|auto")
    intersect_universe: bool = Field(
        default=True,
        description="Intersect candidates with mode universe (default ON)",
    )
    max_tickers: int = Field(default=25, ge=1, le=50)
    include_core: bool = Field(default=True)


class ApplyScanRequest(BaseModel):
    top_n: int = Field(default=APPLY_RECIPE_MAX, ge=1, le=APPLY_RECIPE_MAX)
    tickers: Optional[List[str]] = Field(
        default=None, description="Optional explicit tickers (still capped at 15)"
    )
    sector_aware: bool = Field(
        default=True,
        description="D3 — diversify underweight sectors first, then fill (skip reasons reported)",
    )
    mode: Optional[str] = Field(
        default=None, description="Universe/sector policy mode — defaults to recipe mode"
    )

    @field_validator("tickers")
    @classmethod
    def normalize_apply_tickers(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return None
        cleaned: List[str] = []
        for t in v:
            if not t or not str(t).strip():
                continue
            sym = str(t).strip().upper()
            if not sym.replace(".", "").isalnum():
                raise ValueError(f"Invalid ticker: {t}")
            if sym not in cleaned:
                cleaned.append(sym)
            if len(cleaned) >= APPLY_RECIPE_MAX:
                break
        return cleaned


class LaunchFromScanRequest(BaseModel):
    execute_trades: bool = Field(
        default=False,
        description="Prefer false (analysis-only). Still dual-gated by env.",
    )
    tickers: Optional[List[str]] = Field(default=None)
    confirm_execute: bool = Field(
        default=False,
        description="UI must set true with execute_trades for paper execute attempt",
    )


@router.post("/automation/swarm-scan")
async def automation_swarm_scan(body: Optional[SwarmScanRequest] = None):
    """C1 — Run market scan, persist last_scan.json, return tagged candidates."""
    body = body or SwarmScanRequest()
    mode = body.mode
    if mode is not None:
        mode = mode.strip().lower()
        if mode not in ("swing", "day", "hit", "auto"):
            raise HTTPException(status_code=400, detail="mode must be swing|day|hit|auto")
    try:
        result = run_swarm_scan(
            mode=mode,
            intersect_universe=bool(body.intersect_universe),
            max_tickers=int(body.max_tickers),
            include_core=bool(body.include_core),
            persist=True,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Scan failed ({type(e).__name__})"
        ) from e
    return {**result, "auto_launch_env_allows": auto_launch_env_allows()}


@router.get("/automation/swarm-scan")
async def automation_swarm_scan_get():
    """C5 — Last scan + recent scan history (no secrets)."""
    return get_last_scan_payload()


@router.post("/automation/swarm-scan/apply")
async def automation_swarm_scan_apply(body: Optional[ApplyScanRequest] = None):
    """C2 + D3 — Apply top N (≤15) candidates to cron recipe, sector-aware."""
    body = body or ApplyScanRequest()
    mode = body.mode
    if mode is not None:
        mode = mode.strip().lower()
        if mode not in ("swing", "day", "hit", "auto"):
            raise HTTPException(status_code=400, detail="mode must be swing|day|hit|auto")
    try:
        return apply_scan_to_recipe(
            top_n=body.top_n,
            tickers=body.tickers,
            sector_aware=bool(body.sector_aware),
            mode=mode,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Apply failed ({type(e).__name__})"
        ) from e


@router.post("/automation/swarm-scan/launch")
async def automation_swarm_scan_launch(body: Optional[LaunchFromScanRequest] = None):
    """C3 — Launch paper analysis from recipe/CORE analysts (analysis-only default).

    execute_trades requires confirm_execute + dual gate; never live / never flips dry-run.
    """
    body = body or LaunchFromScanRequest()
    want_execute = bool(body.execute_trades) and bool(body.confirm_execute)
    try:
        return launch_analysis_from_recipe(
            execute_trades=want_execute,
            tickers=body.tickers,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Launch failed ({type(e).__name__})"
        ) from e


@router.get("/automation/risk-policy")
async def automation_risk_policy(mode: Optional[str] = None):
    """D2 — Read-only hard risk caps for the mode (display only, no override)."""
    if mode is not None:
        mode = mode.strip().lower()
        if mode and mode not in ("swing", "day", "hit", "auto"):
            raise HTTPException(status_code=400, detail="mode must be swing|day|hit|auto")
    try:
        return get_risk_policy(mode)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Risk policy unavailable ({type(e).__name__})"
        ) from e


@router.get("/automation/recipe-hints")
async def automation_recipe_hints():
    """D5 — Display-only next-recipe hints from the last conviction digest.

    Never writes the recipe: the UI must call the apply endpoint explicitly.
    """
    wrap = read_last_conviction_digest() or {}
    digest = wrap.get("digest") if isinstance(wrap, dict) else None
    recipe = read_cron_recipe()
    hints = build_recipe_hints(digest, current_tickers=recipe.get("tickers") or [])
    return {
        **hints,
        "run_id": wrap.get("run_id") if isinstance(wrap, dict) else None,
        "digest_updated_at": wrap.get("updated_at") if isinstance(wrap, dict) else None,
        "current_recipe_tickers": recipe.get("tickers") or [],
        "paper_only": True,
    }


# ── E1 — A2 dry-run streak / exit checklist ─────────────────────────────────


class DryRunAckRequest(BaseModel):
    by: Optional[str] = Field(default=None, description="Who is acking (James / Reviewer)")
    note: Optional[str] = Field(default=None, description="Optional context for the ack")


@router.get("/automation/dry-run-streak")
async def automation_dry_run_streak():
    """E1 — Weekday dry-run streak + last would-fire summaries.

    Display/record only: there is no field here (or write path) that flips
    ``SWARM_MONITOR_DRY_RUN``. That stays an Elestio-console-only decision.
    """
    return read_dry_run_streak()


@router.post("/automation/dry-run-streak/ack")
async def automation_dry_run_streak_ack(body: Optional[DryRunAckRequest] = None):
    """E1 — Record a James/Reviewer ack. Never touches SWARM_MONITOR_DRY_RUN."""
    body = body or DryRunAckRequest()
    return record_dry_run_ack(body.by, body.note)


@router.post("/automation/dry-run-streak/clear-ack")
async def automation_dry_run_streak_clear_ack():
    """E1 — Clear a previously recorded ack (record only)."""
    return clear_dry_run_ack()


# ── E3 — Session digest center ──────────────────────────────────────────────


@router.get("/automation/session-digests")
async def automation_session_digests(limit: int = 10):
    """E3 — Durable digests built from real run fields only, newest first."""
    limit = max(1, min(int(limit or 10), 20))
    return {
        "paper_only": True,
        "limit": limit,
        "digests": read_session_digests(limit=limit),
        "note": (
            "Built from real run fields only (action_counts, decisions, conviction "
            "digest, trade_results filled/blocked) — no invented scores."
        ),
    }


# ── E4 — Mode auto-resolver lite ────────────────────────────────────────────


@router.get("/automation/mode-resolution")
async def automation_mode_resolution():
    """E4 — Last persisted auto-resolution (cheap; no network fetch)."""
    cached = read_last_mode_resolution()
    if cached:
        return cached
    try:
        return compute_and_persist_mode_resolution()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Mode resolution unavailable ({type(e).__name__})"
        ) from e


@router.post("/automation/mode-resolution/refresh")
async def automation_mode_resolution_refresh():
    """E4 — Force a fresh VIX/gap/calendar resolution. Human override still wins."""
    try:
        return compute_and_persist_mode_resolution(force=True)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Mode resolution failed ({type(e).__name__})"
        ) from e


# ── E5 — Empty-book redeploy assist ─────────────────────────────────────────


@router.get("/automation/redeploy-suggestion")
async def automation_redeploy_suggestion():
    """E5 — Suggest Scan → Apply → Launch analysis when the book is empty and
    cash sits above a sensible threshold. Display-only; execute stays
    dual-gated off by default regardless of this suggestion.
    """
    return get_redeploy_suggestion()


# ── E6 — AutoResearch review queue (stub) ───────────────────────────────────


class AutoResearchReviewRequest(BaseModel):
    experiment_id: str = Field(..., description="experiment_id from the review queue")
    decision: str = Field(..., description="approved | rejected | pending (pending clears it)")
    by: Optional[str] = Field(default=None, description="Who is reviewing")
    note: Optional[str] = Field(default=None, description="Optional context for the decision")


@router.get("/automation/autoresearch/queue")
async def automation_autoresearch_queue(limit: int = 20):
    """E6 — Recent fitness/experiments from autoresearch/experiments/*.jsonl.

    Read-only view over the existing offline evolution loop's own logs.
    Approve/reject decisions recorded via the POST endpoint below are
    display/UX-only annotations — they never write strategy.py or any
    production config, and never trigger evolve.py.
    """
    limit = max(1, min(int(limit or 20), 100))
    try:
        return get_review_queue(limit=limit)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"AutoResearch queue unavailable ({type(e).__name__})"
        ) from e


@router.get("/automation/autoresearch/runs")
async def automation_autoresearch_runs(limit: int = 10):
    """E6 — Recent evolution run summaries from autoresearch/experiments/runs.jsonl."""
    limit = max(1, min(int(limit or 10), 50))
    try:
        return {"paper_only": True, "read_only_source": True, "runs": read_recent_autoresearch_runs(limit=limit)}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"AutoResearch runs unavailable ({type(e).__name__})"
        ) from e


@router.post("/automation/autoresearch/review")
async def automation_autoresearch_review(body: AutoResearchReviewRequest):
    """E6 — Record a display/UX-only approve/reject annotation.

    Never applies anything to production config: no write to
    ``autoresearch/strategy.py``, ``trading_mode.json``, ``cron_recipe.json``,
    or any other file this app treats as config, and no evolve.py trigger.
    """
    try:
        return record_review_decision(body.experiment_id, body.decision, body.by, body.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Review decision failed ({type(e).__name__})"
        ) from e


# ── F5 — Ops HIT strip (trades today, turnover, cost-gate rejects, last pulse) ──


@router.get("/automation/hit/ops")
async def automation_hit_ops():
    """F5 — Today's HIT strip. Never crashes without a pulse yet (blank fields).

    HIT is High-frequency **Intraday Turnover** (paper; minutes-hours holds),
    not true HFT — see docs/WAVE_F_HIT.md. This reads a persisted counter
    file; it never opens a live WebSocket connection from this endpoint.
    """
    try:
        ops = read_hit_ops()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"HIT ops unavailable ({type(e).__name__})"
        ) from e
    return {
        **ops,
        "paper_only": True,
        "hit_execute_env_allows": hit_execute_env_allows(),
        "not_true_hft": True,
    }


class HitPulseRequest(BaseModel):
    tickers: Optional[List[str]] = Field(default=None, description="Optional tickers; default HIT universe")
    execute_trades: bool = Field(
        default=False,
        description="Prefer false (analysis-only). Only takes effect if SWARM_HIT_EXECUTE is truthy.",
    )
    top_n: int = Field(default=10, ge=1, le=15)
    fast: bool = Field(
        default=True,
        description=(
            "G2 — default true: fast analyst preset only (technical_analyst/"
            "market_regime/autoresearch/sentiment_analyst). false: also adds "
            "apex + news_sentiment_analyst (slow path — one full LLM call per "
            "ticker each). See docs/WAVE_G_LATENCY_MAX.md."
        ),
    )


@router.post("/automation/hit/pulse")
async def automation_hit_pulse(body: Optional[HitPulseRequest] = None):
    """F3 — UI-facing HIT pulse trigger (no cron secret needed here).

    Same dual-gated execute semantics as ``POST /cron/hit-pulse``: analysis-only
    by default; execute only if ``SWARM_HIT_EXECUTE`` is truthy **and**
    ``execute_trades=true`` is explicitly requested. Cadence for the cron path
    is Scheduler-owned; this route exists for manual/UI-triggered pulses.
    """
    from app.backend.services.hit_service import run_hit_pulse

    body = body or HitPulseRequest()
    try:
        return run_hit_pulse(
            tickers=body.tickers,
            execute_requested=bool(body.execute_trades),
            top_n=body.top_n,
            fast=bool(body.fast),
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"HIT pulse failed ({type(e).__name__})"
        ) from e


# ── F6 — HIT dry-run streak / exit checklist (mirrors A2/E1) ────────────────


class HitStreakAckRequest(BaseModel):
    by: Optional[str] = Field(default=None, description="Who is acking (James / Reviewer)")
    note: Optional[str] = Field(default=None, description="Optional context for the ack")


@router.get("/automation/hit-dry-run-streak")
async def automation_hit_dry_run_streak():
    """F6 — Weekday HIT streak + last would-fire/blocked/cost-gate summaries.

    Display/record only — there is no field here (or write path) that flips
    ``SWARM_HIT_EXECUTE``. That stays an Elestio-console-only decision.
    """
    return read_hit_dry_run_streak()


@router.post("/automation/hit-dry-run-streak/ack")
async def automation_hit_dry_run_streak_ack(body: Optional[HitStreakAckRequest] = None):
    """F6 — Record a James/Reviewer ack. Never touches SWARM_HIT_EXECUTE."""
    body = body or HitStreakAckRequest()
    return record_hit_streak_ack(body.by, body.note)


@router.post("/automation/hit-dry-run-streak/clear-ack")
async def automation_hit_dry_run_streak_clear_ack():
    """F6 — Clear a previously recorded ack (record only)."""
    return clear_hit_streak_ack()
