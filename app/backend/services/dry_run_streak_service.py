"""E1 — A2 dry-run streak + exit checklist.

Tracks consecutive **weekday** dry-run portfolio-monitor calls (Mon-Fri) and
persists the last would-fire summaries so the Ops/Book UI can show progress
toward the documented exit criteria in ``docs/AUTOMATION_A1_A2.md``:

  1. 5 consecutive weekday dry-runs without unexpected errors
     (HTTP 5xx / auth failures / malformed action payloads — NOT a normal
     would-fire stop action, which is exactly what a dry run is meant to show)
  2. James / Reviewer ack

This module only counts and displays. **Nothing here flips
``SWARM_MONITOR_DRY_RUN``** — that stays an env-only, human/Elestio-console
decision. There is intentionally no write path from this service (or any UI
control backed by it) to that environment variable.
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
STREAK_FILE = "dry_run_streak.json"


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
        "summaries": [],  # last N would-fire summaries (newest first)
        "ack": _default_ack(),
        "ready_to_flip": False,  # streak_met AND ack.acknowledged — display only
        "updated_at": None,
        "note": (
            "Streak + ack are records only. This does not and cannot set "
            "SWARM_MONITOR_DRY_RUN=false — that stays an Elestio env change."
        ),
    }


def _finalize(state: Dict[str, Any]) -> Dict[str, Any]:
    state["target"] = STREAK_TARGET
    state["streak_met"] = int(state.get("consecutive_weekday_count") or 0) >= STREAK_TARGET
    state["ready_to_flip"] = bool(state["streak_met"] and (state.get("ack") or {}).get("acknowledged"))
    return state


def read_dry_run_streak() -> Dict[str, Any]:
    data = _read_json(_streak_path())
    state = _default_state()
    if data:
        state.update(data)
        state["ack"] = {**_default_ack(), **(data.get("ack") or {})}
    return _finalize(state)


def _next_weekday(d: date) -> date:
    """Next business day after ``d`` (skips Sat/Sun)."""
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def _is_weekday(d: date) -> bool:
    return d.weekday() < 5


def _summarize_monitor_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Compact would-fire summary — compacts real monitor fields only."""
    actions = result.get("actions") or []
    return {
        "timestamp": result.get("timestamp") or _now_iso(),
        "dry_run": result.get("dry_run", True),
        "trading_mode": result.get("trading_mode"),
        "positions_checked": result.get("positions_checked"),
        "would_fire_count": len(actions),
        "would_fire": [
            {
                "symbol": a.get("symbol") or a.get("ticker"),
                "stop_type": a.get("stop_type"),
                "reason": (a.get("reason") or "")[:200] if isinstance(a.get("reason"), str) else a.get("reason"),
            }
            for a in actions[:20]
            if isinstance(a, dict)
        ],
        "warnings_count": len(result.get("warnings") or []),
    }


def record_weekday_dry_run_event(
    *,
    dry_run: bool,
    had_error: bool = False,
    monitor_result: Optional[Dict[str, Any]] = None,
    when: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Update the streak from one portfolio-monitor cron/UI call.

    Only **weekday dry-run** calls count toward the streak — hot calls
    (``dry_run=False``) never touch this counter. An unexpected error resets
    the streak to 0, matching the documented exit criteria. A normal
    would-fire stop action is not an error; it is exactly what a dry run
    should surface, so it does not reset the streak.
    """
    if not dry_run:
        return read_dry_run_streak()

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
        # Idempotent same-day repeat — only an error can regress it further.
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
        # First run ever, or a gap (missed a weekday) — restart the streak at 1.
        raw["consecutive_weekday_count"] = 1
        raw["last_result"] = "ok"
        raw["last_date"] = today.isoformat()
        raw["last_weekday_label"] = today.strftime("%A")

    if monitor_result:
        summary = _summarize_monitor_result(monitor_result)
        summaries: List[Dict[str, Any]] = [summary] + list(raw.get("summaries") or [])
        raw["summaries"] = summaries[:SUMMARY_HISTORY_MAX]

    raw["updated_at"] = _now_iso()
    state = _finalize(raw)
    _atomic_write(_streak_path(), state)
    return state


def record_ack(by: Optional[str], note: Optional[str] = None) -> Dict[str, Any]:
    """Record a James / Reviewer ack for the record.

    This is a durable note only — it never writes ``SWARM_MONITOR_DRY_RUN``
    or any other env var. Flipping the monitor hot still requires an
    operator to change the Elestio environment directly.
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
