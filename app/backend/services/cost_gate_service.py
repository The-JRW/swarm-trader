"""F2 — Cost / microstructure gate (pre-execute), mandatory for HIT execute.

Coarse, documented heuristic gate — **not** a limit-order-book model and not a
claim of true HFT microstructure modeling. It exists because the research
behind Wave F (see ``docs/WAVE_F_HIT.md``) found that many "high-frequency"
momentum/mean-reversion strategies only look profitable before realistic
costs; bid-ask bounce looks like mean reversion until spread + turnover costs
are subtracted.

Two checks, either of which blocks a proposed **entry** (buy/short only —
exits/holds always pass through):

  1. Estimated round-trip cost (2x half-spread) >= a configured bps budget.
  2. This trade would push same-day gross turnover over a configured budget
     (fraction of equity).

Half-spread is estimated from a live Alpaca quote when available; otherwise a
documented ticker-class default is used and clearly labeled as *assumed*, not
measured — this module never presents an assumption as real market data.

Blocked entries are tagged ``rule="cost_gate"`` so they surface distinctly in
trade_results / the conviction digest / the Ops HIT strip (F5).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

RULE_COST_GATE = "cost_gate"

# Ticker-class default *half*-spread assumptions, in bps of price. Used only
# when a live quote is unavailable. These are documented assumptions, not
# measured market data.
DEFAULT_HALF_SPREAD_BPS_LIQUID = 2.5
DEFAULT_HALF_SPREAD_BPS_ETF = 1.0
_ETF_ANCHORS = {"SPY", "QQQ"}

DEFAULT_COST_GATE_BPS_BUDGET = 15.0
DEFAULT_TURNOVER_BUDGET_PCT = 200.0  # percent of equity per day


def default_cost_gate_bps_budget() -> float:
    """Round-trip cost budget in bps. Env ``SWARM_HIT_COST_GATE_BPS``."""
    try:
        return float(os.environ.get("SWARM_HIT_COST_GATE_BPS") or DEFAULT_COST_GATE_BPS_BUDGET)
    except (TypeError, ValueError):
        return DEFAULT_COST_GATE_BPS_BUDGET


def default_turnover_budget_pct() -> float:
    """Same-day gross turnover budget as a fraction of equity.

    Env ``SWARM_HIT_TURNOVER_BUDGET_PCT`` is a percent (e.g. 200 = 200% of
    equity/day — turnover, not net exposure). Returns a fraction (2.0).
    """
    try:
        pct = float(os.environ.get("SWARM_HIT_TURNOVER_BUDGET_PCT") or DEFAULT_TURNOVER_BUDGET_PCT)
    except (TypeError, ValueError):
        pct = DEFAULT_TURNOVER_BUDGET_PCT
    return pct / 100.0


def estimate_half_spread_bps(
    ticker: str, quote: Optional[Dict[str, Any]] = None
) -> Tuple[float, str]:
    """Half-spread in bps + a short provenance note.

    Uses a live bid/ask quote when both sides are positive and sane; else
    falls back to a ticker-class default that is explicitly labeled
    ``ticker_class_default_assumed`` (never presented as measured data).
    """
    if isinstance(quote, dict):
        try:
            bid = float(quote.get("bp") or quote.get("bid_price") or quote.get("bid") or 0)
            ask = float(quote.get("ap") or quote.get("ask_price") or quote.get("ask") or 0)
            if bid > 0 and ask > 0 and ask >= bid:
                mid = (bid + ask) / 2.0
                if mid > 0:
                    half_spread_bps = ((ask - bid) / mid) * 10000.0 / 2.0
                    return round(half_spread_bps, 4), "live_quote"
        except (TypeError, ValueError):
            pass
    sym = (ticker or "").strip().upper()
    default_bps = DEFAULT_HALF_SPREAD_BPS_ETF if sym in _ETF_ANCHORS else DEFAULT_HALF_SPREAD_BPS_LIQUID
    return default_bps, "ticker_class_default_assumed"


@dataclass
class CostGateResult:
    approved: bool
    ticker: str
    action: str
    qty: float
    notional: float
    half_spread_bps: float
    round_trip_cost_bps: float
    cost_budget_bps: float
    quote_source: str
    turnover_before: float
    turnover_after: float
    turnover_budget: float
    reason: str
    rule: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "ticker": self.ticker,
            "action": self.action,
            "qty": self.qty,
            "notional": round(self.notional, 2),
            "half_spread_bps": self.half_spread_bps,
            "round_trip_cost_bps": self.round_trip_cost_bps,
            "cost_budget_bps": self.cost_budget_bps,
            "quote_source": self.quote_source,
            "turnover_before": round(self.turnover_before, 2),
            "turnover_after": round(self.turnover_after, 2),
            "turnover_budget": round(self.turnover_budget, 2),
            "reason": self.reason,
            "rule": self.rule,
        }


def evaluate_cost_gate(
    *,
    ticker: str,
    action: str,
    qty: float,
    price: float,
    equity: float,
    turnover_today: float = 0.0,
    quote: Optional[Dict[str, Any]] = None,
    cost_budget_bps: Optional[float] = None,
    turnover_budget_pct: Optional[float] = None,
) -> CostGateResult:
    """Pre-execute cost/microstructure gate for one proposed HIT trade.

    Pure function — no I/O, no network — deliberately easy to unit test.
    Only ``buy``/``short`` (new entries) can be blocked; ``sell``/``cover``/
    ``hold`` always pass through untouched.
    """
    action_l = (action or "").strip().lower()
    qty_f = abs(float(qty or 0))
    price_f = float(price or 0)
    notional = qty_f * price_f
    budget_bps = float(
        cost_budget_bps if cost_budget_bps is not None else default_cost_gate_bps_budget()
    )
    turnover_budget_frac = float(
        turnover_budget_pct if turnover_budget_pct is not None else default_turnover_budget_pct()
    )
    turnover_budget = equity * turnover_budget_frac if equity and equity > 0 else 0.0

    half_spread_bps, quote_source = estimate_half_spread_bps(ticker, quote)
    round_trip_bps = round(half_spread_bps * 2.0, 4)
    turnover_before = float(turnover_today or 0.0)
    turnover_after = turnover_before + notional

    common = dict(
        ticker=ticker,
        action=action_l,
        qty=qty_f,
        notional=notional,
        half_spread_bps=half_spread_bps,
        round_trip_cost_bps=round_trip_bps,
        cost_budget_bps=budget_bps,
        quote_source=quote_source,
        turnover_budget=turnover_budget,
    )

    if action_l not in ("buy", "short"):
        return CostGateResult(
            approved=True,
            turnover_before=turnover_before,
            turnover_after=turnover_before,
            reason="Exit/hold — cost gate only applies to new entries (buy/short)",
            **common,
        )

    if round_trip_bps >= budget_bps:
        return CostGateResult(
            approved=False,
            turnover_before=turnover_before,
            turnover_after=turnover_before,
            reason=(
                f"BLOCKED: estimated round-trip cost {round_trip_bps:.2f}bps "
                f"(half-spread {half_spread_bps:.2f}bps x2, source={quote_source}) "
                f">= budget {budget_bps:.2f}bps"
            ),
            rule=RULE_COST_GATE,
            **common,
        )

    if turnover_budget > 0 and turnover_after > turnover_budget:
        return CostGateResult(
            approved=False,
            turnover_before=turnover_before,
            turnover_after=turnover_before,
            reason=(
                f"BLOCKED: same-day turnover would reach ${turnover_after:,.0f} "
                f"(budget ${turnover_budget:,.0f} = {turnover_budget_frac*100:.0f}% of equity)"
            ),
            rule=RULE_COST_GATE,
            **common,
        )

    return CostGateResult(
        approved=True,
        turnover_before=turnover_before,
        turnover_after=turnover_after,
        reason=f"APPROVED: round-trip {round_trip_bps:.2f}bps < budget {budget_bps:.2f}bps",
        **common,
    )


def apply_cost_gate_to_decisions(
    decisions: Dict[str, Any],
    *,
    prices: Dict[str, float],
    equity: float,
    turnover_today: float = 0.0,
    quotes: Optional[Dict[str, Dict[str, Any]]] = None,
    cost_budget_bps: Optional[float] = None,
    turnover_budget_pct: Optional[float] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Run the cost gate over a decisions dict. Pure — no I/O.

    Returns ``(filtered_decisions, rejects)``. ``filtered_decisions`` mirrors
    ``decisions`` but blocked buy/short entries are downgraded to
    ``action="hold", quantity=0`` so risk_manager/execute never sees them —
    the original decisions (with the LLM's reasoning) are untouched for
    display; this only controls what gets executed. Entries with no known
    price are passed through ungated (never fabricates a price) but this is
    logged by the caller as a note, not silently dropped.
    """
    filtered: Dict[str, Any] = {}
    rejects: List[Dict[str, Any]] = []
    running_turnover = float(turnover_today or 0.0)
    quotes = quotes or {}
    prices = prices or {}

    for ticker, decision in (decisions or {}).items():
        if not isinstance(decision, dict):
            filtered[ticker] = decision
            continue
        action = str(decision.get("action") or "hold").lower()
        qty = decision.get("quantity") or 0
        price = prices.get(ticker) or prices.get(str(ticker).upper()) or 0

        if action not in ("buy", "short") or not qty or not price:
            filtered[ticker] = decision
            continue

        result = evaluate_cost_gate(
            ticker=ticker,
            action=action,
            qty=qty,
            price=price,
            equity=equity,
            turnover_today=running_turnover,
            quote=quotes.get(ticker) or quotes.get(str(ticker).upper()),
            cost_budget_bps=cost_budget_bps,
            turnover_budget_pct=turnover_budget_pct,
        )
        if result.approved:
            running_turnover = result.turnover_after
            filtered[ticker] = decision
        else:
            filtered[ticker] = {**decision, "action": "hold", "quantity": 0}
            rejects.append(result.to_dict())

    return filtered, rejects


