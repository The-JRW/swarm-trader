"""Persist last cron/automation summaries under /app/data/automation/.

Single-worker assumption: status files are best-effort local disk, not shared
across replicas. Never write secrets.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

AUTOMATION_DIR = Path(os.environ.get("SWARM_AUTOMATION_DIR") or "/app/data/automation")
LAST_PAPER_RUN_FILE = "last_paper_run.json"
LAST_MONITOR_FILE = "last_monitor.json"
OPS_STATUS_FILE = "ops_status.json"


def _ensure_dir() -> Path:
    AUTOMATION_DIR.mkdir(parents=True, exist_ok=True)
    return AUTOMATION_DIR


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    _ensure_dir()
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, indent=2, default=str)
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Could not read %s (%s)", path, type(e).__name__)
        return None


def write_last_paper_run(summary: Dict[str, Any]) -> Path:
    """Write sanitized last cron paper-run summary."""
    path = _ensure_dir() / LAST_PAPER_RUN_FILE
    payload = {
        "updated_at": _now_iso(),
        **{k: v for k, v in summary.items() if k not in ("secret", "headers", "env")},
    }
    _atomic_write(path, payload)
    _refresh_ops_status()
    return path


def write_last_monitor(summary: Dict[str, Any]) -> Path:
    """Write sanitized last portfolio-monitor summary."""
    path = _ensure_dir() / LAST_MONITOR_FILE
    payload = {
        "updated_at": _now_iso(),
        **{k: v for k, v in summary.items() if k not in ("secret", "headers", "env")},
    }
    _atomic_write(path, payload)
    _refresh_ops_status()
    return path


def _refresh_ops_status() -> None:
    paper = _read_json(_ensure_dir() / LAST_PAPER_RUN_FILE) or {}
    monitor = _read_json(_ensure_dir() / LAST_MONITOR_FILE) or {}
    dry_run_env = (os.environ.get("SWARM_MONITOR_DRY_RUN") or "true").strip().lower()
    payload = {
        "updated_at": _now_iso(),
        "paper_only": True,
        "monitor_dry_run_env": dry_run_env != "false",
        "last_paper_run": {
            "run_id": paper.get("run_id"),
            "status": paper.get("status"),
            "mode": paper.get("mode"),
            "tickers": paper.get("tickers"),
            "execute_trades": paper.get("execute_trades"),
            "created_at": paper.get("created_at") or paper.get("updated_at"),
            "message": paper.get("message"),
            "store_note": paper.get("store_note"),
        }
        if paper
        else None,
        "last_monitor": {
            "timestamp": monitor.get("timestamp") or monitor.get("updated_at"),
            "dry_run": monitor.get("dry_run"),
            "trading_mode": monitor.get("trading_mode"),
            "positions_checked": monitor.get("positions_checked"),
            "stops_triggered": monitor.get("stops_triggered"),
            "eod_flatten": monitor.get("eod_flatten"),
            "actions": monitor.get("actions") or [],
            "warnings": monitor.get("warnings") or [],
            "error": monitor.get("error"),
        }
        if monitor
        else None,
        "paths": {
            "dir": str(AUTOMATION_DIR),
            "last_paper_run": str(AUTOMATION_DIR / LAST_PAPER_RUN_FILE),
            "last_monitor": str(AUTOMATION_DIR / LAST_MONITOR_FILE),
        },
    }
    _atomic_write(_ensure_dir() / OPS_STATUS_FILE, payload)


def read_ops_status() -> Dict[str, Any]:
    """Return combined ops status for UI / cron monitor-status (no secrets)."""
    path = _ensure_dir() / OPS_STATUS_FILE
    data = _read_json(path)
    if data:
        return data
    # Rebuild from parts if ops_status missing
    _refresh_ops_status()
    return _read_json(path) or {
        "updated_at": _now_iso(),
        "paper_only": True,
        "monitor_dry_run_env": (os.environ.get("SWARM_MONITOR_DRY_RUN") or "true").strip().lower()
        != "false",
        "last_paper_run": None,
        "last_monitor": None,
        "paths": {
            "dir": str(AUTOMATION_DIR),
            "last_paper_run": str(AUTOMATION_DIR / LAST_PAPER_RUN_FILE),
            "last_monitor": str(AUTOMATION_DIR / LAST_MONITOR_FILE),
        },
    }


def read_last_monitor() -> Optional[Dict[str, Any]]:
    return _read_json(_ensure_dir() / LAST_MONITOR_FILE)
