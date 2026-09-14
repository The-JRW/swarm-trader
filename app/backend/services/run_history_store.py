"""Durable paper-run history under /app/data/runs/ (last N=50).

Single-replica assumption: local disk only — not shared across replicas.
Never write secrets.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

RUNS_DIR = Path(os.environ.get("SWARM_RUNS_DIR") or "/app/data/runs")
INDEX_FILE = "index.jsonl"
MAX_HISTORY = 50
_LOCK = threading.Lock()


def _ensure_dir() -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return RUNS_DIR


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_path(run_id: str) -> Path:
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_")[:64]
    return _ensure_dir() / f"{safe}.json"


def _sanitize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Drop secrets / oversized payloads; keep digest + summary essentials."""
    summary = record.get("summary")
    compact_summary = None
    if isinstance(summary, dict):
        compact_summary = {
            "mode": summary.get("mode"),
            "instrument": summary.get("instrument"),
            "ticker_count": summary.get("ticker_count"),
            "analyst_count": summary.get("analyst_count"),
            "action_counts": summary.get("action_counts"),
            "paper": summary.get("paper", True),
            "executed_trades": summary.get("executed_trades"),
            "execute_blocked_reason": summary.get("execute_blocked_reason"),
            "conviction_digest": summary.get("conviction_digest"),
        }
        # Keep decision rows truncated
        decisions = summary.get("decisions")
        if isinstance(decisions, list):
            compact_summary["decisions"] = [
                {
                    "ticker": d.get("ticker"),
                    "action": d.get("action"),
                    "quantity": d.get("quantity"),
                    "confidence": d.get("confidence"),
                }
                for d in decisions[:30]
                if isinstance(d, dict)
            ]

    return {
        "run_id": record.get("run_id"),
        "status": record.get("status"),
        "mode": record.get("mode"),
        "instrument": record.get("instrument") or "stocks",
        "tickers": record.get("tickers") or [],
        "strategy_ids": (record.get("strategy_ids") or [])[:40],
        "execute_trades": bool(record.get("execute_trades")),
        "created_at": record.get("created_at"),
        "started_at": record.get("started_at"),
        "completed_at": record.get("completed_at"),
        "error": (str(record["error"])[:500] if record.get("error") else None),
        "summary": compact_summary,
        "conviction_digest": record.get("conviction_digest")
        or (compact_summary or {}).get("conviction_digest"),
        "persisted_at": _now_iso(),
        "paper": True,
    }


def _summary_row(sanitized: Dict[str, Any]) -> Dict[str, Any]:
    digest = sanitized.get("conviction_digest") or {}
    return {
        "run_id": sanitized.get("run_id"),
        "status": sanitized.get("status"),
        "mode": sanitized.get("mode"),
        "instrument": sanitized.get("instrument"),
        "tickers": sanitized.get("tickers") or [],
        "execute_trades": sanitized.get("execute_trades"),
        "created_at": sanitized.get("created_at"),
        "started_at": sanitized.get("started_at"),
        "completed_at": sanitized.get("completed_at"),
        "error": sanitized.get("error"),
        "action_counts": (sanitized.get("summary") or {}).get("action_counts"),
        "conviction_digest": {
            "consensus_count": len(digest.get("consensus") or []) if isinstance(digest, dict) else 0,
            "contested_count": len(digest.get("contested") or []) if isinstance(digest, dict) else 0,
            "risk_rejected_count": len(digest.get("risk_rejected") or [])
            if isinstance(digest, dict)
            else 0,
        }
        if digest
        else None,
        "paper": True,
    }


def persist_run(record: Dict[str, Any]) -> Optional[Path]:
    """Write/update a durable run JSON and refresh the JSONL index (last N)."""
    run_id = record.get("run_id")
    if not run_id:
        return None
    sanitized = _sanitize_record(record)
    path = _run_path(str(run_id))
    with _LOCK:
        try:
            _ensure_dir()
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(sanitized, indent=2, default=str), encoding="utf-8")
            tmp.replace(path)
            _rewrite_index()
            return path
        except Exception as e:
            logger.warning("Could not persist run %s (%s)", run_id, type(e).__name__)
            return None


def _rewrite_index() -> None:
    """Rebuild index.jsonl from individual run files, newest first, capped at MAX_HISTORY."""
    _ensure_dir()
    files = list(RUNS_DIR.glob("*.json"))
    records: List[Dict[str, Any]] = []
    for f in files:
        if f.name.endswith(".tmp"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("run_id"):
                records.append(data)
        except Exception:
            continue

    def _sort_key(r: Dict[str, Any]) -> str:
        return str(r.get("completed_at") or r.get("created_at") or r.get("persisted_at") or "")

    records.sort(key=_sort_key, reverse=True)
    keep = records[:MAX_HISTORY]
    keep_ids = {r["run_id"] for r in keep}

    # Prune older files beyond N
    for r in records[MAX_HISTORY:]:
        try:
            p = _run_path(str(r["run_id"]))
            if p.is_file():
                p.unlink()
        except Exception:
            pass

    index_path = RUNS_DIR / INDEX_FILE
    tmp = index_path.with_suffix(".tmp")
    lines = [json.dumps(_summary_row(r), default=str) for r in keep]
    tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    tmp.replace(index_path)

    # Ensure we didn't leave orphan index entries without files
    _ = keep_ids


def list_history(limit: int = MAX_HISTORY) -> List[Dict[str, Any]]:
    """Return last N sanitized run summaries (newest first)."""
    limit = max(1, min(int(limit or MAX_HISTORY), MAX_HISTORY))
    index_path = _ensure_dir() / INDEX_FILE
    rows: List[Dict[str, Any]] = []
    try:
        if index_path.is_file():
            for line in index_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.warning("Could not read run history index (%s)", type(e).__name__)

    if not rows:
        # Fallback: scan files
        with _LOCK:
            _rewrite_index()
        try:
            if index_path.is_file():
                for line in index_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
        except Exception:
            pass

    return rows[:limit]


def read_run(run_id: str) -> Optional[Dict[str, Any]]:
    path = _run_path(run_id)
    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
