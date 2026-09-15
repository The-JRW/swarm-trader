"""F6 — HIT dry-run streak / exit checklist (mirrors A2/E1).

Tracks consecutive **weekday** HIT paper runs that completed without an
unexpected error, plus the last would-fire / blocked / cost-gate summaries,
so Ops can show progress toward a documented exit bar before an operator
considers setting ``SWARM_HIT_EXECUTE=true`` in the deployment environment.

Exactly like A2/E1: this module only counts and displays. **Nothing here
flips ``SWARM_HIT_EXECUTE``** (or any other execute-gating env var) — that
stays an env-only, human/Elestio-console decision. There is intentionally no
write path from this service, or any UI control backed by it, to that
environment variable.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STREAK_TARGET = 5
SUMMARY_HISTORY_MAX = 10
STREAK_FILE = "hit_dry_run_streak.json"


def _automation_dir() -> Path:
    from app.backend.services.automation_store import AUTOMATION_DIR

    AUTOMATION_DIR.mkdir(parents=True, exist_ok=True)
    return AUTOMATION_DIR


def _streak_path() -> Path:
    return _automation_dir() / STREAK_FILE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _default_ack() -> Dict[str, Any]:
    return {"acknowledged": False, "by": None, "note": None, "at": None}


def _default_state() -> Dict[str, Any]:
    return {
        "consecutive_weekday_count": 0,
        "target": STREAK_TARGET,
        "streak_met": False,
        "last_date": None,
        "last_weekday_label": None,
        "last_result": None,  # "ok" | "error" | "skipped_weekend"
        "summaries": [],  # last N would-fire/blocked/cost-gate summaries (newest first)
        "ack": _default_ack(),
        "ready_to_flip": False,  # streak_met AND ack.acknowledged — display only
        "updated_at": None,
        "note": (
            "Streak + ack are records only. This does not and cannot set "
            "SWARM_HIT_EXECUTE=true — that stays an Elestio env change."
        ),
    }


def _finalize(state: Dict[str, Any]) -> Dict[str, Any]:
    state["target"] = STREAK_TARGET
    state["streak_met"] = int(state.get("consecutive_weekday_count") or 0) >= STREAK_TARGET
    state["ready_to_flip"] = bool(
        state["streak_met"] and (state.get("ack") or {}).get("acknowledged")
    )
    return state


def read_hit_dry_run_streak() -> Dict[str, Any]:
    data = _read_json(_streak_path())
    state = _default_state()
    if data:
        state.update(data)
        state["ack"] = {**_default_ack(), **(data.get("ack") or {})}
    return _finalize(state)


def _next_weekday(d: date) -> date:
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def _is_weekday(d: date) -> bool:
    return d.weekday() < 5


def _summarize_hit_run(summary: Dict[str, Any], cost_gate_reject_count: int) -> Dict[str, Any]:
    """Compact would-fire/blocked/cost-gate summary — real run fields only."""
    action_counts = summary.get("action_counts") or {}
    would_fire = int(action_counts.get("buy", 0)) + int(action_counts.get("short", 0))
    digest = summary.get("conviction_digest") or {}
    risk_rejected = digest.get("risk_rejected") or []
    return {
        "timestamp": _now_iso(),
        "mode": summary.get("mode"),
        "would_fire_count": would_fire,
        "risk_blocked_count": len(risk_rejected) if isinstance(risk_rejected, list) else 0,
        "cost_gate_reject_count": max(0, int(cost_gate_reject_count or 0)),
        "executed_trades": bool(summary.get("executed_trades")),
    }


def record_weekday_hit_pulse_event(
    *,
    dry_run: bool,
    had_error: bool = False,
    summary: Optional[Dict[str, Any]] = None,
    cost_gate_reject_count: int = 0,
    when: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Update the HIT streak from one completed HIT paper run.

    ``dry_run`` mirrors A2's convention: ``True`` means this run did **not**
    hot-execute (the common/default case — ``SWARM_HIT_EXECUTE`` absent or
    the request didn't ask for execute). Only ``dry_run=True`` weekday calls
    count toward the streak, exactly like A2. An unexpected error resets the
    streak to 0; a normal would-fire/blocked/cost-gate summary is not an
    error — that is exactly what a dry run is meant to surface.
    """
    if not dry_run:
        return read_hit_dry_run_streak()

    now = when or datetime.now(timezone.utc)
    today = now.date()
    raw = _read_json(_streak_path()) or _default_state()
    raw.setdefault("ack", _default_ack())
    raw.setdefault("summaries", [])

    if not _is_weekday(today):
        raw["last_result"] = "skipped_weekend"
        raw["updated_at"] = _now_iso()
        state = _finalize(raw)
        _atomic_write(_streak_path(), state)
        return state

    last_date_raw = raw.get("last_date")
    last_date: Optional[date] = None
    if last_date_raw:
        try:
            last_date = date.fromisoformat(last_date_raw)
        except ValueError:
            last_date = None

    if last_date == today:
        if had_error:
            raw["consecutive_weekday_count"] = 0
            raw["last_result"] = "error"
    elif had_error:
        raw["consecutive_weekday_count"] = 0
        raw["last_result"] = "error"
        raw["last_date"] = today.isoformat()
        raw["last_weekday_label"] = today.strftime("%A")
    elif last_date is not None and _next_weekday(last_date) == today:
        raw["consecutive_weekday_count"] = int(raw.get("consecutive_weekday_count") or 0) + 1
        raw["last_result"] = "ok"
        raw["last_date"] = today.isoformat()
        raw["last_weekday_label"] = today.strftime("%A")
    else:
        raw["consecutive_weekday_count"] = 1
        raw["last_result"] = "ok"
        raw["last_date"] = today.isoformat()
        raw["last_weekday_label"] = today.strftime("%A")

    if summary:
        entry = _summarize_hit_run(summary, cost_gate_reject_count)
        summaries: List[Dict[str, Any]] = [entry] + list(raw.get("summaries") or [])
        raw["summaries"] = summaries[:SUMMARY_HISTORY_MAX]

    raw["updated_at"] = _now_iso()
    state = _finalize(raw)
    _atomic_write(_streak_path(), state)
    return state


def record_ack(by: Optional[str], note: Optional[str] = None) -> Dict[str, Any]:
    """Record a James / Reviewer ack for the record only.

    Never writes ``SWARM_HIT_EXECUTE`` or any other env var — flipping HIT
    execute hot still requires an operator to change the Elestio environment
    directly.
    """
    raw = _read_json(_streak_path()) or _default_state()
    raw["ack"] = {
        "acknowledged": True,
        "by": (by or "unspecified").strip()[:120],
        "note": (note or "").strip()[:500] or None,
        "at": _now_iso(),
    }
    raw["updated_at"] = _now_iso()
    state = _finalize(raw)
    _atomic_write(_streak_path(), state)
    return state


def clear_ack() -> Dict[str, Any]:
    raw = _read_json(_streak_path()) or _default_state()
    raw["ack"] = _default_ack()
    raw["updated_at"] = _now_iso()
    state = _finalize(raw)
    _atomic_write(_streak_path(), state)
    return state
