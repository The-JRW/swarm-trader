"""E5 — Empty-book redeploy assist.

When the paper book has zero positions and cash sits above a sensible
threshold, suggest the existing Scan → Apply → Launch **analysis** path on
Run/Ops. This is a display-only nudge: it never starts a scan, applies a
recipe, or launches a run by itself, and execute stays dual-gated off by
default exactly as everywhere else (``SWARM_CRON_EXECUTE_TRADES`` ∧
recipe/request ``execute_trades``).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_CASH_THRESHOLD = 1000.0


def _cash_threshold() -> float:
    raw = (os.environ.get("SWARM_EMPTY_BOOK_CASH_THRESHOLD") or "").strip()
    if not raw:
        return DEFAULT_CASH_THRESHOLD
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_CASH_THRESHOLD


def compute_suggestion(
    positions_count: Optional[int],
    cash: Optional[float],
    threshold: Optional[float] = None,
) -> Dict[str, Any]:
    """Pure decision — no I/O. Suggest only when book is empty and cash is real."""
    threshold = _cash_threshold() if threshold is None else float(threshold)
    has_positions = positions_count is not None and positions_count > 0
    has_cash = cash is not None
    suggest = bool((not has_positions) and has_cash and cash > threshold and positions_count == 0)

    message = None
    if suggest:
        message = (
            f"Book is empty with ${cash:,.0f} cash available — "
            "consider Scan → Apply → Launch analysis to redeploy. "
            "Execute stays off by default (dual-gated)."
        )

    return {
        "suggest": suggest,
        "positions_count": positions_count,
        "cash": cash,
        "threshold": threshold,
        "message": message,
        "execute_dual_gated": True,
        "paper_only": True,
    }


def get_redeploy_suggestion(threshold: Optional[float] = None) -> Dict[str, Any]:
    """Fetch live positions/cash (best-effort) and compute the suggestion."""
    from app.backend.services.paper_run_service import alpaca_trading_mode, has_alpaca_keys

    if alpaca_trading_mode() == "live":
        return {"available": False, "paper": False, "message": "Paper-only (ALPACA_TRADING_MODE=live refused)"}
    if not has_alpaca_keys():
        return {"available": False, "paper": True, "message": "Server Alpaca keys not configured"}

    try:
        from src import accounts as accounts_mod
        from src.alpaca_integration import get_alpaca_account, get_alpaca_positions
        from src.config import resolve_mode

        mode = resolve_mode()
        if mode == "auto" or mode not in ("swing", "day", "hit"):
            mode = "swing"

        if not accounts_mod.get_all_accounts():
            accounts_mod._load_accounts()

        try:
            account = get_alpaca_account(mode)
            positions = get_alpaca_positions(mode)
        except ValueError:
            accounts_mod._load_accounts()
            account = get_alpaca_account("swing")
            positions = get_alpaca_positions("swing")

        cash = float(account.get("cash") or 0)
        positions_count = len(positions or [])
        suggestion = compute_suggestion(positions_count, cash, threshold)
        return {"available": True, "paper": True, **suggestion}
    except Exception as e:
        logger.warning("Redeploy suggestion unavailable (%s)", type(e).__name__)
        return {
            "available": False,
            "paper": True,
            "message": f"Could not load portfolio ({type(e).__name__})",
        }
