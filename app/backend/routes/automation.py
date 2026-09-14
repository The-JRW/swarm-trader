"""Public automation / ops status + cron recipe for the Strategies UI.

Does not require SWARM_CRON_SECRET. Never returns secrets — only summaries
written under /app/data/automation/. Recipe is paper-only config (no secrets).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.backend.services.automation_store import (
    cron_execute_env_allows,
    read_cron_recipe,
    read_ops_status,
    write_cron_recipe,
)
from app.backend.services.portfolio_monitor_service import monitor_dry_run_env_default

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
        "recipe": ops.get("recipe") or read_cron_recipe(),
        "last_paper_run": ops.get("last_paper_run"),
        "last_monitor": ops.get("last_monitor"),
        "last_conviction_digest": ops.get("last_conviction_digest"),
        "last_conviction_digest_meta": ops.get("last_conviction_digest_meta"),
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