def fetch_quotes_and_prices(
    tickers: List[str],
) -> Tuple[Dict[str, float], Dict[str, Dict[str, Any]]]:
    """Best-effort live quotes + a usable price per ticker (network I/O).

    Prefers the quote mid-price (also used for the spread estimate); falls
    back to the latest trade price when no usable quote exists. Never
    fabricates a price — a ticker with neither simply is absent from the
    returned dicts.
    """
    prices: Dict[str, float] = {}
    quotes: Dict[str, Dict[str, Any]] = {}
    try:
        from src.tools.alpaca_data import alpaca_credentials_configured, get_latest_quote, get_latest_trade
    except Exception as e:  # pragma: no cover - import should always succeed in app
        logger.warning("HIT cost gate: could not import alpaca_data (%s)", type(e).__name__)
        return prices, quotes

    if not alpaca_credentials_configured():
        return prices, quotes

    for t in tickers or []:
        sym = str(t).strip().upper()
        if not sym or sym in prices:
            continue
        try:
            quote = get_latest_quote(sym)
        except Exception:
            quote = None
        price: Optional[float] = None
        if isinstance(quote, dict):
            try:
                bid = float(quote.get("bp") or 0)
                ask = float(quote.get("ap") or 0)
                if bid > 0 and ask > 0:
                    price = (bid + ask) / 2.0
                    quotes[sym] = quote
            except (TypeError, ValueError):
                price = None
        if price is None:
            try:
                trade = get_latest_trade(sym)
                if isinstance(trade, dict) and trade.get("p"):
                    price = float(trade["p"])
            except Exception:
                price = None
        if price and price > 0:
            prices[sym] = price

    return prices, quotes


