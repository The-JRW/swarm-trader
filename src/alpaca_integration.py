"""Alpaca paper trading integration for the AI hedge fund.

Fetches positions, converts to portfolio format, and executes trades.
Trade validation is delegated to risk_manager.py (V2 hard rules) — no
parallel safety rail logic lives here.

Helper functions (get_account, get_positions, etc.) are always safe to call.
execute_decisions() routes buy/short orders through risk_manager.validate_trade()
before placing.

Multi-account support: all functions accept an optional `mode` parameter.
When provided, credentials are routed to the correct account (day vs swing).
When omitted, the current trading mode (from trading_mode.json) is used.
"""

import os
import requests
from datetime import datetime, timezone

from src.accounts import get_account_for_mode, AlpacaAccount


def _now_iso_ms() -> str:
    """UTC now, ISO-8601, millisecond precision — G4 latency-observatory
    client-side clock reads (never a broker/server timestamp)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _post_order_with_timing(url: str, headers: dict, order_data: dict, timeout: int = 10):
    """POST one order, capturing G4 decision→submit→ack→fill timestamps.

    Returns ``(order_json_or_None, timing, response)``. ``timing`` always has
    ``client_submit_at`` — this module's own clock read immediately before
    the request — and ``broker_ack_at``, which is Alpaca's own
    ``created_at``/``submitted_at`` from the response (the earliest
    broker-side acknowledgement available), populated only when the POST
    succeeded. Neither is ever fabricated; a failed POST yields
    ``broker_ack_at=None``.
    """
    client_submit_at = _now_iso_ms()
    resp = requests.post(url, headers=headers, json=order_data, timeout=timeout)
    timing = {"client_submit_at": client_submit_at, "broker_ack_at": None}
    if resp.status_code in (200, 201):
        order = resp.json()
        timing["broker_ack_at"] = order.get("created_at") or order.get("submitted_at")
        return order, timing, resp
    return None, timing, resp

def _get_account(mode: str = None) -> AlpacaAccount:
    """Get the Alpaca account (credentials + base_url) for the trading mode."""
    return get_account_for_mode(mode)


def _get_headers(mode: str = None) -> dict:
    """Get API headers for the appropriate account based on trading mode."""
    return _get_account(mode).headers


def _get_base_url(mode: str = None) -> str:
    """Get Alpaca REST base URL from the account for this mode (env-driven)."""
    return _get_account(mode).base_url


# Legacy module-level headers for backward compat.
# Lazy + swing fallback so import does not break when only swing keys exist.
_HEADERS = None


def _ensure_legacy_headers() -> dict:
    global _HEADERS
    if _HEADERS is not None:
        return _HEADERS
    try:
        _HEADERS = _get_headers("day")
    except ValueError:
        try:
            _HEADERS = _get_headers("swing")
        except ValueError:
            _HEADERS = {}
    return _HEADERS


# Populate lazily on first attribute access via module getattr pattern below
try:
    _HEADERS = _ensure_legacy_headers()
except Exception:
    _HEADERS = {}


def get_alpaca_account(mode: str = None) -> dict:
    """Fetch account information from Alpaca.

    Args:
        mode: Trading mode ("swing" or "day"). Routes to correct account.
    """
    headers = _get_headers(mode)
    resp = requests.get(f"{_get_base_url(mode)}/account", headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_alpaca_positions(mode: str = None) -> list[dict]:
    """Fetch all open positions from Alpaca. Returns list of position dicts.

    Args:
        mode: Trading mode ("swing" or "day"). Routes to correct account.
    """
    headers = _get_headers(mode)
    resp = requests.get(f"{_get_base_url(mode)}/positions", headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_alpaca_portfolio_value(account: dict, positions: list[dict]) -> float:
    """Calculate total portfolio value (cash + positions)."""
    cash = float(account.get("cash", 0))
    position_value = sum(float(p.get("market_value", 0)) for p in positions)
    return cash + position_value


def convert_to_portfolio(
    alpaca_positions: list[dict],
    alpaca_account: dict,
    tickers: list[str] | None = None,
) -> dict:
    """Convert Alpaca positions + account into the portfolio format expected by the hedge fund.

    Args:
        alpaca_positions: Raw list of Alpaca position objects
        alpaca_account: Raw Alpaca account object
        tickers: Full list of tickers to analyze (including ones not currently held).
                 If None, uses only tickers from existing positions.

    Returns:
        Portfolio dict compatible with run_hedge_fund()
    """
    cash = float(alpaca_account.get("cash", 0))

    # Build lookup by symbol
    positions_by_symbol: dict[str, dict] = {p["symbol"]: p for p in alpaca_positions}

    # Determine all tickers (existing positions + any additional from args)
    all_tickers = list(positions_by_symbol.keys())
    if tickers:
        for t in tickers:
            if t not in all_tickers:
                all_tickers.append(t)

    positions = {}
    for ticker in all_tickers:
        pos = positions_by_symbol.get(ticker, {})
        qty = int(float(pos.get("qty", 0)))
        avg_price = float(pos.get("avg_entry_price", 0))

        positions[ticker] = {
            "long": qty if qty > 0 else 0,
            "short": abs(qty) if qty < 0 else 0,
            "long_cost_basis": avg_price if qty > 0 else 0.0,
            "short_cost_basis": avg_price if qty < 0 else 0.0,
            "short_margin_used": 0.0,
        }

    realized_gains = {
        ticker: {"long": 0.0, "short": 0.0}
        for ticker in all_tickers
    }

    return {
        "cash": cash,
        "margin_requirement": 0.5,
        "margin_used": 0.0,
        "positions": positions,
        "realized_gains": realized_gains,
    }


def get_daily_pnl(account: dict) -> float:
    """Calculate today's P&L as a fraction of starting equity."""
    equity = float(account.get("equity", 0))
    last_equity = float(account.get("last_equity", equity))
    if last_equity <= 0:
        return 0.0
    return (equity - last_equity) / last_equity


