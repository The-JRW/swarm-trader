"""A1/A2 cron automation routes — paper-only, secret-gated.

Assumption (documented for operators): paper-run status lives in the single-worker
in-memory run store used by Strategies (`paper_run_service._RUNS`). Multi-replica
deploys will not share run state; prefer one backend replica for cron paper-runs.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.backend.dependencies.cron_auth import require_cron_secret
from app.backend.models.schemas import ErrorResponse, PaperRunStatusResponse
from app.backend.services.automation_store import (
    auto_launch_env_allows,
    cron_execute_env_allows,
    read_cron_recipe,
    read_last_monitor,
    read_ops_status,
    resolve_cron_execute_trades,
    write_last_monitor,
    write_last_paper_run,
)
from app.backend.services.paper_run_service import (
    CORE_STRATEGY_IDS,
    alpaca_trading_mode,
    assert_paper_only,
    create_run_record,
    get_run,
    has_alpaca_keys,
    start_paper_run_async,
)
from app.backend.services.dry_run_streak_service import record_weekday_dry_run_event
from app.backend.services.performance_snapshot_service import take_performance_snapshot
from app.backend.services.portfolio_monitor_service import (
    monitor_dry_run_env_default,
    resolve_monitor_dry_run,
    run_portfolio_monitor,
)
from src.config import resolve_mode

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_cron_secret)])

STORE_NOTE = (
    "in-memory run store for live status; durable summaries also under /app/data/runs/ "
    "(single-replica assumption — not shared across multi-replica)"
)


# Preset → analyst ids (aligned with Strategies UI)
_PRESET_ANALYST_IDS = {
    "core": list(CORE_STRATEGY_IDS),
    "value": [
        "ben_graham",
        "warren_buffett",
        "charlie_munger",
        "aswath_damodaran",
        "fundamentals_analyst",
        "valuation_analyst",
    ],
    "growth": [
        "cathie_wood",
        "peter_lynch",
        "phil_fisher",
        "growth_analyst",
        "technical_analyst",
    ],
    "quant": [
        "technical_analyst",
        "autoresearch",
        "apex",
        "market_regime",
        "sentiment_analyst",
        "news_sentiment_analyst",
    ],
    # F4 — HIT preset: deterministic/fast signals ahead of heavier LLM research.
    "hit": [
        "technical_analyst",
        "market_regime",
        "autoresearch",
        "sentiment_analyst",
    ],
}


def _strategy_ids_for_preset(preset: str) -> list:
    p = (preset or "core").strip().lower()
    if p == "custom":
        return list(CORE_STRATEGY_IDS)
    return list(_PRESET_ANALYST_IDS.get(p, CORE_STRATEGY_IDS))

# Fixed liquid fallback when mode universe is unavailable
DEFAULT_LIQUID_TICKERS = ["NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "SPY"]


def _default_cron_tickers() -> List[str]:
    """Swing core_tech universe, else fixed liquid set."""
    try:
        from src.config import get_mode_config

        mode = resolve_mode()
        if mode == "auto" or mode not in ("swing", "day"):
            mode = "swing"
        universe = get_mode_config(mode).get("universe") or {}
        core = universe.get("core_tech") or universe.get("mega_cap") or {}
        tickers = list(core.get("tickers") or [])
        if tickers:
            # Cap for cron cost; keep liquid names
            return [t.upper() for t in tickers[:7]]
    except Exception:
        pass
    return list(DEFAULT_LIQUID_TICKERS)


class CronPaperRunRequest(BaseModel):
    tickers: Optional[List[str]] = Field(
        default=None,
        description="Optional tickers; default swing core / liquid set",
    )
    mode: Optional[str] = Field(default=None, description="swing | day | auto")
    execute_trades: Optional[bool] = Field(
        default=None,
        description="Omit to use recipe; true/false overrides. Still dual-gated by env.",
    )
    strategy_ids: Optional[List[str]] = Field(
        default=None,
        description="Optional analysts; default CORE_STRATEGY_IDS",
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
        return cleaned or None


class CronPortfolioMonitorRequest(BaseModel):
    dry_run: Optional[bool] = Field(
        default=None,
        description="Default true unless env SWARM_MONITOR_DRY_RUN=false AND this is false",
    )
    flatten_day: bool = Field(
        default=False,
        description="If true and resolved mode is day, flatten open positions",
    )


@router.post(
    "/cron/paper-run",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def cron_paper_run(
    body: Optional[CronPaperRunRequest] = None,
    execute_trades: Optional[bool] = Query(
        default=None,
        description="Query override; true enables paper execute (default false)",
    ),
):
    """Start a weekday paper swarm run (CORE analysts by default).

    Reuses create_run_record + start_paper_run_async. Responses are sanitized
    (never include secrets).

    **Store assumption:** run status uses the single-worker in-memory store
    (`paper_run_service`). Not shared across replicas; lost on process restart.
    """
    body = body or CronPaperRunRequest()
    recipe = read_cron_recipe()

    if not has_alpaca_keys():
        raise HTTPException(
            status_code=503,
            detail=(
                "FAIL_CLOSED: ALPACA_API_KEY and ALPACA_API_SECRET are not set. "
                "Configure keys in Elestio env."
            ),
        )
    try:
        assert_paper_only()
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=f"FAIL_CLOSED: {e}") from e

    if alpaca_trading_mode() == "live":
        raise HTTPException(
            status_code=403,
            detail="FAIL_CLOSED: cron paper-run refuses ALPACA_TRADING_MODE=live",
        )

    # Recipe defaults when body omits fields
    mode = (body.mode or recipe.get("mode") or resolve_mode() or "swing").strip().lower()
    if mode not in ("swing", "day", "hit", "auto"):
        raise HTTPException(status_code=400, detail="mode must be swing, day, hit, or auto")

    tickers = body.tickers or recipe.get("tickers") or _default_cron_tickers()
    if body.strategy_ids is not None:
        strategy_ids = body.strategy_ids
    else:
        strategy_ids = _strategy_ids_for_preset(recipe.get("preset") or "core")

    # Requested execute: query > body (if set) > recipe > false
    if execute_trades is not None:
        requested_execute = bool(execute_trades)
    elif body.execute_trades is not None:
        requested_execute = bool(body.execute_trades)
    else:
        requested_execute = bool(recipe.get("execute_trades"))

    # Dual gate: recipe/body true AND env SWARM_CRON_EXECUTE_TRADES truthy
    do_execute = resolve_cron_execute_trades(requested_execute)

    run_id = create_run_record(
        tickers,
        strategy_ids,
        mode,
        execute_trades=do_execute,
        instrument="stocks",
    )
    start_paper_run_async(run_id)

    payload = {
        "run_id": run_id,
        "status": "queued",
        "mode": mode,
        "tickers": tickers,
        "strategy_ids": strategy_ids,
        "execute_trades": do_execute,
        "execute_requested": requested_execute,
        "cron_execute_env_allows": cron_execute_env_allows(),
        "recipe_applied": {
            "preset": recipe.get("preset"),
            "mode": recipe.get("mode"),
            "tickers": recipe.get("tickers"),
            "execute_trades": recipe.get("execute_trades"),
        },
        "paper": True,
        "message": "Cron paper analysis started",
        "store_note": STORE_NOTE,
    }
    try:
        write_last_paper_run(payload)
    except Exception as e:
        logger.warning("Could not persist last paper-run status (%s)", type(e).__name__)

    return payload


@router.get(
    "/cron/paper-run/{run_id}",
    response_model=PaperRunStatusResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def cron_paper_run_status(run_id: str):
    """Poll cron paper-run status from the in-memory single-worker store."""
    rec = get_run(run_id)
    if not rec:
        raise HTTPException(
            status_code=404,
            detail=f"Run not found: {run_id} ({STORE_NOTE})",
        )
    # Persist latest known status for Ops UI
    try:
        write_last_paper_run(
            {
                "run_id": rec.get("run_id"),
                "status": rec.get("status"),
                "mode": rec.get("mode"),
                "tickers": rec.get("tickers"),
                "execute_trades": rec.get("execute_trades"),
                "created_at": rec.get("created_at"),
                "completed_at": rec.get("completed_at"),
                "error": rec.get("error"),
                "store_note": STORE_NOTE,
            }
        )
    except Exception:
        pass
    return PaperRunStatusResponse(**rec)


@router.get(
    "/cron/health",
    responses={401: {"model": ErrorResponse}},
)
async def cron_health():
    """Cron health — paper_only, mode, has_alpaca_keys. Never returns secrets."""
    mode = resolve_mode() or "swing"
    return {
        "ok": True,
        "paper_only": True,
        "alpaca_trading_mode": alpaca_trading_mode(),
        "mode": mode,
        "has_alpaca_keys": has_alpaca_keys(),
        "monitor_dry_run_env": monitor_dry_run_env_default(),
    }


@router.post(
    "/cron/portfolio-monitor",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
async def cron_portfolio_monitor(body: Optional[CronPortfolioMonitorRequest] = None):
    """A2 portfolio monitor — stops + optional day flatten.

    Default dry_run=true unless env SWARM_MONITOR_DRY_RUN=false AND body dry_run=false.
    Hot path places paper orders only; live trading is FAIL_CLOSED.
    """
    body = body or CronPortfolioMonitorRequest()
    dry_run = resolve_monitor_dry_run(body.dry_run)

    try:
        assert_paper_only()
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=f"FAIL_CLOSED: {e}") from e

    if alpaca_trading_mode() == "live":
        raise HTTPException(
            status_code=403,
            detail="FAIL_CLOSED: portfolio monitor refuses ALPACA_TRADING_MODE=live",
        )

    if not has_alpaca_keys():
        raise HTTPException(
            status_code=503,
            detail="FAIL_CLOSED: Alpaca keys missing — cannot run portfolio monitor",
        )

    try:
        result = run_portfolio_monitor(
            dry_run=dry_run,
            flatten_day=bool(body.flatten_day),
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=f"FAIL_CLOSED: {e}") from e
    except Exception as e:
        err = {"error": f"{type(e).__name__}: {e}", "dry_run": dry_run, "paper": True}
        try:
            write_last_monitor(err)
        except Exception:
            pass
        try:
            # E1 — an unexpected error resets the weekday dry-run streak.
            record_weekday_dry_run_event(dry_run=dry_run, had_error=True)
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Monitor failed ({type(e).__name__})",
        ) from e

    try:
        write_last_monitor(result)
    except Exception as e:
        logger.warning("Could not persist monitor status (%s)", type(e).__name__)

    try:
        # E1 — a normal would-fire action is not an error; only exceptions reset the streak.
        record_weekday_dry_run_event(dry_run=dry_run, had_error=False, monitor_result=result)
    except Exception as e:
        logger.warning("Could not update dry-run streak (%s)", type(e).__name__)

    return result


@router.get(
    "/cron/monitor-status",
    responses={401: {"model": ErrorResponse}},
)
async def cron_monitor_status():
    """Last monitor + paper-run summary from /app/data/automation/ (no secrets)."""
    ops = read_ops_status()
    last = read_last_monitor()
    return {
        "paper_only": True,
        "monitor_dry_run_env": monitor_dry_run_env_default(),
        "paths": ops.get("paths"),
        "last_monitor": last or ops.get("last_monitor"),
        "last_paper_run": ops.get("last_paper_run"),
        "updated_at": ops.get("updated_at"),
    }


@router.post(
    "/cron/performance-snapshot",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
async def cron_performance_snapshot(force: bool = False):
    """B4 — Write a paper performance snapshot (equity + SPY when available).

    Requires X-Swarm-Cron-Secret. Never invents alpha — returns null when data missing.
    """
    try:
        assert_paper_only()
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=f"FAIL_CLOSED: {e}") from e

    if alpaca_trading_mode() == "live":
        raise HTTPException(
            status_code=403,
            detail="FAIL_CLOSED: performance snapshot refuses ALPACA_TRADING_MODE=live",
        )

    if not has_alpaca_keys():
        raise HTTPException(
            status_code=503,
            detail="FAIL_CLOSED: Alpaca keys missing — cannot snapshot performance",
        )

    result = take_performance_snapshot(force=bool(force))
    if not result.get("ok"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error") or "Snapshot failed",
        )
    return result


class CronSwarmScanRequest(BaseModel):
    """C4 — Cron swarm scan. apply_recipe/launch only if SWARM_AUTO_LAUNCH truthy."""

    apply_recipe: bool = Field(
        default=False,
        description="Apply top candidates to recipe — ignored unless SWARM_AUTO_LAUNCH",
    )
    launch: bool = Field(
        default=False,
        description="Launch paper analysis — ignored unless SWARM_AUTO_LAUNCH",
    )
    intersect_universe: bool = Field(
        default=True,
        description="Intersect with mode universe (default ON)",
    )
    mode: Optional[str] = Field(default=None, description="swing|day|auto")
    top_n: int = Field(default=15, ge=1, le=15)


@router.post(
    "/cron/swarm-scan",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
async def cron_swarm_scan(body: Optional[CronSwarmScanRequest] = None):
    """C4 — Secret-gated swarm scan. Default scan-only.

    ``apply_recipe`` / ``launch`` honored only when ``SWARM_AUTO_LAUNCH`` is truthy.
    Launch = paper analysis; execute_trades still dual-gated separately (defaults off).
    Never flips SWARM_MONITOR_DRY_RUN or live trading.
    """
    from app.backend.services.swarm_scan_service import (
        apply_scan_to_recipe,
        launch_analysis_from_recipe,
        run_swarm_scan,
    )

    body = body or CronSwarmScanRequest()
    mode = body.mode
    if mode is not None:
        mode = mode.strip().lower()
        if mode not in ("swing", "day", "hit", "auto"):
            raise HTTPException(status_code=400, detail="mode must be swing|day|hit|auto")

    try:
        assert_paper_only()
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=f"FAIL_CLOSED: {e}") from e

    if alpaca_trading_mode() == "live":
        raise HTTPException(
            status_code=403,
            detail="FAIL_CLOSED: cron swarm-scan refuses ALPACA_TRADING_MODE=live",
        )

    try:
        scan_result = run_swarm_scan(
            mode=mode,
            intersect_universe=bool(body.intersect_universe),
            persist=True,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Scan failed ({type(e).__name__})"
        ) from e

    auto = auto_launch_env_allows()
    applied = None
    launched = None
    notes = []

    if body.apply_recipe or body.launch:
        if not auto:
            notes.append(
                "SWARM_AUTO_LAUNCH absent/false — scan-only; apply_recipe/launch ignored"
            )
        else:
            if body.apply_recipe:
                try:
                    applied = apply_scan_to_recipe(top_n=int(body.top_n))
                except Exception as e:
                    notes.append(f"apply_recipe failed: {type(e).__name__}")
            if body.launch:
                try:
                    # Analysis-only via cron auto path (execute still dual-gated elsewhere)
                    launched = launch_analysis_from_recipe(execute_trades=False)
                except PermissionError as e:
                    notes.append(f"launch blocked: {e}")
                except Exception as e:
                    notes.append(f"launch failed: {type(e).__name__}")

    return {
        "paper_only": True,
        "scan": {
            "timestamp": scan_result.get("timestamp"),
            "mode": scan_result.get("mode"),
            "intersect_universe": scan_result.get("intersect_universe"),
            "candidate_count": scan_result.get("candidate_count"),
            "tickers": scan_result.get("tickers"),
            "candidates": scan_result.get("candidates"),
        },
        "auto_launch_env_allows": auto,
        "apply_recipe_requested": bool(body.apply_recipe),
        "launch_requested": bool(body.launch),
        "applied": applied,
        "launched": launched,
        "notes": notes,
        "message": "scan-only" if not auto else "scan (+ optional apply/launch)",
    }


class CronHitPulseRequest(BaseModel):
    """F3 — HIT pulse. Analysis-only default; execute only if SWARM_HIT_EXECUTE
    is truthy **and** this request explicitly asks for it (dual gate, same
    pattern as B1/C4). Cadence is Scheduler/cron-owned — document only, never
    hardcoded here.
    """

    tickers: Optional[List[str]] = Field(
        default=None,
        description="Optional tickers; default liquid mega-cap + SPY/QQQ (HIT universe)",
    )
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

    @field_validator("tickers")
    @classmethod
    def normalize_hit_tickers(cls, v: Optional[List[str]]) -> Optional[List[str]]:
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
        if len(cleaned) > 15:
            raise ValueError("max 15 tickers")
        return cleaned or None


@router.post(
    "/cron/hit-pulse",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def cron_hit_pulse(body: Optional[CronHitPulseRequest] = None):
    """F3 — Secret-gated HIT pulse. Default scan-lite + analysis-only.

    ``execute_trades`` is honored only when ``SWARM_HIT_EXECUTE`` is truthy
    **and** this request sets it true (dual gate — never a single-sided
    env flip). The F2 cost gate is mandatory on any HIT execute attempt.
    Cadence (how often this fires) is owned by the external
    Scheduler/routines/cron that calls this endpoint — nothing here
    self-schedules. HIT ≠ true HFT: paper-only, no co-location, no LOB
    imbalance modeling. See docs/WAVE_F_HIT.md.
    """
    from app.backend.services.hit_service import run_hit_pulse

    body = body or CronHitPulseRequest()

    if not has_alpaca_keys():
        raise HTTPException(
            status_code=503,
            detail=(
                "FAIL_CLOSED: ALPACA_API_KEY and ALPACA_API_SECRET are not set. "
                "Configure keys in Elestio env."
            ),
        )
    try:
        assert_paper_only()
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=f"FAIL_CLOSED: {e}") from e

    if alpaca_trading_mode() == "live":
        raise HTTPException(
            status_code=403,
            detail="FAIL_CLOSED: cron hit-pulse refuses ALPACA_TRADING_MODE=live",
        )

    try:
        return run_hit_pulse(
            tickers=body.tickers,
            execute_requested=bool(body.execute_trades),
            top_n=body.top_n,
            fast=bool(body.fast),
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=f"FAIL_CLOSED: {e}") from e
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"HIT pulse failed ({type(e).__name__})"
        ) from e