def gate_hit_decisions_for_execute(
    decisions: Dict[str, Any], mode: str
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, float]]:
    """Network-touching wrapper: fetch quotes/equity/turnover, then gate.

    Only meaningful for ``mode == "hit"``; other modes pass decisions through
    unchanged with no rejects. Returns ``(filtered_decisions, rejects, prices)``
    — ``prices`` lets the caller compute an honest (if partial — gated
    tickers only) turnover estimate for the Ops HIT strip (F5).
    """
    if mode != "hit":
        return decisions, [], {}

    entry_tickers = [
        t
        for t, d in (decisions or {}).items()
        if isinstance(d, dict) and str(d.get("action") or "").lower() in ("buy", "short")
    ]
    prices, quotes = fetch_quotes_and_prices(entry_tickers) if entry_tickers else ({}, {})

    equity = 0.0
    try:
        from src.alpaca_integration import get_alpaca_account

        acct = get_alpaca_account("hit") or {}
        equity = float(acct.get("equity") or acct.get("portfolio_value") or 0)
    except Exception as e:
        logger.warning("HIT cost gate: could not fetch equity (%s)", type(e).__name__)

    turnover_today = 0.0
    try:
        from app.backend.services.hit_ops_service import read_hit_ops

        turnover_today = float((read_hit_ops() or {}).get("turnover_today") or 0.0)
    except Exception as e:
        logger.warning("HIT cost gate: could not read turnover-to-date (%s)", type(e).__name__)

    filtered, rejects = apply_cost_gate_to_decisions(
        decisions,
        prices=prices,
        equity=equity,
        turnover_today=turnover_today,
        quotes=quotes,
    )
    return filtered, rejects, prices
