"""D2 — Read-only risk policy glance.

Surfaces the hard caps that ``risk_manager.validate_trade`` enforces so the UI
can display them. Display only: nothing here widens, relaxes, or writes risk
config, and no LLM path can override the numbers.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

VALID_MODES = ("swing", "day")

DISPLAY_ONLY_NOTE = (
    "Display only — hard caps are code-enforced in risk_manager.validate_trade. "
    "No LLM or UI path can widen them."
)


def _resolve_mode(mode: Optional[str]) -> str:
    m = (mode or "").strip().lower()
    if m in VALID_MODES:
        return m
    if m in ("", "auto"):
        try:
            from src.config import resolve_mode

            resolved = (resolve_mode() or "swing").strip().lower()
        except Exception as e:  # pragma: no cover - config always importable in app
            logger.warning("Could not resolve trading mode (%s)", type(e).__name__)
            resolved = "swing"
        return resolved if resolved in VALID_MODES else "swing"
    return "swing"


def _pct(value: Any) -> Optional[float]:
    """Fraction (0.08) → percent (8.0), rounded to 2dp. None when unusable."""
    try:
        return round(float(value) * 100, 2)
    except (TypeError, ValueError):
        return None


def _blocklists(risk: Dict[str, Any]) -> Dict[str, Any]:
    """Ticker blocklists from risk_manager (lazy import — it pulls requests/dotenv)."""
    leveraged: List[str] = []
    moonshots: List[str] = []
    try:
        from risk_manager import LEVERAGED_ETFS, MOONSHOTS

        leveraged = sorted(LEVERAGED_ETFS)
        moonshots = sorted(MOONSHOTS)
    except Exception as e:
        logger.info("Blocklists unavailable (%s)", type(e).__name__)
    return {
        "leveraged_etfs_allowed": bool(risk.get("allow_leveraged_etfs")),
        "leveraged_etfs": leveraged,
        "moonshots_blocked_all_modes": True,
        "moonshots": moonshots,
    }


def get_risk_policy(mode: Optional[str] = None) -> Dict[str, Any]:
    """Return the hard risk caps for ``mode`` (read-only snapshot)."""
    from src.config import get_mode_config

    resolved = _resolve_mode(mode)
    config = get_mode_config(resolved)
    risk: Dict[str, Any] = dict(config.get("risk") or {})
    universe: Dict[str, Any] = config.get("universe") or {}

    sectors: List[Dict[str, Any]] = []
    for key, bucket in universe.items():
        if not isinstance(bucket, dict):
            continue
        tickers = [str(t).strip().upper() for t in (bucket.get("tickers") or []) if t]
        sectors.append(
            {
                "key": key,
                "label": bucket.get("label") or key.replace("_", " ").title(),
                "max_sector_pct": _pct(bucket.get("max_sector_pct", risk.get("max_sector_pct"))),
                "max_per_stock_pct": _pct(
                    bucket.get("max_per_stock_pct", risk.get("max_position_pct"))
                ),
                "ticker_count": len(tickers),
                "tickers": tickers,
            }
        )

    circuit_breakers = [
        {
            "rule": "daily_loss_limit",
            "label": "Daily circuit breaker",
            "limit_pct": _pct(risk.get("daily_loss_limit")),
            "effect": "No new entries for the rest of the day",
        },
        {
            "rule": "no_buy_if_down_pct",
            "label": "No-buy when down",
            "limit_pct": _pct(risk.get("no_buy_if_down_pct")),
            "effect": "Blocks new buys (shorts still validated)",
        },
        {
            "rule": "weekly_loss_limit",
            "label": "Weekly circuit breaker",
            "limit_pct": _pct(risk.get("weekly_loss_limit")),
            "effect": "Blocks new entries for the week",
        },
    ]

    return {
        "paper_only": True,
        "read_only": True,
        "mode": resolved,
        "mode_label": config.get("label") or resolved,
        "requested_mode": (mode or "").strip().lower() or None,
        "caps": {
            "max_position_pct": _pct(risk.get("max_position_pct")),
            "max_sector_pct": _pct(risk.get("max_sector_pct")),
            "max_tactical_pct": _pct(risk.get("max_tactical_pct")),
            "min_cash_pct": _pct(risk.get("min_cash_pct")),
            "stop_loss_pct": _pct(risk.get("stop_loss_pct")),
            "trailing_stop_pct": _pct(risk.get("trailing_stop_pct")),
            "max_trades_per_day": risk.get("max_trades_per_day"),
            "max_open_positions": risk.get("max_open_positions"),
        },
        "sectors": sectors,
        "circuit_breakers": circuit_breakers,
        "flatten": {
            "flatten_eod": bool(risk.get("flatten_eod")),
            "flatten_by": risk.get("flatten_by") if risk.get("flatten_eod") else None,
        },
        "blocklists": _blocklists(risk),
        "source": "src.config.MODES[mode]['risk'] + risk_manager blocklists",
        "note": DISPLAY_ONLY_NOTE,
    }
