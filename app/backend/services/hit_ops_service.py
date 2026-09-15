"""F5 — Ops HIT strip: trades today, turnover, cost-gate rejects, last pulse.
G4 (Wave G) — latency observatory: decision→submit→ack→fill, in ms.

Persists a small daily counter file under ``/app/data/automation/`` (same
directory as the rest of Wave A-E automation state) so the Ops/Book UI can
show same-day HIT activity without needing a live WebSocket connection.

Every number here is either a direct pass-through of a real paper-run/trade
result or an explicit sum of them — **never a fabricated or estimated-as-if-
measured figure**. Turnover in particular is computed only from legs where a
real reference price was available (from the F2 cost-gate quote fetch);
legs without one are simply not counted, and the persisted note says so.

Latency timestamps (``decision_at`` / ``client_submit_at`` / ``broker_ack_at``
/ ``submitted_at`` / ``filled_at``) are copied through only when the pipeline
itself recorded or Alpaca's order response actually included them; each is
blank (``None``) when missing, and any derived ms duration that would need a
missing timestamp is also blank — this module never invents a timestamp or a
duration. ``decision_at`` is this codebase's own clock (when a batch of
decisions was finalized, post cost-gate, pre-execute); ``client_submit_at``
is this codebase's own clock immediately before the Alpaca order POST;
``broker_ack_at`` is Alpaca's own ``created_at``/``submitted_at`` from the
order response; ``filled_at`` is Alpaca's own fill timestamp. None of these
require or open a WebSocket — all are ordinary REST response fields plus two
client-side clock reads.
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

LATENCY_NOTE = (
    "G4 — decision/submit are this codebase's own clock reads; ack/fill are "
    "Alpaca's own order-response timestamps. Any missing stage leaves that "
    "stage, and durations depending on it, blank — never fabricated. This is "
    "latency-max paper trading over a broker REST API, not colocated "
    "microsecond HFT."
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
        "latency_note": LATENCY_NOTE,
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


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _ms_between(a: Optional[datetime], b: Optional[datetime]) -> Optional[int]:
    """Duration in ms, or ``None`` when either endpoint is missing — never
    fabricated, and never negative (clock skew/out-of-order timestamps clamp
    to 0 rather than reporting a nonsensical negative latency)."""
    if a is None or b is None:
        return None
    return max(0, int((b - a).total_seconds() * 1000))


def _latency_breakdown(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """G4 — decision→submit→ack→fill latency in ms, from real timestamps
    only. Requires a real ``filled_at`` (this is fundamentally about
    completed fills); any other stage timestamp that is missing simply
    leaves that segment (and any duration depending on it) blank.

    Stages, in order:
      decision_at      — this codebase's clock when the batch of decisions
                          was finalized (post cost-gate, pre-execute).
      client_submit_at — this codebase's clock immediately before the Alpaca
                          order POST (falls back to Alpaca's own
                          ``submitted_at`` pre-G4/if absent, so F5's original
                          ``latency_ms`` measure below is unaffected).
      broker_ack_at     — Alpaca's own ``created_at``/``submitted_at`` from
                          the order response (broker-side acknowledgement).
      filled_at         — Alpaca's own fill timestamp.
    """
    filled_at = row.get("filled_at")
    if not filled_at:
        return None

    decision_at = row.get("decision_at")
    client_submit_at = row.get("client_submit_at")
    broker_ack_at = row.get("broker_ack_at")
    submitted_at = row.get("submitted_at")

    d = _parse_ts(decision_at)
    cs = _parse_ts(client_submit_at)
    ack = _parse_ts(broker_ack_at) or _parse_ts(submitted_at)
    f = _parse_ts(filled_at)
    # F5 backward-compat measure: Alpaca's own submitted_at -> filled_at.
    s_legacy = _parse_ts(submitted_at)

    if not (cs or ack or s_legacy):
        return None

    return {
        "ticker": row.get("ticker"),
        "order_id": row.get("order_id"),
        "decision_at": str(decision_at) if decision_at else None,
        "client_submit_at": str(client_submit_at) if client_submit_at else None,
        "broker_ack_at": str(broker_ack_at) if broker_ack_at else None,
        "submitted_at": str(submitted_at) if submitted_at else None,
        "filled_at": str(filled_at),
        "decision_to_submit_ms": _ms_between(d, cs),
        "submit_to_ack_ms": _ms_between(cs, ack),
        "ack_to_fill_ms": _ms_between(ack, f),
        "decision_to_fill_ms": _ms_between(d, f),
        # F5 (unchanged measure) — Alpaca's own submitted_at -> filled_at.
        "latency_ms": _ms_between(s_legacy, f),
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
        if row.get("rule") in ("cost_gate", "stale_quote"):
            continue  # already counted separately below (F2/G3 pre-trade gate rejects)
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
        latency = _latency_breakdown(row)
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
    state["latency_note"] = LATENCY_NOTE
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
