"""Public read-only automation / ops status for the Strategies UI.

Does not require SWARM_CRON_SECRET. Never returns secrets — only summaries
written under /app/data/automation/.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.backend.services.automation_store import read_ops_status
from app.backend.services.portfolio_monitor_service import monitor_dry_run_env_default

router = APIRouter()


@router.get("/automation/status")
async def automation_ops_status():
    """Ops/Automation card data — last cron paper-run + monitor actions."""
    ops = read_ops_status()
    return {
        "paper_only": True,
        "monitor_dry_run_env": monitor_dry_run_env_default(),
        "last_paper_run": ops.get("last_paper_run"),
        "last_monitor": ops.get("last_monitor"),
        "updated_at": ops.get("updated_at"),
        "paths": ops.get("paths"),
    }
