"""E6 — AutoResearch review queue (stub).

Lists recent experiments/runs from the existing offline evolution loop
(``autoresearch/evolve.py`` → ``autoresearch/experiments/log.jsonl`` +
``runs.jsonl``) as an in-app review queue. This is a **read-only view over
an existing offline artifact** plus a **display/UX-only** approve/reject
annotation.

Hard constraints (do not relax without a new reviewer binding):

- Approve/reject here **never** writes ``autoresearch/strategy.py``, never
  touches ``trading_mode.json``, ``cron_recipe.json``, or any other
  production config, and never triggers ``evolve.py`` or a backtest.
- ``evolve.py`` already applies "kept" experiments to ``strategy.py``
  *offline*, outside this app — this queue does not change that behavior;
  it only gives a human a place to record a review opinion for the record.
- Paper-only; nothing here can reach live trading.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

EXPERIMENTS_LOG_FILE = "log.jsonl"
RUNS_LOG_FILE = "runs.jsonl"
REVIEW_STATE_FILE = "autoresearch_review.json"
VALID_DECISIONS = ("approved", "rejected", "pending")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _experiments_dir() -> Path:
    return _repo_root() / "autoresearch" / "experiments"


def _automation_dir() -> Path:
    from app.backend.services.automation_store import AUTOMATION_DIR

    AUTOMATION_DIR.mkdir(parents=True, exist_ok=True)
    return AUTOMATION_DIR


def _review_state_path() -> Path:
    return _automation_dir() / REVIEW_STATE_FILE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.is_file():
        return rows
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except Exception:
                continue
    except Exception as e:
        logger.warning("Could not read %s (%s)", path, type(e).__name__)
    return rows


def _sanitize_experiment(row: Dict[str, Any]) -> Dict[str, Any]:
    """Compact experiment row — truncates the diff, keeps real metrics only."""
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    diff = row.get("diff")
    diff_preview = None
    if isinstance(diff, str) and diff:
        diff_preview = diff[:1500] + ("…" if len(diff) > 1500 else "")
    return {
        "experiment_id": row.get("experiment_id"),
        "timestamp": row.get("timestamp"),
        "iteration": row.get("iteration"),
        "mode": row.get("mode"),
        "hypothesis": (row.get("hypothesis") or "")[:500] if isinstance(row.get("hypothesis"), str) else row.get("hypothesis"),
        "fitness_score": metrics.get("fitness", row.get("fitness_score")),
        "kept": bool(row.get("kept")),
        "error": (row.get("error") or None),
        "metrics": {
            k: metrics.get(k)
            for k in (
                "total_return_pct",
                "sharpe_ratio",
                "sortino_ratio",
                "max_drawdown_pct",
                "win_rate",
                "profit_factor",
                "num_trades",
            )
            if k in metrics
        },
        "diff_preview": diff_preview,
    }


def read_recent_experiments(limit: int = 20) -> List[Dict[str, Any]]:
    """Newest-first sanitized experiments from ``experiments/log.jsonl``."""
    limit = max(1, min(int(limit or 20), 100))
    rows = _read_jsonl(_experiments_dir() / EXPERIMENTS_LOG_FILE)
    rows.sort(key=lambda r: str(r.get("timestamp") or ""))
    rows.reverse()
    return [_sanitize_experiment(r) for r in rows[:limit]]


def _sanitize_run(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "run_id": row.get("run_id"),
        "timestamp_start": row.get("timestamp_start"),
        "timestamp_end": row.get("timestamp_end"),
        "mode": row.get("mode"),
        "iterations_requested": row.get("iterations_requested"),
        "iterations_completed": row.get("iterations_completed"),
        "stop_reason": row.get("stop_reason"),
        "baseline_fitness": row.get("baseline_fitness"),
        "best_fitness": row.get("best_fitness"),
        "improvement": row.get("improvement"),
        "keep_count": row.get("keep_count"),
        "total_experiments": row.get("total_experiments"),
        "error_count": row.get("error_count"),
        "top_hypothesis": (row.get("top_hypothesis") or "")[:500]
        if isinstance(row.get("top_hypothesis"), str)
        else row.get("top_hypothesis"),
    }


def read_recent_runs(limit: int = 10) -> List[Dict[str, Any]]:
    """Newest-first sanitized evolution runs from ``experiments/runs.jsonl``."""
    limit = max(1, min(int(limit or 10), 50))
    rows = _read_jsonl(_experiments_dir() / RUNS_LOG_FILE)
    rows.sort(key=lambda r: str(r.get("timestamp_end") or r.get("timestamp_start") or ""))
    rows.reverse()
    return [_sanitize_run(r) for r in rows[:limit]]


def _read_review_state() -> Dict[str, Any]:
    path = _review_state_path()
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Could not read %s (%s)", path, type(e).__name__)
    return {}


def _write_review_state(state: Dict[str, Any]) -> None:
    path = _review_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def get_review_queue(limit: int = 20) -> Dict[str, Any]:
    """Recent experiments merged with any recorded (display-only) decisions."""
    experiments = read_recent_experiments(limit=limit)
    decisions = _read_review_state()
    for exp in experiments:
        eid = exp.get("experiment_id")
        exp["review"] = decisions.get(eid) if eid else None
    return {
        "paper_only": True,
        "read_only_source": True,
        "limit": limit,
        "experiments": experiments,
        "recent_runs": read_recent_runs(limit=5),
        "note": (
            "Display/UX-only stub. Approve/reject here never writes "
            "autoresearch/strategy.py or any production config, and never "
            "triggers evolve.py — it only records a review opinion."
        ),
        "source_files": [
            str(_experiments_dir() / EXPERIMENTS_LOG_FILE),
            str(_experiments_dir() / RUNS_LOG_FILE),
        ],
    }


def record_review_decision(
    experiment_id: str,
    decision: str,
    by: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Record (or clear) a display-only approve/reject annotation.

    Never touches ``autoresearch/strategy.py`` or any config file — this is
    purely a note attached to the experiment_id for the record.
    """
    decision = (decision or "").strip().lower()
    if decision not in VALID_DECISIONS:
        raise ValueError(f"decision must be one of {VALID_DECISIONS}")
    if not experiment_id or not str(experiment_id).strip():
        raise ValueError("experiment_id is required")

    state = _read_review_state()
    eid = str(experiment_id).strip()
    if decision == "pending":
        state.pop(eid, None)
    else:
        state[eid] = {
            "decision": decision,
            "by": (by or "unspecified").strip()[:120],
            "note": (note or "").strip()[:500] or None,
            "at": _now_iso(),
            "applied": False,  # always false — this stub never auto-applies
        }
    _write_review_state(state)
    return {
        "experiment_id": eid,
        "review": state.get(eid),
        "note": "Recorded for the record only — no config was written.",
    }