def _place_alpaca_order(ticker: str, action: str, qty: int, mode: str = None) -> dict:
    """Place a market order via Alpaca API."""
    headers = _get_headers(mode)
    side = "buy" if action in ("buy", "cover") else "sell"
    order_data = {
        "symbol": ticker,
        "qty": str(qty),
        "side": side,
        "type": "market",
        "time_in_force": "day",
    }
    order, timing, resp = _post_order_with_timing(
        f"{_get_base_url(mode)}/orders", headers, order_data
    )
    if order is not None:
        result = {
            "success": True,
            "order_id": order.get("id"),
            "status": order.get("status"),
            # G4 — latency observatory: client-side submit clock + broker ack
            # (Alpaca's own created_at/submitted_at). Never fabricated.
            "client_submit_at": timing["client_submit_at"],
            "broker_ack_at": timing["broker_ack_at"],
            # F5 — fill-latency timestamps when Alpaca already returned them on
            # the initial order response; left absent otherwise (never
            # fabricated). Paper market orders on liquid names often fill
            # near-instantly, so a one-shot refetch is a cheap best-effort.
            "submitted_at": order.get("submitted_at"),
            "filled_at": order.get("filled_at"),
        }
        if not result["filled_at"] and result["order_id"]:
            try:
                refreshed = get_order(result["order_id"], mode)
                if isinstance(refreshed, dict) and refreshed.get("id"):
                    result["status"] = refreshed.get("status") or result["status"]
                    result["submitted_at"] = refreshed.get("submitted_at") or result["submitted_at"]
                    result["filled_at"] = refreshed.get("filled_at") or result["filled_at"]
                    result["broker_ack_at"] = result["broker_ack_at"] or refreshed.get("created_at")
            except Exception:
                pass  # best-effort only — never fabricate a timestamp
        return result
    return {
        "success": False,
        "reason": f"Alpaca API error {resp.status_code}: {resp.text[:200]}",
        "client_submit_at": timing["client_submit_at"],
    }


