"""Conviction digest from real agent signals — no invented confidence scores.

Classifies each ticker as:
  - consensus: majority of analyst signals agree buy (bullish) or sell (bearish)
  - contested: bullish and bearish both present with no clear majority
  - risk-rejected: risk manager remaining_position_limit is 0 while analysts lean buy/short
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _norm_signal(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("bullish", "buy", "long"):
        return "bullish"
    if s in ("bearish", "sell", "short"):
        return "bearish"
    if s in ("neutral", "hold"):
        return "neutral"
    return None


def _is_risk_agent(agent_id: str) -> bool:
    a = (agent_id or "").lower()
    return a.startswith("risk_management_agent") or a in ("risk_manager", "risk_management")


def compute_conviction_digest(
    analyst_signals: Optional[Dict[str, Any]],
    tickers: Optional[List[str]] = None,
    decisions: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build digest from real analyst_signals dict.

    Returns:
      {
        "consensus": [{"ticker", "direction", "agree", "total", "signals"}],
        "contested": [{"ticker", "bullish", "bearish", "neutral", "signals"}],
        "risk_rejected": [{"ticker", "reason", "remaining_position_limit"}],
      }
    """
    signals = analyst_signals if isinstance(analyst_signals, dict) else {}
    consensus: List[Dict[str, Any]] = []
    contested: List[Dict[str, Any]] = []
    risk_rejected: List[Dict[str, Any]] = []

    # Discover tickers from signals + explicit list + decisions
    ticker_set = set(t.upper() for t in (tickers or []) if t)
    for agent, by_ticker in signals.items():
        if not isinstance(by_ticker, dict):
            continue
        for t in by_ticker.keys():
            if t and isinstance(t, str):
                ticker_set.add(t.upper())
    if isinstance(decisions, dict):
        for t in decisions.keys():
            if t:
                ticker_set.add(str(t).upper())

    for ticker in sorted(ticker_set):
        votes: Dict[str, str] = {}  # agent -> bullish|bearish|neutral
        remaining_limit = None
        for agent, by_ticker in signals.items():
            if not isinstance(by_ticker, dict):
                continue
            # Match ticker case-insensitively
            entry = by_ticker.get(ticker) or by_ticker.get(ticker.upper()) or by_ticker.get(ticker.lower())
            if not isinstance(entry, dict):
                continue
            if _is_risk_agent(agent):
                lim = entry.get("remaining_position_limit")
                if lim is not None:
                    try:
                        remaining_limit = float(lim)
                    except (TypeError, ValueError):
                        remaining_limit = None
                continue
            sig = _norm_signal(entry.get("signal"))
            if sig:
                votes[agent] = sig

        bullish = sum(1 for v in votes.values() if v == "bullish")
        bearish = sum(1 for v in votes.values() if v == "bearish")
        neutral = sum(1 for v in votes.values() if v == "neutral")
        total = len(votes)

        # Risk-rejected: limit zeroed while analysts lean buy (bullish > bearish)
        if remaining_limit is not None and remaining_limit <= 0 and bullish > bearish and bullish > 0:
            risk_rejected.append(
                {
                    "ticker": ticker,
                    "reason": "remaining_position_limit=0 with bullish majority",
                    "remaining_position_limit": 0.0,
                    "bullish": bullish,
                    "bearish": bearish,
                }
            )

        if total == 0:
            continue

        # Also check decision held/zeroed due to risk when analysts wanted action
        if isinstance(decisions, dict):
            dec = decisions.get(ticker) or decisions.get(ticker.upper())
            if isinstance(dec, dict):
                action = str(dec.get("action") or "hold").lower()
                qty = dec.get("quantity") or 0
                try:
                    qty_n = float(qty)
                except (TypeError, ValueError):
                    qty_n = 0
                if (
                    remaining_limit is not None
                    and remaining_limit <= 0
                    and action in ("hold", "sell")
                    and bullish > bearish
                    and ticker not in {r["ticker"] for r in risk_rejected}
                ):
                    risk_rejected.append(
                        {
                            "ticker": ticker,
                            "reason": "risk limit blocked buy (decision hold/flat)",
                            "remaining_position_limit": float(remaining_limit),
                            "decision_action": action,
                            "decision_qty": qty_n,
                        }
                    )

        signal_list = [{"agent": a, "signal": s} for a, s in sorted(votes.items())]

        if bullish > bearish and bullish > neutral and bullish * 2 > total:
            consensus.append(
                {
                    "ticker": ticker,
                    "direction": "buy",
                    "agree": bullish,
                    "total": total,
                    "signals": signal_list,
                }
            )
        elif bearish > bullish and bearish > neutral and bearish * 2 > total:
            consensus.append(
                {
                    "ticker": ticker,
                    "direction": "sell",
                    "agree": bearish,
                    "total": total,
                    "signals": signal_list,
                }
            )
        elif bullish > 0 and bearish > 0:
            contested.append(
                {
                    "ticker": ticker,
                    "bullish": bullish,
                    "bearish": bearish,
                    "neutral": neutral,
                    "signals": signal_list,
                }
            )
        # Pure neutral / no majority → neither consensus nor contested

    return {
        "consensus": consensus,
        "contested": contested,
        "risk_rejected": risk_rejected,
        "ticker_count": len(ticker_set),
        "source": "analyst_signals",
    }


