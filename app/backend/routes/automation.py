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
    read_ops_status,
    read_scan_history,
    write_cron_recipe,
)
from app.backend.services.portfolio_monitor_service import monitor_dry_run_env_default
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
        if preset not in ("core", "value", "growth", "quant", "custom"):
            raise HTTPException(status_code=400, detail="preset must be core|value|growth|quant|custom")
        patch["preset"] = preset
    if body.mode is not None:
        mode = body.mode.strip().lower()
        if mode not in ("swing", "day", "auto"):
            raise HTTPException(status_code=400, detail="mode must be swing|day|auto")
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
        if mode not in ("swing", "day", "auto"):
            raise HTTPException(status_code=400, detail="mode must be swing|day|auto")
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
    """C2 — Apply top N (≤15) candidates to cron recipe tickers."""
    body = body or ApplyScanRequest()
    try:
        return apply_scan_to_recipe(top_n=body.top_n, tickers=body.tickers)
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