def _place_bracket_order(
    ticker: str,
    action: str,
    qty: int,
    stop_price: float,
    take_profit_price: float,
    mode: str = None,
) -> dict:
    """Place a bracket order via Alpaca API (entry + stop-loss + take-profit as one atomic order).

    Args:
        ticker: Stock symbol
        action: "buy" or "sell"
        qty: Number of shares
        stop_price: Stop-loss trigger price
        take_profit_price: Take-profit limit price
        mode: Trading mode for account routing

    Returns:
        Dict with success, order_id, status, or reason on failure
    """
    headers = _get_headers(mode)
    side = "buy" if action in ("buy", "cover") else "sell"
    order_data = {
        "symbol": ticker,
        "qty": str(qty),
        "side": side,
        "type": "market",
        "time_in_force": "gtc",
        "order_class": "bracket",
        "stop_loss": {"stop_price": str(round(stop_price, 2))},
        "take_profit": {"limit_price": str(round(take_profit_price, 2))},
    }
    order, timing, resp = _post_order_with_timing(
        f"{_get_base_url(mode)}/orders", headers, order_data
    )
    if order is not None:
        return {
            "success": True,
            "order_id": order.get("id"),
            "status": order.get("status"),
            "order_class": "bracket",
            "stop_price": stop_price,
            "take_profit_price": take_profit_price,
            # G4 — latency observatory (see _post_order_with_timing).
            "client_submit_at": timing["client_submit_at"],
            "broker_ack_at": timing["broker_ack_at"],
            "submitted_at": order.get("submitted_at"),
            "filled_at": order.get("filled_at"),
        }
    return {
        "success": False,
        "reason": f"Alpaca API error {resp.status_code}: {resp.text[:200]}",
        "client_submit_at": timing["client_submit_at"],
    }


def flatten_positions(
    positions_raw: list[dict],
    dry_run: bool = True,
    tickers: list[str] | None = None,
    mode: str = None,
) -> list[dict]:
    """Market-sell all open positions (end-of-day flatten).

    Args:
        positions_raw: Raw Alpaca positions list
        dry_run: If True, show what would be sold without placing orders
        tickers: If provided, only flatten these tickers. Default: all positions.
        mode: Trading mode for account routing.

    Returns:
        List of result dicts per position flattened
    """
    headers = _get_headers(mode)
    results = []
    for pos in positions_raw:
        symbol = pos["symbol"]
        if tickers and symbol not in tickers:
            continue

        qty = int(float(pos.get("qty", 0)))
        if qty == 0:
            continue

        side = "sell" if qty > 0 else "buy"  # longs → sell, shorts → buy to cover
        abs_qty = abs(qty)

        if dry_run:
            results.append({
                "ticker": symbol,
                "action": "flatten",
                "qty": abs_qty,
                "side": side,
                "success": True,
                "dry_run": True,
            })
        else:
            order_data = {
                "symbol": symbol,
                "qty": str(abs_qty),
                "side": side,
                "type": "market",
                "time_in_force": "day",
            }
            resp = requests.post(
                f"{_get_base_url(mode)}/orders",
                headers=headers,
                json=order_data,
                timeout=10,
            )
            if resp.status_code in (200, 201):
                order = resp.json()
                results.append({
                    "ticker": symbol,
                    "action": "flatten",
                    "qty": abs_qty,
                    "side": side,
                    "success": True,
                    "order_id": order.get("id"),
                    "status": order.get("status"),
                })
            else:
                results.append({
                    "ticker": symbol,
                    "action": "flatten",
                    "qty": abs_qty,
                    "success": False,
                    "reason": f"Alpaca API error {resp.status_code}: {resp.text[:200]}",
                })

    return results


