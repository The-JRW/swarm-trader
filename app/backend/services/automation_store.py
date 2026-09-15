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
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

AUTOMATION_DIR = Path(os.environ.get("SWARM_AUTOMATION_DIR") or "/app/data/automation")
LAST_PAPER_RUN_FILE = "last_paper_run.json"
LAST_MONITOR_FILE = "last_monitor.json"
OPS_STATUS_FILE = "ops_status.json"
CRON_RECIPE_FILE = "cron_recipe.json"
LAST_DIGEST_FILE = "last_conviction_digest.json"
LAST_SCAN_FILE = "last_scan.json"
SCAN_HISTORY_FILE = "scan_history.jsonl"
APPLY_RECIPE_MAX = 15
SCAN_HISTORY_MAX = 20

VALID_PRESETS = ("core", "value", "growth", "quant", "custom")
VALID_MODES = ("swing", "day", "auto")

DEFAULT_RECIPE: Dict[str, Any] = {
    "tickers": ["NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "SPY"],
    "preset": "core",
    "mode": "swing",
    "execute_trades": False,
}


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


def _scan_ops_summary(scan: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not scan:
        return None
    return {
        "updated_at": scan.get("updated_at") or scan.get("timestamp"),
        "mode": scan.get("mode"),
        "intersect_universe": scan.get("intersect_universe"),
        "candidate_count": scan.get("candidate_count") or len(scan.get("candidates") or []),
        "tickers": (scan.get("tickers") or [])[:APPLY_RECIPE_MAX],
        "paper_only": True,
    }


def cron_execute_env_allows() -> bool:
    """True only when SWARM_CRON_EXECUTE_TRADES is explicitly truthy."""
    val = (os.environ.get("SWARM_CRON_EXECUTE_TRADES") or "").strip().lower()
    return val in ("1", "true", "yes", "on")


def resolve_cron_execute_trades(recipe_or_body_flag: bool) -> bool:
    """Dual gate: recipe/body true AND env SWARM_CRON_EXECUTE_TRADES truthy."""
    return bool(recipe_or_body_flag) and cron_execute_env_allows()


def _normalize_tickers(tickers: Any) -> List[str]:
    if not isinstance(tickers, list):
        return list(DEFAULT_RECIPE["tickers"])
    cleaned: List[str] = []
    for t in tickers:
        if not t or not str(t).strip():
            continue
        sym = str(t).strip().upper()
        if not sym.replace(".", "").isalnum():
            continue
        if sym not in cleaned:
            cleaned.append(sym)
        if len(cleaned) >= 20:
            break
    return cleaned or list(DEFAULT_RECIPE["tickers"])


def _normalize_recipe(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    preset = str(raw.get("preset") or "core").strip().lower()
    if preset not in VALID_PRESETS:
        preset = "core"
    mode = str(raw.get("mode") or "swing").strip().lower()
    if mode not in VALID_MODES:
        mode = "swing"
    return {
        "tickers": _normalize_tickers(raw.get("tickers")),
        "preset": preset,
        "mode": mode,
        "execute_trades": bool(raw.get("execute_trades")),
        "updated_at": raw.get("updated_at") or _now_iso(),
        "paper_only": True,
    }


def read_cron_recipe() -> Dict[str, Any]:
    """Load cron recipe (no secrets). Defaults if missing."""
    data = _read_json(_ensure_dir() / CRON_RECIPE_FILE)
    if not data:
        recipe = dict(DEFAULT_RECIPE)
        recipe["updated_at"] = None
        recipe["paper_only"] = True
        return recipe
    return _normalize_recipe(data)


def write_cron_recipe(recipe: Dict[str, Any]) -> Dict[str, Any]:
    """Persist cron recipe JSON. Never stores secrets."""
    # Strip any accidental secret-looking keys
    clean_in = {
        k: v
        for k, v in (recipe or {}).items()
        if k
        not in (
            "secret",
            "headers",
            "env",
            "api_key",
            "api_secret",
            "ALPACA_API_KEY",
            "ALPACA_API_SECRET",
            "SWARM_CRON_SECRET",
        )
    }
    normalized = _normalize_recipe(clean_in)
    normalized["updated_at"] = _now_iso()
    _atomic_write(_ensure_dir() / CRON_RECIPE_FILE, normalized)
    _refresh_ops_status()
    return normalized


def write_last_conviction_digest(digest: Dict[str, Any], run_id: Optional[str] = None) -> Path:
    path = _ensure_dir() / LAST_DIGEST_FILE
    payload = {
        "updated_at": _now_iso(),
        "run_id": run_id,
        "digest": digest,
        "paper": True,
    }
    _atomic_write(path, payload)
    _refresh_ops_status()
    return path


def read_last_conviction_digest() -> Optional[Dict[str, Any]]:
    return _read_json(_ensure_dir() / LAST_DIGEST_FILE)


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
    recipe = read_cron_recipe()
    digest_wrap = _read_json(_ensure_dir() / LAST_DIGEST_FILE) or {}
    dry_run_env = (os.environ.get("SWARM_MONITOR_DRY_RUN") or "true").strip().lower()
    payload = {
        "updated_at": _now_iso(),
        "paper_only": True,
        "monitor_dry_run_env": dry_run_env != "false",
        "cron_execute_env_allows": cron_execute_env_allows(),
        "auto_launch_env_allows": auto_launch_env_allows(),
        "recipe": {
            "tickers": recipe.get("tickers"),
            "preset": recipe.get("preset"),
            "mode": recipe.get("mode"),
            "execute_trades": recipe.get("execute_trades"),
            "updated_at": recipe.get("updated_at"),
        },
        "last_conviction_digest": digest_wrap.get("digest") if digest_wrap else None,
        "last_conviction_digest_meta": {
            "run_id": digest_wrap.get("run_id"),
            "updated_at": digest_wrap.get("updated_at"),
        }
        if digest_wrap
        else None,
        "last_paper_run": {
            "run_id": paper.get("run_id"),
            "status": paper.get("status"),
            "mode": paper.get("mode"),
            "tickers": paper.get("tickers"),
            "execute_trades": paper.get("execute_trades"),
            "created_at": paper.get("created_at") or paper.get("updated_at"),
            "message": paper.get("message"),
            "store_note": paper.get("store_note"),
            "conviction_digest": paper.get("conviction_digest"),
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
        "last_scan": _scan_ops_summary(_read_json(_ensure_dir() / LAST_SCAN_FILE)),
        "recent_scans_count": len(read_scan_history(limit=SCAN_HISTORY_MAX)),
        "paths": {
            "dir": str(AUTOMATION_DIR),
            "last_paper_run": str(AUTOMATION_DIR / LAST_PAPER_RUN_FILE),
            "last_monitor": str(AUTOMATION_DIR / LAST_MONITOR_FILE),
            "cron_recipe": str(AUTOMATION_DIR / CRON_RECIPE_FILE),
            "last_conviction_digest": str(AUTOMATION_DIR / LAST_DIGEST_FILE),
            "last_scan": str(AUTOMATION_DIR / LAST_SCAN_FILE),
            "scan_history": str(AUTOMATION_DIR / SCAN_HISTORY_FILE),
        },
    }
    _atomic_write(_ensure_dir() / OPS_STATUS_FILE, payload)


def read_ops_status() -> Dict[str, Any]:
    """Return combined ops status for UI / cron monitor-status (no secrets)."""
    path = _ensure_dir() / OPS_STATUS_FILE
    data = _read_json(path)
    if data:
        # Always refresh env-derived flags
        data["cron_execute_env_allows"] = cron_execute_env_allows()
        data["auto_launch_env_allows"] = auto_launch_env_allows()
        dry_run_env = (os.environ.get("SWARM_MONITOR_DRY_RUN") or "true").strip().lower()
        data["monitor_dry_run_env"] = dry_run_env != "false"
        if "recipe" not in data:
            data["recipe"] = read_cron_recipe()
        return data
    # Rebuild from parts if ops_status missing
    _refresh_ops_status()
    return _read_json(path) or {
        "updated_at": _now_iso(),
        "paper_only": True,
        "monitor_dry_run_env": (os.environ.get("SWARM_MONITOR_DRY_RUN") or "true").strip().lower()
        != "false",
        "cron_execute_env_allows": cron_execute_env_allows(),
        "recipe": read_cron_recipe(),
        "last_conviction_digest": None,
        "last_paper_run": None,
        "last_monitor": None,
        "paths": {
            "dir": str(AUTOMATION_DIR),
            "last_paper_run": str(AUTOMATION_DIR / LAST_PAPER_RUN_FILE),
            "last_monitor": str(AUTOMATION_DIR / LAST_MONITOR_FILE),
            "cron_recipe": str(AUTOMATION_DIR / CRON_RECIPE_FILE),
        },
    }




def auto_launch_env_allows() -> bool:
    """True only when SWARM_AUTO_LAUNCH is explicitly truthy.

    When false/absent, cron swarm-scan is scan-only (ignore apply_recipe/launch).
    """
    val = (os.environ.get("SWARM_AUTO_LAUNCH") or "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _strip_secrets(payload: Dict[str, Any]) -> Dict[str, Any]:
    banned = {
        "secret",
        "headers",
        "env",
        "api_key",
        "api_secret",
        "ALPACA_API_KEY",
        "ALPACA_API_SECRET",
        "SWARM_CRON_SECRET",
        "SWARM_AUTO_LAUNCH",
        "Authorization",
        "authorization",
    }
    if not isinstance(payload, dict):
        return {}
    return {k: v for k, v in payload.items() if k not in banned}


def write_last_scan(summary: Dict[str, Any]) -> Path:
    """Persist last swarm scan JSON (no secrets) + append to scan history."""
    path = _ensure_dir() / LAST_SCAN_FILE
    clean = _strip_secrets(summary or {})
    # Never embed env or credentials
    payload = {
        "updated_at": _now_iso(),
        "paper_only": True,
        **clean,
        "paper_only": True,
    }
    # Cap candidate list size in persisted file
    cands = payload.get("candidates")
    if isinstance(cands, list) and len(cands) > 50:
        payload["candidates"] = cands[:50]
    tickers = payload.get("tickers")
    if isinstance(tickers, list) and len(tickers) > 50:
        payload["tickers"] = tickers[:50]
    _atomic_write(path, payload)
    _append_scan_history(payload)
    _refresh_ops_status()
    return path


def read_last_scan() -> Optional[Dict[str, Any]]:
    return _read_json(_ensure_dir() / LAST_SCAN_FILE)


def _append_scan_history(entry: Dict[str, Any]) -> None:
    """Append one scan summary line; keep last SCAN_HISTORY_MAX (C5)."""
    hist_path = _ensure_dir() / SCAN_HISTORY_FILE
    line_obj = {
        "updated_at": entry.get("updated_at") or _now_iso(),
        "timestamp": entry.get("timestamp"),
        "mode": entry.get("mode"),
        "intersect_universe": entry.get("intersect_universe"),
        "candidate_count": entry.get("candidate_count")
        or len(entry.get("candidates") or []),
        "tickers": (entry.get("tickers") or [])[:APPLY_RECIPE_MAX],
        "candidates_preview": [
            {
                "symbol": c.get("symbol"),
                "sources": c.get("sources"),
            }
            for c in (entry.get("candidates") or [])[:APPLY_RECIPE_MAX]
            if isinstance(c, dict)
        ],
        "paper_only": True,
    }
    try:
        existing: List[str] = []
        if hist_path.is_file():
            existing = [
                ln for ln in hist_path.read_text(encoding="utf-8").splitlines() if ln.strip()
            ]
        existing.append(json.dumps(line_obj, default=str))
        existing = existing[-SCAN_HISTORY_MAX:]
        tmp = hist_path.with_suffix(hist_path.suffix + ".tmp")
        tmp.write_text("\n".join(existing) + "\n", encoding="utf-8")
        tmp.replace(hist_path)
    except Exception as e:
        logger.warning("Could not append scan history (%s)", type(e).__name__)


def read_scan_history(limit: int = 10) -> List[Dict[str, Any]]:
    """Return last K scan summaries (newest first)."""
    hist_path = _ensure_dir() / SCAN_HISTORY_FILE
    limit = max(1, min(int(limit or 10), SCAN_HISTORY_MAX))
    if not hist_path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        for ln in hist_path.read_text(encoding="utf-8").splitlines():
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


def read_last_monitor() -> Optional[Dict[str, Any]]:
    return _read_json(_ensure_dir() / LAST_MONITOR_FILE)