HINTS_NOTE = (
    "Display-only suggestions for the next Apply. Nothing is written to the cron "
    "recipe without an explicit Apply from the user."
)


def build_recipe_hints(
    digest: Optional[Dict[str, Any]],
    *,
    current_tickers: Optional[List[str]] = None,
    limit: int = 15,
) -> Dict[str, Any]:
    """D5 — turn a conviction digest into next-recipe hints (never auto-applied).

    Contested tickers rank first (the swarm disagreed, so another paper pass is
    the most informative), then consensus names. Risk-rejected tickers are
    reported as excluded, never suggested.
    """
    cap = max(1, min(int(limit or 15), 15))
    digest = digest if isinstance(digest, dict) else {}
    current = {str(t).strip().upper() for t in (current_tickers or []) if t}

    hints: List[Dict[str, Any]] = []
    seen: set = set()
    rejected = {
        str(r.get("ticker") or "").strip().upper()
        for r in (digest.get("risk_rejected") or [])
        if isinstance(r, dict) and r.get("ticker")
    }

    def _add(ticker: Any, kind: str, reason: str) -> None:
        sym = str(ticker or "").strip().upper()
        if not sym or sym in seen or sym in rejected or len(hints) >= cap:
            return
        seen.add(sym)
        hints.append(
            {
                "ticker": sym,
                "kind": kind,
                "reason": reason,
                "in_current_recipe": sym in current,
            }
        )

    for c in digest.get("contested") or []:
        if not isinstance(c, dict):
            continue
        bull = c.get("bullish") or 0
        bear = c.get("bearish") or 0
        _add(c.get("ticker"), "contested", f"contested — bull {bull} / bear {bear}, worth another pass")

    for c in digest.get("consensus") or []:
        if not isinstance(c, dict):
            continue
        direction = str(c.get("direction") or "").lower() or "agree"
        agree = c.get("agree") or 0
        total = c.get("total") or 0
        _add(c.get("ticker"), "consensus", f"consensus {direction} ({agree}/{total} analysts)")

    excluded = [
        {
            "ticker": str(r.get("ticker") or "").strip().upper(),
            "kind": "risk_rejected",
            "reason": str(r.get("reason") or "risk manager blocked entry"),
        }
        for r in (digest.get("risk_rejected") or [])
        if isinstance(r, dict) and r.get("ticker")
    ]

    return {
        "suggested_tickers": [h["ticker"] for h in hints],
        "hints": hints,
        "excluded": excluded,
        "cap": cap,
        "display_only": True,
        "auto_write": False,
        "requires_explicit_apply": True,
        "source": digest.get("source") or "conviction_digest",
        "note": HINTS_NOTE,
    }
