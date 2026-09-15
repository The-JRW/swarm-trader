"""Performance snapshot writer — wraps performance_tracker_v2 logic for cron.

Writes under /app/data/performance_snapshots/ (or SWARM_PERF_SNAPSHOTS_DIR).
Paper-only; never stores secrets. Returns alpha vs SPY only when real data exists.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SNAPSHOTS_DIR = Path(
    os.environ.get("SWARM_PERF_SNAPSHOTS_DIR")
    or os.environ.get("SWARM_AUTOMATION_DIR", "/app/data/automation").replace(
        "/automation", "/performance_snapshots"
    )
)
if str(SNAPSHOTS_DIR).endswith("/automation"):
    SNAPSHOTS_DIR = Path("/app/data/performance_snapshots")


def _ensure_dir() -> Path:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    return SNAPSHOTS_DIR


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    _ensure_dir()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def load_snapshots(days: Optional[int] = None) -> List[Dict[str, Any]]:
    _ensure_dir()
    files = sorted(SNAPSHOTS_DIR.glob("*.json"))
    # Also check legacy repo snapshots/ if empty
    snapshots: List[Dict[str, Any]] = []
    for f in files:
        if f.name.endswith(".tmp") or f.name.startswith("latest"):
            continue
        try:
            snapshots.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    if days:
        from datetime import timedelta

        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        snapshots = [s for s in snapshots if s.get("date", "") >= cutoff]
    return snapshots


def list_recent_snapshots(limit: int = 30) -> List[Dict[str, Any]]:
    """E2 — sanitized recent snapshots for the perf strip's Details drawer.

    Newest first, capped at ``limit``. Every field here already comes from a
    real snapshot write (equity/cash from Alpaca, SPY/QQQ from yfinance when
    available) — never fabricated.
    """
    snaps = load_snapshots()
    snaps_sorted = sorted(snaps, key=lambda s: (s.get("date") or "", s.get("timestamp") or ""))
    limit = max(1, min(int(limit or 30), 90))
    out = list(reversed(snaps_sorted))[:limit]
    return [
        {
            "date": s.get("date"),
            "timestamp": s.get("timestamp"),
            "equity": s.get("equity"),
            "cash": s.get("cash"),
            "position_count": s.get("position_count"),
            "daily_pnl": s.get("daily_pnl"),
            "daily_pnl_pct": s.get("daily_pnl_pct"),
            "spy_price": s.get("spy_price"),
            "spy_daily_pct": s.get("spy_daily_pct"),
            "alpha_vs_spy_daily": s.get("alpha_vs_spy_daily"),
        }
        for s in out
    ]


def read_latest_snapshot() -> Optional[Dict[str, Any]]:
    latest = _ensure_dir() / "latest.json"
    try:
        if latest.is_file():
            return json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        pass
    snaps = load_snapshots()
    return snaps[-1] if snaps else None


def compute_alpha_vs_spy(snapshots: Optional[List[Dict[str, Any]]] = None) -> Optional[float]:
    """Return portfolio return − SPY return in pct points when both real; else None."""
    snaps = snapshots if snapshots is not None else load_snapshots()
    if len(snaps) < 2:
        # Single snapshot: use daily_pnl_pct vs spy_daily_pct when both present
        if len(snaps) == 1:
            s = snaps[0]
            port = s.get("daily_pnl_pct")
            spy = s.get("spy_daily_pct")
            if port is not None and spy is not None:
                try:
                    return round(float(port) - float(spy), 4)
                except (TypeError, ValueError):
                    return None
        return None
    first, latest = snaps[0], snaps[-1]
    base_eq = first.get("equity")
    curr_eq = latest.get("equity")
    base_spy = first.get("spy_price")
    curr_spy = latest.get("spy_price")
    try:
        if not base_eq or not curr_eq or not base_spy or not curr_spy:
            return None
        port_ret = (float(curr_eq) - float(base_eq)) / float(base_eq) * 100.0
        spy_ret = (float(curr_spy) - float(base_spy)) / float(base_spy) * 100.0
        return round(port_ret - spy_ret, 4)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def take_performance_snapshot(force: bool = False) -> Dict[str, Any]:
    """Fetch paper portfolio + SPY/QQQ and write today's snapshot.

    Prefers Alpaca via src.alpaca_integration (paper). Falls back to None fields
    rather than inventing zeros. Never logs secrets.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snap_file = _ensure_dir() / f"{today}.json"

    if snap_file.is_file() and not force:
        existing = json.loads(snap_file.read_text(encoding="utf-8"))
        return {
            "ok": True,
            "skipped": True,
            "reason": "snapshot_exists",
            "path": str(snap_file),
            "snapshot": existing,
            "paper": True,
        }

    equity = None
    cash = None
    invested = None
    position_count = None
    daily_pnl = None
    daily_pnl_pct = None

    try:
        from src.alpaca_integration import get_alpaca_account, get_alpaca_positions
        from src.config import resolve_mode

        mode = resolve_mode()
        if mode == "auto" or mode not in ("swing", "day", "hit"):
            mode = "swing"
        try:
            account = get_alpaca_account(mode)
            positions = get_alpaca_positions(mode)
        except Exception:
            account = get_alpaca_account("swing")
            positions = get_alpaca_positions("swing")

        equity = float(account.get("equity") or account.get("portfolio_value") or 0)
        cash = float(account.get("cash") or 0)
        invested = equity - cash
        position_count = len(positions or [])
        last_eq = account.get("last_equity")
        if last_eq is not None:
            try:
                last_f = float(last_eq)
                if last_f > 0:
                    daily_pnl = equity - last_f
                    daily_pnl_pct = (daily_pnl / last_f) * 100.0
            except (TypeError, ValueError):
                pass
    except Exception as e:
        logger.warning("Perf snapshot: Alpaca fetch failed (%s)", type(e).__name__)
        return {
            "ok": False,
            "error": f"{type(e).__name__}: portfolio fetch failed",
            "paper": True,
        }

    spy_price = None
    spy_daily_pct = None
    qqq_price = None
    qqq_daily_pct = None

    # Prefer yfinance when available; otherwise leave None (never fake)
    try:
        import yfinance as yf

        spy_hist = yf.Ticker("SPY").history(period="2d", interval="1d")
        if spy_hist is not None and not spy_hist.empty:
            spy_price = float(spy_hist["Close"].iloc[-1])
            if len(spy_hist) >= 2:
                prev = float(spy_hist["Close"].iloc[-2])
                if prev:
                    spy_daily_pct = round((spy_price - prev) / prev * 100.0, 4)
        qqq_hist = yf.Ticker("QQQ").history(period="2d", interval="1d")
        if qqq_hist is not None and not qqq_hist.empty:
            qqq_price = float(qqq_hist["Close"].iloc[-1])
            if len(qqq_hist) >= 2:
                prev = float(qqq_hist["Close"].iloc[-2])
                if prev:
                    qqq_daily_pct = round((qqq_price - prev) / prev * 100.0, 4)
    except Exception as e:
        logger.warning("Perf snapshot: benchmark fetch failed (%s)", type(e).__name__)

    snapshot = {
        "date": today,
        "timestamp": _now_iso(),
        "equity": equity,
        "cash": cash,
        "invested": invested,
        "position_count": position_count,
        "daily_pnl": round(daily_pnl, 2) if daily_pnl is not None else None,
        "daily_pnl_pct": round(daily_pnl_pct, 4) if daily_pnl_pct is not None else None,
        "spy_price": spy_price,
        "spy_daily_pct": spy_daily_pct,
        "qqq_price": qqq_price,
        "qqq_daily_pct": qqq_daily_pct,
        "paper": True,
    }

    # Alpha for the day only when both real
    if daily_pnl_pct is not None and spy_daily_pct is not None:
        snapshot["alpha_vs_spy_daily"] = round(float(daily_pnl_pct) - float(spy_daily_pct), 4)

    _atomic_write(snap_file, snapshot)
    _atomic_write(_ensure_dir() / "latest.json", snapshot)

    all_snaps = load_snapshots()
    alpha = compute_alpha_vs_spy(all_snaps)

    return {
        "ok": True,
        "skipped": False,
        "path": str(snap_file),
        "snapshot": snapshot,
        "alpha_vs_spy": alpha,  # None unless real multi-day or daily data
        "snapshots_count": len(all_snaps),
        "paper": True,
    }