def execute_decisions(
    decisions: dict,
    positions_raw: list[dict],
    account: dict,
    dry_run: bool = True,
    mode: str = None,
    decision_at: str = None,
) -> list[dict]:
    """Execute trading decisions with V2 risk validation.

    Validation for buy/short orders is delegated to risk_manager.validate_trade().
    No internal safety rail logic — risk_manager is the single source of truth.

    Args:
        decisions: Dict of {ticker: {action, quantity, confidence, reasoning,
                   stop_price (optional), take_profit (optional), order_type (optional)}}
                   If stop_price and take_profit are both provided, a bracket order is placed.
        positions_raw: Raw Alpaca positions list
        account: Raw Alpaca account dict
        dry_run: If True, validate but don't actually place orders
        mode: Trading mode ("swing" or "day"). Resolved from env if not specified.
        decision_at: G4 (Wave G) — an ISO timestamp the caller captured when
                   this batch of decisions was finalized (post-analysis,
                   pre-execute). Attached verbatim to every placed order's
                   result so the HIT Ops strip can show decision→submit→
                   ack→fill. Optional; omitted from results entirely when
                   not provided — never fabricated here.

    Returns:
        List of result dicts with success/failure info per ticker
    """
    from src.config import resolve_mode
    if mode is None:
        mode = resolve_mode()

    # Try to load V2 risk manager
    risk_manager_available = False
    rm_portfolio_state = None
    try:
        from risk_manager import validate_trade as rm_validate_trade, get_portfolio_state as rm_get_portfolio_state
        risk_manager_available = True
        try:
            rm_portfolio_state = rm_get_portfolio_state(mode=mode)
        except Exception:
            rm_portfolio_state = None  # will be fetched per-trade by validate_trade
    except ImportError:
        pass

    positions_by_symbol: dict[str, dict] = {p["symbol"]: p for p in positions_raw}

    results = []

    for ticker, decision in decisions.items():
        action = decision.get("action", "hold")
        qty = int(decision.get("quantity", 0))
        confidence = float(decision.get("confidence", 0))
        reasoning = decision.get("reasoning", "")
        stop_price = decision.get("stop_price")
        take_profit = decision.get("take_profit")
        order_type = decision.get("order_type", "market")
        limit_price = decision.get("limit_price")
        trail_percent = decision.get("trail_percent")

        if action == "hold" or qty <= 0:
            results.append({
                "ticker": ticker,
                "action": action,
                "qty": qty,
                "success": False,
                "reason": "Hold — no trade needed",
                "skipped": True,
            })
            continue

        # V2 risk manager validation for entries
        if action in ("buy", "short") and risk_manager_available:
            pos = positions_by_symbol.get(ticker, {})
            entry_price = float(pos.get("current_price", 0)) or float(limit_price or 0)
            rm_result = rm_validate_trade(
                ticker=ticker,
                action=action,
                qty=qty,
                entry_price=entry_price,
                portfolio_state=rm_portfolio_state,
                mode=mode,
            )
            if not rm_result.approved:
                results.append({
                    "ticker": ticker,
                    "action": action,
                    "qty": qty,
                    "confidence": confidence,
                    "success": False,
                    "reason": rm_result.reason,
                    "rule": rm_result.rule,
                })
                continue

        use_bracket = stop_price is not None and take_profit is not None and order_type != "oco"

        if dry_run:
            dry_result: dict = {
                "ticker": ticker,
                "action": action,
                "qty": qty,
                "confidence": confidence,
                "success": True,
                "dry_run": True,
                "reasoning": reasoning,
                "order_type": order_type,
            }
            if use_bracket:
                dry_result["order_class"] = "bracket"
                dry_result["stop_price"] = stop_price
                dry_result["take_profit_price"] = take_profit
            elif order_type == "oco" and stop_price is not None and take_profit is not None:
                dry_result["order_class"] = "oco"
                dry_result["stop_price"] = stop_price
                dry_result["take_profit_price"] = take_profit
            elif order_type == "limit" and limit_price is not None:
                dry_result["limit_price"] = limit_price
            elif order_type == "stop" and stop_price is not None:
                dry_result["stop_price"] = stop_price
            elif order_type == "trailing_stop" and trail_percent is not None:
                dry_result["trail_percent"] = trail_percent
            results.append(dry_result)
        else:
            if use_bracket:
                order_result = _place_bracket_order(ticker, action, qty, float(stop_price), float(take_profit), mode=mode)
            elif order_type == "oco" and stop_price is not None and take_profit is not None:
                order_result = _place_oco_order(ticker, action, qty, float(stop_price), float(take_profit), mode=mode)
            elif order_type == "limit" and limit_price is not None:
                order_result = _place_limit_order(ticker, action, qty, float(limit_price), mode=mode)
            elif order_type == "stop" and stop_price is not None:
                order_result = _place_stop_order(ticker, action, qty, float(stop_price), mode=mode)
            elif order_type == "trailing_stop" and trail_percent is not None:
                order_result = _place_trailing_stop(ticker, action, qty, float(trail_percent), mode=mode)
            else:
                order_result = _place_alpaca_order(ticker, action, qty, mode=mode)
            row = {
                "ticker": ticker,
                "action": action,
                "qty": qty,
                "confidence": confidence,
                **order_result,
            }
            if decision_at:
                row["decision_at"] = decision_at
            results.append(row)

    return results



