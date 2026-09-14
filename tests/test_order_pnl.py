"""Unit tests for FIFO realized P&L on closing orders."""

from app.backend.services.order_pnl import compute_realized_pl_by_order, fills_from_orders


def _fill(symbol, side, qty, price, order_id, ts):
    return {
        "activity_type": "FILL",
        "symbol": symbol,
        "side": side,
        "qty": str(qty),
        "price": str(price),
        "order_id": order_id,
        "transaction_time": ts,
    }


def test_long_close_profit():
    fills = [
        _fill("MSFT", "buy", 10, 100.0, "open-1", "2026-01-01T10:00:00Z"),
        _fill("MSFT", "sell", 10, 110.0, "close-1", "2026-01-02T10:00:00Z"),
    ]
    by = compute_realized_pl_by_order(fills)
    assert "open-1" not in by
    assert by["close-1"]["is_closing"] is True
    assert by["close-1"]["realized_pl"] == 100.0  # (110-100)*10
    assert abs(by["close-1"]["realized_plpc"] - 0.1) < 1e-9


def test_long_partial_and_open_no_pl():
    fills = [
        _fill("AAPL", "buy", 20, 50.0, "b1", "2026-01-01T10:00:00Z"),
        _fill("AAPL", "sell", 5, 40.0, "s1", "2026-01-02T10:00:00Z"),
        _fill("NVDA", "buy", 2, 200.0, "b2", "2026-01-03T10:00:00Z"),
    ]
    by = compute_realized_pl_by_order(fills)
    assert "b1" not in by
    assert "b2" not in by
    assert by["s1"]["realized_pl"] == -50.0  # (40-50)*5
    assert by["s1"]["is_closing"] is True


def test_short_cover_profit():
    fills = [
        _fill("TSLA", "sell", 4, 250.0, "short-1", "2026-01-01T10:00:00Z"),
        _fill("TSLA", "buy", 4, 200.0, "cover-1", "2026-01-02T10:00:00Z"),
    ]
    by = compute_realized_pl_by_order(fills)
    assert "short-1" not in by
    assert by["cover-1"]["realized_pl"] == 200.0  # (250-200)*4


def test_unknown_basis_sell_first_is_open_short():
    """Sell with no prior buys opens a short — no realized P&L until cover."""
    fills = [
        _fill("XYZ", "sell", 3, 10.0, "s0", "2026-01-01T10:00:00Z"),
    ]
    by = compute_realized_pl_by_order(fills)
    assert by == {}


def test_fifo_across_multiple_lots():
    fills = [
        _fill("MSFT", "buy", 5, 100.0, "b1", "2026-01-01T10:00:00Z"),
        _fill("MSFT", "buy", 5, 120.0, "b2", "2026-01-02T10:00:00Z"),
        _fill("MSFT", "sell", 8, 130.0, "s1", "2026-01-03T10:00:00Z"),
    ]
    by = compute_realized_pl_by_order(fills)
    # 5*(130-100) + 3*(130-120) = 150 + 30 = 180
    assert by["s1"]["realized_pl"] == 180.0


def test_fills_from_orders_fallback():
    orders = [
        {
            "id": "o1",
            "symbol": "AAPL",
            "side": "buy",
            "status": "filled",
            "filled_qty": "2",
            "filled_avg_price": "150",
            "filled_at": "2026-01-01T12:00:00Z",
        },
        {
            "id": "o2",
            "symbol": "AAPL",
            "side": "sell",
            "status": "filled",
            "filled_qty": "2",
            "filled_avg_price": "160",
            "filled_at": "2026-01-02T12:00:00Z",
        },
    ]
    fills = fills_from_orders(orders)
    by = compute_realized_pl_by_order(fills)
    assert by["o2"]["realized_pl"] == 20.0
