"""F5 — Ops HIT strip: trades today, turnover, cost-gate rejects, last pulse.

Persists a small daily counter file under ``/app/data/automation/`` (same
directory as the rest of Wave A-E automation state) so the Ops/Book UI can
show same-day HIT activity without needing a live WebSocket connection.

Every number here is either a direct pass-through of a real paper-run/trade
result or an explicit sum of them — **never a fabricated or estimated-as-if-
measured figure**. Turnover in particular is computed only from legs where a
real reference price was available (from the F2 cost-gate quote fetch);
legs without one are simply not counted, and the persisted note says so.

Fill-latency timestamps (``submitted_at`` / ``filled_at``) are copied through
only when Alpaca's order response actually included them; they are blank
(``None``) when missing — this module never invents a timestamp.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

HIT_OPS_FILE = "hit_ops.json"
RECENT_MAX = 20

TURNOVER_NOTE = (
    "Gross turnover reflects only legs where a real reference price was "
    "available (from the F2 cost-gate quote/trade fetch) — never fabricated; "
    "some fills may be undercounted rather than estimated."
)


def _automation_dir() -> Path:
    from app.backend.services.automation_store import AUTOMATION_DIR

    AUTOMATION_DIR.mkdir(parents=True, exist_ok=True)
    return AUTOMATION_DIR


def _hit_ops_path() -> Path:
    return _automation_dir() / HIT_OPS_FILE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _today_str() -> str:
    return date.today().isoformat()


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Could not read %s (%s)", path, type(e).__name__)
        return None


def _default_state(today: Optional[str] = None) -> Dict[str, Any]:
    return {
        "date": today or _today_str(),
        "trades_today": 0,
        "turnover_today": 0.0,
        "cost_gate_rejects_today": 0,
        "would_fire_today": 0,
        "pulses_today": 0,
        "last_pulse": None,
        "recent_fill_latencies": [],
        "recent_cost_gate_rejects": [],
        "note": TURNOVER_NOTE,
        "updated_at": None,
    }


def _read_or_reset_today() -> Dict[str, Any]:
    """Read persisted state; reset daily counters when the calendar date rolled."""
    raw = _read_json(_hit_ops_path())
    today = _today_str()
    if not raw or raw.get("date") != today:
        return _default_state(today)
    state = _default_state(today)
    state.update(raw)
    state["date"] = today
    return state


def read_hit_ops() -> Dict[str, Any]:
    """Today's HIT ops strip — trades, turnover, cost-gate rejects, last pulse."""
    return _read_or_reset_today()


def _fill_latency(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    submitted = row.get("submitted_at")
    filled = row.get("filled_at")
    if not submitted or not filled:
        return None
    try:
        t0 = datetime.fromisoformat(str(submitted).replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(str(filled).replace("Z", "+00:00"))
        latency_ms = max(0, int((t1 - t0).total_seconds() * 1000))
    except (TypeError, ValueError):
        return None
    return {
        "ticker": row.get("ticker"),
        "order_id": row.get("order_id"),
        "submitted_at": str(submitted),
        "filled_at": str(filled),
        "latency_ms": latency_ms,
    }


def record_hit_run(
    *,
    run_id: str,
    execute_requested: bool,
    execute_effective: bool,
    would_fire_count: int = 0,
    trade_results: Optional[List[Dict[str, Any]]] = None,
    cost_gate_rejects: Optional[List[Dict[str, Any]]] = None,
    prices: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Update today's HIT ops counters from one completed HIT paper run.

    Called for every ``mode == "hit"`` paper run (cron pulse or Strategies UI
    "Run"), whether or not it actually executed — this keeps "last pulse"
    honest and current even for analysis-only runs.
    """
    state = _read_or_reset_today()
    trade_results = trade_results or []
    cost_gate_rejects = cost_gate_rejects or []
    prices = prices or {}

    trades_filled = 0
    turnover_add = 0.0
    latencies: List[Dict[str, Any]] = []

    for row in trade_results:
        if not isinstance(row, dict):
            continue
        if row.get("rule") == "cost_gate":
            continue  # already counted separately below
        if row.get("success"):
            trades_filled += 1
            ticker = str(row.get("ticker") or "").strip().upper()
            qty = row.get("qty") or row.get("quantity") or 0
            price = prices.get(ticker)
            if price:
                try:
                    turnover_add += abs(float(qty or 0)) * float(price)
                except (TypeError, ValueError):
                    pass
        latency = _fill_latency(row)
        if latency:
            latencies.append(latency)

    state["trades_today"] = int(state.get("trades_today") or 0) + trades_filled
    state["turnover_today"] = round(float(state.get("turnover_today") or 0.0) + turnover_add, 2)
    state["cost_gate_rejects_today"] = int(state.get("cost_gate_rejects_today") or 0) + len(
        cost_gate_rejects
    )
    state["would_fire_today"] = int(state.get("would_fire_today") or 0) + max(0, int(would_fire_count or 0))
    state["pulses_today"] = int(state.get("pulses_today") or 0) + 1
    state["last_pulse"] = {
        "run_id": run_id,
        "at": _now_iso(),
        "execute_requested": bool(execute_requested),
        "execute_effective": bool(execute_effective),
        "trades_filled": trades_filled,
        "cost_gate_rejects": len(cost_gate_rejects),
        "turnover_added": round(turnover_add, 2),
        "would_fire_count": max(0, int(would_fire_count or 0)),
    }
    state["recent_fill_latencies"] = (latencies + list(state.get("recent_fill_latencies") or []))[
        :RECENT_MAX
    ]
    state["recent_cost_gate_rejects"] = (
        list(cost_gate_rejects) + list(state.get("recent_cost_gate_rejects") or [])
    )[:RECENT_MAX]
    state["note"] = TURNOVER_NOTE
    state["updated_at"] = _now_iso()

    _atomic_write(_hit_ops_path(), state)
    return state


def hit_execute_env_allows() -> bool:
    """True only when ``SWARM_HIT_EXECUTE`` is explicitly truthy."""
    val = (os.environ.get("SWARM_HIT_EXECUTE") or "").strip().lower()
    return val in ("1", "true", "yes", "on")


def resolve_hit_execute(requested: bool) -> bool:
    """Dual gate for HIT execute: request/recipe true AND env truthy (B1/C4 pattern)."""
    return bool(requested) and hit_execute_env_allows()