def close_position(
    symbol: str,
    *,
    percent: float | None = None,
    qty: float | None = None,
    mode: str = None,
    dry_run: bool = False,
) -> dict:
    """Close (or partially close) one paper position via market order.

    Prefer ``percent`` (1–100) or exact ``qty``. Default percent=100 (full close).
    Validates close qty is at least 1 share when the open qty is ≥ 1.

    Returns a sanitized result dict (no secrets).
    """
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {"success": False, "symbol": symbol, "reason": "symbol required"}

    positions = get_alpaca_positions(mode)
    pos = next((p for p in positions if str(p.get("symbol", "")).upper() == symbol), None)
    if not pos:
        return {"success": False, "symbol": symbol, "reason": "No open position for symbol"}

    raw_qty = float(pos.get("qty") or 0)
    if raw_qty == 0:
        return {"success": False, "symbol": symbol, "reason": "Position qty is 0"}

    side_pos = "long" if raw_qty > 0 else "short"
    abs_open = abs(raw_qty)

    if qty is not None:
        close_qty = abs(float(qty))
    else:
        pct = 100.0 if percent is None else float(percent)
        if pct <= 0 or pct > 100:
            return {"success": False, "symbol": symbol, "reason": "percent must be in (0, 100]"}
        close_qty = abs_open * (pct / 100.0)

    # Prefer whole shares when open qty is integral ≥ 1
    if abs_open >= 1 and abs(abs_open - round(abs_open)) < 1e-9:
        close_qty = int(max(1, min(round(close_qty), int(round(abs_open)))))
        if close_qty < 1:
            return {"success": False, "symbol": symbol, "reason": "Close qty must be ≥ 1 share"}
    else:
        close_qty = round(min(close_qty, abs_open), 6)
        if close_qty <= 0:
            return {"success": False, "symbol": symbol, "reason": "Close qty must be > 0"}

    order_side = "sell" if raw_qty > 0 else "buy"

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "symbol": symbol,
            "side": side_pos,
            "order_side": order_side,
            "qty": close_qty,
            "open_qty": abs_open,
            "status": "dry_run",
        }

    headers = _get_headers(mode)
    order_data = {
        "symbol": symbol,
        "qty": str(close_qty),
        "side": order_side,
        "type": "market",
        "time_in_force": "day",
    }
    resp = requests.post(
        f"{_get_base_url(mode)}/orders",
        headers=headers,
        json=order_data,
        timeout=10,
    )
    if resp.status_code in (200, 201):
        order = resp.json()
        return {
            "success": True,
            "symbol": symbol,
            "side": side_pos,
            "order_side": order_side,
            "qty": close_qty,
            "open_qty": abs_open,
            "order_id": order.get("id"),
            "status": order.get("status"),
        }
    return {
        "success": False,
        "symbol": symbol,
        "side": side_pos,
        "qty": close_qty,
        "reason": f"Alpaca API error {resp.status_code}: {resp.text[:200]}",
    }



