"""Realize P&L for closing orders via FIFO lot matching on FILL activities.

Paper Strategies UI only. Never invents P&L when cost basis cannot be matched.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional, Tuple


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fills_from_orders(orders: List[dict]) -> List[dict]:
    """Synthesize FILL-like dicts from Alpaca order objects (fallback)."""
    fills: List[dict] = []
    for o in orders or []:
        if not isinstance(o, dict):
            continue
        status = str(o.get("status") or "").lower()
        filled_qty = _f(o.get("filled_qty"))
        price = _f(o.get("filled_avg_price"))
        side = str(o.get("side") or "").lower()
        symbol = o.get("symbol")
        order_id = o.get("id")
        if not symbol or not order_id or side not in ("buy", "sell"):
            continue
        if filled_qty is None or filled_qty <= 0 or price is None:
            continue
        if status not in ("filled", "partially_filled") and filled_qty <= 0:
            continue
        ts = o.get("filled_at") or o.get("submitted_at") or o.get("created_at") or ""
        fills.append(
            {
                "activity_type": "FILL",
                "symbol": str(symbol).upper(),
                "side": side,
                "qty": filled_qty,
                "price": price,
                "order_id": str(order_id),
                "transaction_time": str(ts),
            }
        )
    fills.sort(key=lambda x: x.get("transaction_time") or "")
    return fills


def compute_realized_pl_by_order(fills: List[dict]) -> Dict[str, dict]:
    """FIFO-match fills chronologically; return per-order realized P&L.

    Returns:
        {order_id: {
            "is_closing": True,
            "realized_pl": float,
            "realized_plpc": float|None,  # fraction vs cost basis
            "closed_qty": float,
        }}

    Only orders that closed/reduced an opposite open lot appear.
    Opening orders are omitted (caller treats missing as is_closing=False, pl=null).
    """
    long_lots: Dict[str, Deque[List[float]]] = defaultdict(deque)  # [qty, price]
    short_lots: Dict[str, Deque[List[float]]] = defaultdict(deque)

    # Sort oldest → newest for correct FIFO
    ordered = sorted(
        [f for f in (fills or []) if isinstance(f, dict)],
        key=lambda x: str(x.get("transaction_time") or x.get("id") or ""),
    )

    by_order: Dict[str, dict] = {}

    for fill in ordered:
        symbol = str(fill.get("symbol") or "").upper()
        side = str(fill.get("side") or "").lower()
        qty = _f(fill.get("qty"))
        price = _f(fill.get("price"))
        order_id = fill.get("order_id")
        if not symbol or not order_id or side not in ("buy", "sell"):
            continue
        if qty is None or qty <= 0 or price is None:
            continue

        remaining = qty
        pl = 0.0
        cost = 0.0
        closed = 0.0

        if side == "buy":
            # Cover shorts first
            lots = short_lots[symbol]
            while remaining > 1e-12 and lots:
                lot_qty, lot_price = lots[0]
                match = min(remaining, lot_qty)
                # Short: sold high (lot_price), buy cover (price)
                pl += (lot_price - price) * match
                cost += lot_price * match
                closed += match
                lot_qty -= match
                remaining -= match
                if lot_qty <= 1e-12:
                    lots.popleft()
                else:
                    lots[0][0] = lot_qty
            if remaining > 1e-12:
                long_lots[symbol].append([remaining, price])
        else:
            # Close longs first
            lots = long_lots[symbol]
            while remaining > 1e-12 and lots:
                lot_qty, lot_price = lots[0]
                match = min(remaining, lot_qty)
                # Long: buy (lot_price), sell (price)
                pl += (price - lot_price) * match
                cost += lot_price * match
                closed += match
                lot_qty -= match
                remaining -= match
                if lot_qty <= 1e-12:
                    lots.popleft()
                else:
                    lots[0][0] = lot_qty
            if remaining > 1e-12:
                short_lots[symbol].append([remaining, price])

        if closed <= 1e-12:
            continue

        oid = str(order_id)
        agg = by_order.get(oid)
        if agg is None:
            agg = {
                "is_closing": True,
                "realized_pl": 0.0,
                "cost_basis": 0.0,
                "closed_qty": 0.0,
            }
            by_order[oid] = agg
        agg["realized_pl"] += pl
        agg["cost_basis"] += cost
        agg["closed_qty"] += closed

    # Finalize % (fraction); drop internal cost_basis
    out: Dict[str, dict] = {}
    for oid, agg in by_order.items():
        cost = float(agg.get("cost_basis") or 0.0)
        pl = float(agg["realized_pl"])
        plpc = (pl / cost) if cost > 1e-12 else None
        out[oid] = {
            "is_closing": True,
            "realized_pl": round(pl, 4),
            "realized_plpc": round(plpc, 6) if plpc is not None else None,
            "closed_qty": float(agg["closed_qty"]),
        }
    return out


def enrich_orders_with_pnl(
    orders: List[dict],
    pnl_by_order: Dict[str, dict],
) -> List[Tuple[dict, Optional[float], Optional[float], bool]]:
    """Attach realized fields to raw Alpaca order dicts.

    Returns list of (order, realized_pl, realized_plpc, is_closing).
    """
    result = []
    for o in orders or []:
        if not isinstance(o, dict):
            continue
        oid = str(o.get("id") or "")
        info = pnl_by_order.get(oid) if oid else None
        if info and info.get("is_closing"):
            result.append(
                (
                    o,
                    info.get("realized_pl"),
                    info.get("realized_plpc"),
                    True,
                )
            )
        else:
            result.append((o, None, None, False))
    return result
