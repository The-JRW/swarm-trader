"""Paper portfolio monitor for cron A2 — stops + optional day flatten.

Wraps portfolio_monitor stop checks and alpaca close/flatten helpers.
Default is dry-run (no orders) unless env SWARM_MONITOR_DRY_RUN=false AND
the request explicitly sets dry_run=false. Always paper-only FAIL_CLOSED.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.backend.services.paper_run_service import assert_paper_only, alpaca_trading_mode

logger = logging.getLogger(__name__)


def monitor_dry_run_env_default() -> bool:
    """True when env forces dry-run (default). Hot only when env is explicitly false."""
    return (os.environ.get("SWARM_MONITOR_DRY_RUN") or "true").strip().lower() != "false"


def resolve_monitor_dry_run(body_dry_run: Optional[bool]) -> bool:
    """Default dry_run=true unless env SWARM_MONITOR_DRY_RUN=false AND body dry_run=false."""
    if body_dry_run is False and not monitor_dry_run_env_default():
        return False
    return True


def _sanitize_action(row: Dict[str, Any]) -> Dict[str, Any]:
    keep = (
        "status",
        "symbol",
        "ticker",
        "qty",
        "side",
        "reason",
        "order_id",
        "stop_type",
        "action",
        "success",
        "dry_run",
        "error",
    )
    out = {k: row[k] for k in keep if k in row}
    if "reason" in out and isinstance(out["reason"], str):
        out["reason"] = out["reason"][:300]
    if "error" in out and isinstance(out["error"], str):
        out["error"] = out["error"][:200]
    return out


def run_portfolio_monitor(
    *,
    dry_run: bool = True,
    flatten_day: bool = False,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Check stops; optionally flatten day book. Paper-only. Sanitized result."""
    assert_paper_only()
    if alpaca_trading_mode() == "live":
        raise PermissionError("FAIL_CLOSED: portfolio monitor refuses ALPACA_TRADING_MODE=live")

    from src.config import get_mode_config, resolve_mode
    from src.alpaca_integration import (
        flatten_positions,
        get_alpaca_account,
        get_alpaca_positions,
    )

    # Import stop helpers from root portfolio_monitor (PYTHONPATH=/app)
    from portfolio_monitor import (
        check_hard_stop,
        check_trailing_stop,
        get_intraday_high,
        get_spy_daily_return,
    )

    resolved = (mode or resolve_mode() or "swing").strip().lower()
    if resolved == "auto" or resolved not in ("swing", "day"):
        resolved = "swing"

    mode_config = get_mode_config(resolved)
    mode_risk = mode_config["risk"]
    stop_loss_pct = float(mode_risk["stop_loss_pct"])
    trailing_stop_pct = float(mode_risk["trailing_stop_pct"])

    from src import accounts as accounts_mod

    if not accounts_mod.get_all_accounts():
        accounts_mod._load_accounts()

    try:
        account = get_alpaca_account(resolved)
        positions = get_alpaca_positions(resolved) or []
    except Exception:
        accounts_mod._load_accounts()
        account = get_alpaca_account("swing")
        positions = get_alpaca_positions("swing") or []
        resolved = "swing"

    equity = float(account.get("equity") or account.get("portfolio_value") or 0)
    cash = float(account.get("cash") or 0)
    last_equity = float(account.get("last_equity") or equity or 0)
    daily_pnl = equity - last_equity
    daily_pnl_pct = (daily_pnl / last_equity) if last_equity else 0.0

    try:
        spy_return = get_spy_daily_return()
    except Exception:
        spy_return = None

    actions: List[Dict[str, Any]] = []
    warnings: List[str] = []
    eod_flatten = False
    long_positions = [p for p in positions if float(p.get("qty") or 0) > 0]

    # Explicit day flatten when requested (body flatten_day + day mode)
    if flatten_day and resolved == "day" and long_positions:
        eod_flatten = True
        logger.info(
            "Monitor: flatten_day requested (mode=day, dry_run=%s, positions=%d)",
            dry_run,
            len(long_positions),
        )
        flatten_results = flatten_positions(
            long_positions,
            dry_run=dry_run,
            mode=resolved,
        )
        for r in flatten_results or []:
            actions.append({**_sanitize_action(r), "stop_type": "eod_flatten"})
    else:
        # Per-position stop checks
        for pos in long_positions:
            if not isinstance(pos, dict):
                continue
            symbol = str(pos.get("symbol") or "").upper()
            try:
                qty = int(float(pos.get("qty") or 0))
            except (TypeError, ValueError):
                continue
            if qty <= 0 or not symbol:
                continue

            intraday_high = get_intraday_high(symbol)
            hard_triggered, hard_reason = check_hard_stop(pos, stop_loss_pct)
            if hard_triggered:
                if dry_run:
                    actions.append(
                        _sanitize_action(
                            {
                                "status": "dry_run",
                                "symbol": symbol,
                                "qty": qty,
                                "reason": hard_reason,
                                "stop_type": "hard_stop",
                                "dry_run": True,
                                "success": True,
                            }
                        )
                    )
                else:
                    from src.alpaca_integration import close_position

                    result = close_position(symbol, percent=100.0, mode=resolved, dry_run=False)
                    actions.append(
                        _sanitize_action(
                            {
                                **result,
                                "symbol": symbol,
                                "qty": qty,
                                "reason": hard_reason,
                                "stop_type": "hard_stop",
                                "dry_run": False,
                            }
                        )
                    )
                continue

            trail_triggered, trail_reason = check_trailing_stop(
                pos, intraday_high, trailing_stop_pct
            )
            if trail_triggered:
                if dry_run:
                    actions.append(
                        _sanitize_action(
                            {
                                "status": "dry_run",
                                "symbol": symbol,
                                "qty": qty,
                                "reason": trail_reason,
                                "stop_type": "trailing_stop",
                                "dry_run": True,
                                "success": True,
                            }
                        )
                    )
                else:
                    from src.alpaca_integration import close_position

                    result = close_position(symbol, percent=100.0, mode=resolved, dry_run=False)
                    actions.append(
                        _sanitize_action(
                            {
                                **result,
                                "symbol": symbol,
                                "qty": qty,
                                "reason": trail_reason,
                                "stop_type": "trailing_stop",
                                "dry_run": False,
                            }
                        )
                    )
                continue

            # Approaching-stop warnings (same buffer as CLI monitor)
            avg_entry = float(pos.get("avg_entry_price") or 0)
            current_price = float(pos.get("current_price") or 0)
            warn_buffer = stop_loss_pct * 0.2
            if avg_entry > 0 and current_price > 0:
                pct_from_entry = (current_price - avg_entry) / avg_entry
                if pct_from_entry <= -(stop_loss_pct - warn_buffer):
                    warnings.append(
                        f"{symbol}: approaching hard stop at {pct_from_entry*100:.1f}% "
                        f"(stop -{stop_loss_pct*100:.1f}%)"
                    )
            if intraday_high and intraday_high > 0 and current_price > 0:
                trail_warn = trailing_stop_pct * 0.2
                pct_from_high = (current_price - intraday_high) / intraday_high
                if pct_from_high <= -(trailing_stop_pct - trail_warn):
                    warnings.append(
                        f"{symbol}: approaching trailing stop at {pct_from_high*100:.1f}% "
                        f"(stop -{trailing_stop_pct*100:.1f}%)"
                    )

    return {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "paper": True,
        "dry_run": dry_run,
        "trading_mode": resolved,
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "daily_pnl_pct": round(daily_pnl_pct * 100, 2),
        "spy_return_pct": round(spy_return * 100, 2) if spy_return is not None else None,
        "positions_checked": len(long_positions),
        "stops_triggered": len(actions),
        "eod_flatten": eod_flatten,
        "flatten_day_requested": bool(flatten_day),
        "actions": actions,
        "warnings": warnings[:50],
        "monitor_dry_run_env": monitor_dry_run_env_default(),
    }
