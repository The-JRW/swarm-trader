"""E3 — Session digest center.

After any paper run (Strategies UI or cron — both flow through
``paper_run_service.execute_paper_run``), build a durable digest from **real**
run fields only: ``action_counts``, decision count, the existing conviction
digest (B3, already computed from real ``analyst_signals``), and
``trade_results`` filled/blocked counts. **No invented scores** — everything
here is a direct count or pass-through of a field the run already produced.

Persisted under ``/app/data/automation/session_digests.jsonl`` (last
``SESSION_DIGEST_MAX``), mirroring the ``scan_history.jsonl`` pattern from
Wave C. Surfaced in Ops + the Book pane's run history, which already deep
links to a run by ``run_id``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SESSION_DIGEST_FILE = "session_digests.jsonl"
SESSION_DIGEST_MAX = 20


def _automation_dir() -> Path:
    from app.backend.services.automation_store import AUTOMATION_DIR

    AUTOMATION_DIR.mkdir(parents=True, exist_ok=True)
    return AUTOMATION_DIR


def _digest_path() -> Path:
    return _automation_dir() / SESSION_DIGEST_FILE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _classify_trade_results(trade_results: Optional[List[Dict[str, Any]]]) -> Dict[str, int]:
    """Filled vs blocked counts from real ``trade_results`` rows only."""
    filled = 0
    blocked = 0
    other = 0
    for r in trade_results or []:
        if not isinstance(r, dict):
            continue
        success = r.get("success")
        if success is True:
            filled += 1
        elif success is False:
            blocked += 1
        else:
            other += 1
    total = filled + blocked + other
    return {"filled": filled, "blocked": blocked, "other": other, "total": total}


def build_session_digest(
    run_id: str,
    record: Optional[Dict[str, Any]],
    summary: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compact digest from a run's real fields — no invented scores."""
    record = record or {}
    summary = summary or {}
    conviction = summary.get("conviction_digest") or {}
    decisions = summary.get("decisions") or []
    mode_auto_resolution = summary.get("mode_auto_resolution")

    return {
        "run_id": run_id,
        "timestamp": _now_iso(),
        "mode": summary.get("mode") or record.get("mode"),
        "instrument": summary.get("instrument") or record.get("instrument") or "stocks",
        "tickers": record.get("tickers") or [],
        "ticker_count": summary.get("ticker_count") or len(record.get("tickers") or []),
        "analyst_count": summary.get("analyst_count"),
        "action_counts": summary.get("action_counts") or {},
        "decision_count": len(decisions) if isinstance(decisions, list) else 0,
        "conviction": {
            "consensus_count": len(conviction.get("consensus") or []) if isinstance(conviction, dict) else 0,
            "contested_count": len(conviction.get("contested") or []) if isinstance(conviction, dict) else 0,
            "risk_rejected_count": len(conviction.get("risk_rejected") or [])
            if isinstance(conviction, dict)
            else 0,
        },
        "executed_trades": bool(summary.get("executed_trades")),
        "execute_blocked_reason": summary.get("execute_blocked_reason"),
        "trade_results": _classify_trade_results(summary.get("trade_results")),
        "mode_auto_resolution_reason": mode_auto_resolution.get("reason")
        if isinstance(mode_auto_resolution, dict)
        else None,
        "source": "real_run_fields",
        "paper": True,
    }


def write_session_digest(
    run_id: str,
    record: Optional[Dict[str, Any]] = None,
    summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build + append a session digest; keeps the last ``SESSION_DIGEST_MAX``."""
    digest = build_session_digest(run_id, record, summary)
    path = _digest_path()
    try:
        existing: List[str] = []
        if path.is_file():
            existing = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        existing.append(json.dumps(digest, default=str))
        existing = existing[-SESSION_DIGEST_MAX:]
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(existing) + "\n", encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        logger.warning("Could not append session digest for %s (%s)", run_id, type(e).__name__)
    return digest


def read_session_digests(limit: int = 10) -> List[Dict[str, Any]]:
    """Last K session digests, newest first."""
    path = _digest_path()
    limit = max(1, min(int(limit or 10), SESSION_DIGEST_MAX))
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        for ln in path.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                rows.append(json.loads(ln))
            except Exception:
                continue
    except Exception:
        return []
    rows.reverse()
    return rows[:limit]
