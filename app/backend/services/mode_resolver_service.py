"""E4 — mode auto-resolver lite (I/O layer).

When ``mode=auto`` (``trading_mode.json`` has no active human override and its
``mode`` field is ``"auto"``), this resolves a real ``swing``/``day`` mode
using best-effort VIX + SPY gap signals via the documented rules in
``src.mode_resolver`` and persists the reason so the Strategies UI can show
*why* — instead of the previous silent "fall back to swing" behavior.

**Human override always wins.** If ``trading_mode.json`` has an active
override, or ``mode`` is explicitly ``swing``/``day`` (not ``auto``), this
module reports that fact and does not compute or overwrite anything.

Never invents signals: VIX / gap fetch failures leave those fields ``None``
and the pure resolver falls back to a documented default with an honest
reason (see ``src.mode_resolver``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

RESOLUTION_FILE = "mode_resolution.json"


def _automation_dir() -> Path:
    from app.backend.services.automation_store import AUTOMATION_DIR

    AUTOMATION_DIR.mkdir(parents=True, exist_ok=True)
    return AUTOMATION_DIR


def _resolution_path() -> Path:
    return _automation_dir() / RESOLUTION_FILE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    import json

    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Could not read %s (%s)", path, type(e).__name__)
        return None


def read_last_mode_resolution() -> Optional[Dict[str, Any]]:
    return _read_json(_resolution_path())


def _read_trading_mode_file() -> Dict[str, Any]:
    """Raw ``trading_mode.json`` (no side effects on override expiry)."""
    mode_file = Path(__file__).resolve().parents[3] / "trading_mode.json"
    if not mode_file.exists():
        return {}
    try:
        import json

        return json.loads(mode_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _override_active(raw: Dict[str, Any]) -> Optional[str]:
    """Return the active override mode if one is set and not expired."""
    override = raw.get("override")
    if not override:
        return None
    until = raw.get("override_until")
    if until:
        try:
            expiry = datetime.fromisoformat(until)
            now = datetime.now(expiry.tzinfo) if expiry.tzinfo else datetime.now()
            if now >= expiry:
                return None  # expired — resolve_mode() will clear it on next read
        except (TypeError, ValueError):
            pass
    return override


def gather_signals() -> Dict[str, Any]:
    """Best-effort VIX + SPY gap. Never raises; missing data stays ``None``."""
    vix: Optional[float] = None
    gap_pct: Optional[float] = None

    try:
        import yfinance as yf

        vix_hist = yf.Ticker("^VIX").history(period="1d", interval="1d")
        if vix_hist is not None and not vix_hist.empty:
            vix = float(vix_hist["Close"].iloc[-1])
    except Exception as e:
        logger.info("Mode resolver: VIX fetch unavailable (%s)", type(e).__name__)

    try:
        import yfinance as yf

        spy_hist = yf.Ticker("SPY").history(period="2d", interval="1d")
        if spy_hist is not None and len(spy_hist) >= 2:
            prev_close = float(spy_hist["Close"].iloc[-2])
            today_open = float(spy_hist["Open"].iloc[-1])
            if prev_close:
                gap_pct = round((today_open - prev_close) / prev_close * 100.0, 4)
    except Exception as e:
        logger.info("Mode resolver: SPY gap fetch unavailable (%s)", type(e).__name__)

    # Lite calendar — no external API; operators can flag today as an event
    # day in trading_mode.json (`"event_day": true`) ahead of FOMC/CPI/earnings.
    event_day = bool(_read_trading_mode_file().get("event_day"))

    return {"vix": vix, "gap_pct": gap_pct, "event_day": event_day}


def compute_and_persist_mode_resolution(force: bool = False) -> Dict[str, Any]:
    """Resolve ``mode=auto`` and persist the reason. Human override always wins.

    Returns a payload describing which path was taken:
      - ``active == "override"``  → human override in effect, nothing computed
      - ``active == "explicit"``  → mode literal is swing/day, not auto
      - ``active == "auto"``      → freshly computed via VIX/gap/calendar rules
    """
    raw = _read_trading_mode_file()
    override = _override_active(raw)
    if override:
        payload = {
            "active": "override",
            "resolved_mode": override,
            "reason": "Human override active — wins over auto-resolution",
            "override": override,
            "computed_at": _now_iso(),
            "signals": None,
        }
        _atomic_write(_resolution_path(), payload)
        return payload

    literal_mode = (raw.get("mode") or "swing").strip().lower()
    if literal_mode != "auto":
        payload = {
            "active": "explicit",
            "resolved_mode": literal_mode if literal_mode in ("swing", "day") else "swing",
            "reason": f"Mode explicitly set to '{literal_mode}' (not auto)",
            "override": None,
            "computed_at": _now_iso(),
            "signals": None,
        }
        _atomic_write(_resolution_path(), payload)
        return payload

    if not force:
        cached = read_last_mode_resolution()
        if cached and cached.get("active") == "auto":
            return cached

    from src.mode_resolver import resolve_auto_mode_rules

    signals = gather_signals()
    decision = resolve_auto_mode_rules(
        vix=signals.get("vix"), gap_pct=signals.get("gap_pct"), event_day=bool(signals.get("event_day"))
    )
    payload = {
        "active": "auto",
        "resolved_mode": decision["resolved_mode"],
        "reason": decision["reason"],
        "matched_rule": decision["matched_rule"],
        "override": None,
        "computed_at": _now_iso(),
        "signals": signals,
    }
    _atomic_write(_resolution_path(), payload)
    return payload