def get_open_orders(status: str = "open", mode: str = None, limit: int = 100) -> list[dict]:
    """Fetch orders from Alpaca.

    Args:
        status: Order status filter — "open", "closed", or "all"
        mode: Trading mode for account routing.
        limit: Max orders to return (1–500; Alpaca cap).

    Returns:
        List of order dicts from Alpaca
    """
    headers = _get_headers(mode)
    lim = max(1, min(int(limit or 100), 500))
    resp = requests.get(
        f"{_get_base_url(mode)}/orders",
        headers=headers,
        params={"status": status, "limit": lim, "direction": "desc"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_order(order_id: str, mode: str = None) -> dict:
    """Fetch a single order by ID.

    Returns:
        Full order dict (status, filled_qty, etc.) or error dict
    """
    headers = _get_headers(mode)
    resp = requests.get(f"{_get_base_url(mode)}/orders/{order_id}", headers=headers, timeout=10)
    if resp.status_code == 200:
        return resp.json()
    return {"success": False, "reason": f"Alpaca API error {resp.status_code}: {resp.text[:200]}"}


def cancel_order(order_id: str, mode: str = None) -> dict:
    """Cancel a single open order by ID.

    Returns:
        {"success": True/False, "order_id": ..., "reason": ...}
    """
    headers = _get_headers(mode)
    resp = requests.delete(f"{_get_base_url(mode)}/orders/{order_id}", headers=headers, timeout=10)
    if resp.status_code in (200, 204):
        return {"success": True, "order_id": order_id}
    return {
        "success": False,
        "order_id": order_id,
        "reason": f"Alpaca API error {resp.status_code}: {resp.text[:200]}",
    }


def cancel_all_orders(mode: str = None) -> dict:
    """Cancel all open orders.

    Returns:
        {"success": True/False, "cancelled_count": int}
    """
    headers = _get_headers(mode)
    resp = requests.delete(f"{_get_base_url(mode)}/orders", headers=headers, timeout=10)
    if resp.status_code in (200, 207):
        cancelled = resp.json() if resp.text else []
        return {"success": True, "cancelled_count": len(cancelled) if isinstance(cancelled, list) else 0}
    return {
        "success": False,
        "cancelled_count": 0,
        "reason": f"Alpaca API error {resp.status_code}: {resp.text[:200]}",
    }


def _place_limit_order(
    ticker: str,
    action: str,
    qty: int,
    limit_price: float,
    time_in_force: str = "day",
    mode: str = None,
) -> dict:
    """Place a limit order via Alpaca API."""
    headers = _get_headers(mode)
    side = "buy" if action in ("buy", "cover") else "sell"
    order_data = {
        "symbol": ticker,
        "qty": str(qty),
        "side": side,
        "type": "limit",
        "time_in_force": time_in_force,
        "limit_price": str(round(limit_price, 2)),
    }
    order, timing, resp = _post_order_with_timing(f"{_get_base_url(mode)}/orders", headers, order_data)
    if order is not None:
        return {
            "success": True,
            "order_id": order.get("id"),
            "status": order.get("status"),
            "order_type": "limit",
            "limit_price": limit_price,
            "client_submit_at": timing["client_submit_at"],
            "broker_ack_at": timing["broker_ack_at"],
            "submitted_at": order.get("submitted_at"),
            "filled_at": order.get("filled_at"),
        }
    return {
        "success": False,
        "reason": f"Alpaca API error {resp.status_code}: {resp.text[:200]}",
        "client_submit_at": timing["client_submit_at"],
    }


def _place_stop_order(
    ticker: str,
    action: str,
    qty: int,
    stop_price: float,
    time_in_force: str = "gtc",
    mode: str = None,
) -> dict:
    """Place a standalone stop order via Alpaca API.

    Use this for stop-losses on EXISTING positions (not as part of a bracket entry).
    """
    headers = _get_headers(mode)
    side = "buy" if action in ("buy", "cover") else "sell"
    order_data = {
        "symbol": ticker,
        "qty": str(qty),
        "side": side,
        "type": "stop",
        "time_in_force": time_in_force,
        "stop_price": str(round(stop_price, 2)),
    }
    order, timing, resp = _post_order_with_timing(f"{_get_base_url(mode)}/orders", headers, order_data)
    if order is not None:
        return {
            "success": True,
            "order_id": order.get("id"),
            "status": order.get("status"),
            "order_type": "stop",
            "stop_price": stop_price,
            "client_submit_at": timing["client_submit_at"],
            "broker_ack_at": timing["broker_ack_at"],
            "submitted_at": order.get("submitted_at"),
            "filled_at": order.get("filled_at"),
        }
    return {
        "success": False,
        "reason": f"Alpaca API error {resp.status_code}: {resp.text[:200]}",
        "client_submit_at": timing["client_submit_at"],
    }


def _place_trailing_stop(
    ticker: str,
    action: str,
    qty: int,
    trail_percent: float,
    time_in_force: str = "gtc",
    mode: str = None,
) -> dict:
    """Place a trailing stop order via Alpaca API.

    Args:
        trail_percent: Percentage trail (e.g. 2.0 = 2% trailing stop)
        mode: Trading mode for account routing.
    """
    headers = _get_headers(mode)
    side = "buy" if action in ("buy", "cover") else "sell"
    order_data = {
        "symbol": ticker,
        "qty": str(qty),
        "side": side,
        "type": "trailing_stop",
        "time_in_force": time_in_force,
        "trail_percent": str(round(trail_percent, 2)),
    }
    order, timing, resp = _post_order_with_timing(f"{_get_base_url(mode)}/orders", headers, order_data)
    if order is not None:
        return {
            "success": True,
            "order_id": order.get("id"),
            "status": order.get("status"),
            "order_type": "trailing_stop",
            "trail_percent": trail_percent,
            "client_submit_at": timing["client_submit_at"],
            "broker_ack_at": timing["broker_ack_at"],
            "submitted_at": order.get("submitted_at"),
            "filled_at": order.get("filled_at"),
        }
    return {
        "success": False,
        "reason": f"Alpaca API error {resp.status_code}: {resp.text[:200]}",
        "client_submit_at": timing["client_submit_at"],
    }


def _place_oco_order(
    ticker: str,
    action: str,
    qty: int,
    stop_price: float,
    take_profit_price: float,
    mode: str = None,
) -> dict:
    """Place an OCO (One-Cancels-Other) order via Alpaca API.

    Use for managing exits on ALREADY HELD positions — no new entry leg.
    Different from bracket: bracket = entry + exits; OCO = just exits.
    """
    headers = _get_headers(mode)
    side = "buy" if action in ("buy", "cover") else "sell"
    order_data = {
        "symbol": ticker,
        "qty": str(qty),
        "side": side,
        "type": "limit",
        "time_in_force": "gtc",
        "order_class": "oco",
        "stop_loss": {"stop_price": str(round(stop_price, 2))},
        "take_profit": {"limit_price": str(round(take_profit_price, 2))},
    }
    order, timing, resp = _post_order_with_timing(f"{_get_base_url(mode)}/orders", headers, order_data)
    if order is not None:
        return {
            "success": True,
            "order_id": order.get("id"),
            "status": order.get("status"),
            "order_class": "oco",
            "stop_price": stop_price,
            "take_profit_price": take_profit_price,
            "client_submit_at": timing["client_submit_at"],
            "broker_ack_at": timing["broker_ack_at"],
            "submitted_at": order.get("submitted_at"),
            "filled_at": order.get("filled_at"),
        }
    return {
        "success": False,
        "reason": f"Alpaca API error {resp.status_code}: {resp.text[:200]}",
        "client_submit_at": timing["client_submit_at"],
    }


def format_positions_summary(positions_raw: list[dict], account: dict) -> str:
    """Format a human-readable summary of current positions."""
    cash = float(account.get("cash", 0))
    portfolio_value = get_alpaca_portfolio_value(account, positions_raw)
    lines = [
        f"Portfolio Value: ${portfolio_value:,.2f}",
        f"Cash: ${cash:,.2f}",
        f"Positions ({len(positions_raw)}):",
    ]
    for pos in sorted(positions_raw, key=lambda p: abs(float(p.get("market_value", 0))), reverse=True):
        symbol = pos["symbol"]
        qty = float(pos.get("qty", 0))
        market_value = float(pos.get("market_value", 0))
        unrealized_pl = float(pos.get("unrealized_pl", 0))
        pl_sign = "+" if unrealized_pl >= 0 else ""
        lines.append(
            f"  {symbol}: {qty:.0f} shares  ${market_value:,.2f}  ({pl_sign}{unrealized_pl:,.2f} P&L)"
        )
    return "\n".join(lines)


def get_alpaca_portfolio_history(
    mode: str = None,
    period: str = "1A",
    timeframe: str = "1D",
    extended_hours: bool = True,
) -> dict:
    """Fetch Alpaca account portfolio history (equity time series).

    Paper/live URL is determined by account credentials for ``mode``.
    Returns the raw Alpaca JSON (timestamp, equity, profit_loss, ...).
    Never logs secrets.
    """
    headers = _get_headers(mode)
    params = {
        "period": period,
        "timeframe": timeframe,
        "extended_hours": str(extended_hours).lower(),
    }
    resp = requests.get(
        f"{_get_base_url(mode)}/account/portfolio/history",
        headers=headers,
        params=params,
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def get_fill_activities(
    mode: str = None,
    page_size: int = 100,
    max_pages: int = 5,
    direction: str = "asc",
) -> list[dict]:
    """Fetch Alpaca account FILL activities (trade executions).

    Returns a list of activity dicts with price/qty/side/symbol/order_id/
    transaction_time. Never logs secrets. Paper/live URL follows account mode.
    """
    headers = _get_headers(mode)
    base = _get_base_url(mode)
    size = max(1, min(int(page_size or 100), 100))
    pages = max(1, min(int(max_pages or 1), 10))
    direction = "asc" if str(direction).lower() != "desc" else "desc"

    out: list[dict] = []
    page_token = None
    for _ in range(pages):
        params: dict = {
            "activity_types": "FILL",
            "page_size": size,
            "direction": direction,
        }
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(
            f"{base}/account/activities",
            headers=headers,
            params=params,
            timeout=20,
        )
        resp.raise_for_status()
        batch = resp.json() or []
        if not isinstance(batch, list) or not batch:
            break
        out.extend(a for a in batch if isinstance(a, dict))
        if len(batch) < size:
            break
        # Alpaca page_token is the last activity id
        last_id = batch[-1].get("id")
        if not last_id or last_id == page_token:
            break
        page_token = last_id
    return out
