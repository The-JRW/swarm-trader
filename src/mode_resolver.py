"""E4 — mode auto-resolver lite (pure rules).

Mirrors the documented ``auto_rules`` in ``trading_mode.json`` so ``mode=auto``
resolves to a real trading mode with a persisted, human-readable reason
instead of silently defaulting to swing. This module is intentionally pure —
no I/O, no network — so it is trivial to unit test.

Rule precedence (first match wins), matching ``trading_mode.json``:

  prefer_day_when:
    - VIX > 25            (high volatility → more intraday opportunity)
    - Event day (earnings / FOMC / CPI)
    - Morning gap > 1% on core holdings

  prefer_swing_when:
    - VIX < 20            (low volatility → hold and let winners run)
    - Default             (swing is the safer baseline)

"Portfolio has >3 positions approaching stop loss" from the documented rules
is intentionally **not** implemented in this lite pass — it needs live
position data that is out of scope here; see docs/WAVE_E.md.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

VIX_HIGH_THRESHOLD = 25.0
VIX_LOW_THRESHOLD = 20.0
GAP_THRESHOLD_PCT = 1.0


def resolve_auto_mode_rules(
    *,
    vix: Optional[float] = None,
    gap_pct: Optional[float] = None,
    event_day: bool = False,
) -> Dict[str, Any]:
    """Pure decision: given best-effort signals, pick swing or day + why.

    Any signal may be ``None`` when it could not be fetched — this never
    invents a number; it just skips that rule and falls through.
    """
    if event_day:
        return {
            "resolved_mode": "day",
            "reason": "Event day (earnings/FOMC/CPI) — day mode for event-driven trading",
            "matched_rule": "event_day",
        }

    if vix is not None and vix > VIX_HIGH_THRESHOLD:
        return {
            "resolved_mode": "day",
            "reason": f"VIX {vix:.1f} > {VIX_HIGH_THRESHOLD:.0f} — high volatility favors day mode",
            "matched_rule": "vix_high",
        }

    if gap_pct is not None and abs(gap_pct) > GAP_THRESHOLD_PCT:
        return {
            "resolved_mode": "day",
            "reason": (
                f"Morning gap {gap_pct:+.2f}% > {GAP_THRESHOLD_PCT:.0f}% on core holdings — "
                "event-driven day mode"
            ),
            "matched_rule": "gap",
        }

    if vix is not None and vix < VIX_LOW_THRESHOLD:
        return {
            "resolved_mode": "swing",
            "reason": f"VIX {vix:.1f} < {VIX_LOW_THRESHOLD:.0f} — low volatility favors swing (hold winners)",
            "matched_rule": "vix_low",
        }

    if vix is None and gap_pct is None and not event_day:
        return {
            "resolved_mode": "swing",
            "reason": "Insufficient live VIX/gap data — default swing (safer baseline)",
            "matched_rule": "no_data",
        }

    return {
        "resolved_mode": "swing",
        "reason": "Default — swing is the safer baseline (signals inside neutral band)",
        "matched_rule": "default",
    }
