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
    read_last_monitor,
    read_ops_status,
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
from app.backend.services.portfolio_monitor_service import (
    monitor_dry_run_env_default,
    resolve_monitor_dry_run,
    run_portfolio_monitor,
)
from src.config import resolve_mode

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_cron_secret)])

STORE_NOTE = (
    "single-worker in-memory run store — status is local to this backend process; "
    "not durable across restarts or multi-replica"
)

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
    execute_trades: bool = Field(
        default=False,
        description="Default false — analysis-only unless explicitly true",
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

    mode = (body.mode or resolve_mode() or "swing").strip().lower()
    if mode not in ("swing", "day", "auto"):
        raise HTTPException(status_code=400, detail="mode must be swing, day, or auto")

    tickers = body.tickers or _default_cron_tickers()
    strategy_ids = body.strategy_ids if body.strategy_ids is not None else list(CORE_STRATEGY_IDS)
    # Query param wins when explicitly provided; else body (default false)
    do_execute = bool(execute_trades) if execute_trades is not None else bool(body.execute_trades)

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
        raise HTTPException(
            status_code=500,
            detail=f"Monitor failed ({type(e).__name__})",
        ) from e

    try:
        write_last_monitor(result)
    except Exception as e:
        logger.warning("Could not persist monitor status (%s)", type(e).__name__)

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
