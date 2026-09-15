"""Paper analysis runs for the Strategies UI."""

from fastapi import APIRouter, HTTPException, Query

from app.backend.models.schemas import (
    ErrorResponse,
    PaperRunCreateResponse,
    PaperRunRequest,
    PaperRunStatusResponse,
    PortfolioCloseBatchRequest,
    PortfolioCloseRequest,
    PortfolioCloseResponse,
    PortfolioCloseResult,
    PortfolioGlanceResponse,
    PortfolioOrderItem,
    PortfolioOrdersResponse,
    PeriodPerformanceMetric,
    PortfolioPerformanceResponse,
    PortfolioPositionItem,
    PortfolioPositionsResponse,
)
from app.backend.services.paper_run_service import (
    alpaca_trading_mode,
    create_run_record,
    execute_paper_run,
    get_run,
    has_alpaca_keys,
    start_paper_run_async,
)
from app.backend.services.run_history_store import list_history, read_run
from app.backend.services.performance_snapshot_service import (
    compute_alpha_vs_spy,
    list_recent_snapshots,
    load_snapshots,
    read_latest_snapshot,
)
from src.config import resolve_mode

router = APIRouter()


def _paper_mode_or_refuse():
    """Return (ok, glance_mode, error_message). Refuse live trading."""
    if alpaca_trading_mode() == "live":
        return False, None, "Paper-only: ALPACA_TRADING_MODE=live refused"
    if not has_alpaca_keys():
        return False, None, "Server Alpaca keys not configured"
    glance_mode = resolve_mode()
    if glance_mode == "auto" or glance_mode not in ("swing", "day"):
        glance_mode = "swing"
    return True, glance_mode, None


def _load_account_positions(glance_mode: str):
    from src import accounts as accounts_mod
    from src.alpaca_integration import get_alpaca_account, get_alpaca_positions

    if not accounts_mod.get_all_accounts():
        accounts_mod._load_accounts()
    try:
        account = get_alpaca_account(glance_mode)
        positions = get_alpaca_positions(glance_mode)
        return account, positions, glance_mode
    except ValueError:
        accounts_mod._load_accounts()
        return get_alpaca_account("swing"), get_alpaca_positions("swing"), "swing"


def _sanitize_position(pos: dict) -> PortfolioPositionItem:
    qty = float(pos.get("qty") or 0)
    side = str(pos.get("side") or ("long" if qty >= 0 else "short")).lower()
    if side not in ("long", "short"):
        side = "long" if qty >= 0 else "short"

    def _f(key):
        v = pos.get(key)
        try:
            return float(v) if v is not None and v != "" else None
        except (TypeError, ValueError):
            return None

    return PortfolioPositionItem(
        symbol=str(pos.get("symbol") or "").upper(),
        side=side,
        qty=abs(qty),
        market_value=_f("market_value"),
        unrealized_pl=_f("unrealized_pl"),
        unrealized_plpc=_f("unrealized_plpc"),
        current_price=_f("current_price"),
        avg_entry_price=_f("avg_entry_price"),
    )


@router.post(
    "/runs/paper",
    response_model=PaperRunCreateResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def start_paper_run(body: PaperRunRequest):
    """Start a bounded paper analysis run. FAIL_CLOSED if Alpaca keys missing."""
    if not has_alpaca_keys():
        raise HTTPException(
            status_code=503,
            detail=(
                "FAIL_CLOSED: ALPACA_API_KEY and ALPACA_API_SECRET are not set on the server. "
                "Paper analysis cannot start. Configure keys in Elestio env — do not paste them in the UI."
            ),
        )

    trading = alpaca_trading_mode()
    if trading == "live":
        raise HTTPException(
            status_code=403,
            detail="FAIL_CLOSED: Strategies paper runs refuse ALPACA_TRADING_MODE=live.",
        )

    mode = (body.mode or resolve_mode() or "swing").strip().lower()
    if mode not in ("swing", "day", "auto"):
        raise HTTPException(status_code=400, detail="mode must be swing, day, or auto")

    strategy_ids = body.strategy_ids or []
    instrument = (getattr(body, "instrument", None) or "stocks").strip().lower()
    if instrument not in ("stocks", "options"):
        instrument = "stocks"

    # Options + execute: allow research run but refuse execution up-front with clear message
    if bool(body.execute_trades) and instrument == "options":
        raise HTTPException(
            status_code=400,
            detail=(
                "Options paper execute not wired yet — research-only. "
                "Uncheck Execute paper trades or switch instrument to Stocks."
            ),
        )

    run_id = create_run_record(
        body.tickers,
        strategy_ids,
        mode,
        execute_trades=bool(body.execute_trades),
        instrument=instrument,
    )

    if body.sync:
        result = execute_paper_run(run_id)
        status = result.get("status", "error")
        if status == "fail_closed":
            raise HTTPException(status_code=503, detail=result.get("error") or "FAIL_CLOSED")
        if status == "error":
            raise HTTPException(status_code=500, detail=result.get("error") or "Paper run failed")
        return PaperRunCreateResponse(
            run_id=run_id,
            status=status,
            message="Paper analysis complete",
        )

    # Async path — return immediately
    start_paper_run_async(run_id)  # daemon thread; do not block API worker
    return PaperRunCreateResponse(
        run_id=run_id,
        status="queued",
        message="Paper analysis started",
    )


@router.get(
    "/runs/history",
)
async def runs_history(limit: int = Query(default=50, ge=1, le=50)):
    """B2 — Last N durable paper-run summaries (single-replica disk under /app/data/runs/)."""
    rows = list_history(limit=limit)
    return {
        "paper_only": True,
        "limit": limit,
        "count": len(rows),
        "runs": rows,
        "note": (
            "Durable on local disk (single-replica assumption). "
            "Not shared across multi-replica deploys; prefer one backend replica."
        ),
    }


@router.get(
    "/runs/{run_id}",
    response_model=PaperRunStatusResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_paper_run(run_id: str):
    rec = get_run(run_id)
    if not rec:
        # Fall back to durable history
        durable = read_run(run_id)
        if durable:
            return PaperRunStatusResponse(
                run_id=durable.get("run_id") or run_id,
                status=durable.get("status") or "unknown",
                mode=durable.get("mode"),
                instrument=durable.get("instrument"),
                tickers=durable.get("tickers"),
                strategy_ids=durable.get("strategy_ids"),
                created_at=durable.get("created_at"),
                started_at=durable.get("started_at"),
                completed_at=durable.get("completed_at"),
                error=durable.get("error"),
                summary=durable.get("summary"),
                decisions=None,
            )
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return PaperRunStatusResponse(**rec)


@router.get(
    "/portfolio/glance",
    response_model=PortfolioGlanceResponse,
)
async def portfolio_glance():
    """Lightweight paper portfolio glance for the home strip."""
    if not has_alpaca_keys():
        return PortfolioGlanceResponse(
            available=False,
            paper=True,
            message="Server Alpaca keys not configured",
        )
    try:
        from src import accounts as accounts_mod
        from src.alpaca_integration import get_alpaca_account, get_alpaca_positions

        # Prefer resolved/swing mode so day-only missing keys do not ValueError
        glance_mode = resolve_mode()
        if glance_mode == "auto" or glance_mode not in ("swing", "day"):
            glance_mode = "swing"

        if not accounts_mod.get_all_accounts():
            accounts_mod._load_accounts()

        try:
            account = get_alpaca_account(glance_mode)
            positions = get_alpaca_positions(glance_mode)
        except ValueError:
            # Day missing → prefer swing (or vice versa via accounts fallback)
            accounts_mod._load_accounts()
            account = get_alpaca_account("swing")
            positions = get_alpaca_positions("swing")

        return PortfolioGlanceResponse(
            available=True,
            paper=alpaca_trading_mode() != "live",
            cash=float(account.get("cash") or 0),
            equity=float(account.get("equity") or account.get("portfolio_value") or 0),
            buying_power=float(account.get("buying_power") or 0),
            positions_count=len(positions or []),
        )
    except Exception as e:
        return PortfolioGlanceResponse(
            available=False,
            paper=True,
            message=f"Could not load portfolio ({type(e).__name__})",
        )


def _order_float(v):
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _load_realized_pnl_by_order(mode: str) -> dict:
    """Build order_id → realized P&L via Alpaca FILL activities (FIFO).

    Falls back to closed/all order history when activities are unavailable.
    Never invents P&L for unmatched opens.
    """
    from app.backend.services.order_pnl import (
        compute_realized_pl_by_order,
        fills_from_orders,
    )
    from src.alpaca_integration import get_fill_activities, get_open_orders

    fills = []
    try:
        fills = get_fill_activities(mode=mode, page_size=100, max_pages=5, direction="asc")
    except Exception:
        fills = []

    if not fills:
        try:
            # Wider history than the display window so cost basis can resolve
            hist = get_open_orders(status="all", mode=mode, limit=200)
            fills = fills_from_orders(hist or [])
        except Exception:
            fills = []

    if not fills:
        return {}
    return compute_realized_pl_by_order(fills)


@router.get(
    "/portfolio/orders",
    response_model=PortfolioOrdersResponse,
)
async def portfolio_orders(limit: int = Query(default=20, ge=1, le=50)):
    """Recent paper orders (sanitized) with realized P&L on closing fills.

    Opening orders return realized_pl=null / is_closing=false (UI shows —).
    Paper-only; never returns secrets.
    """
    if alpaca_trading_mode() == "live":
        return PortfolioOrdersResponse(
            available=False,
            paper=False,
            message="Orders strip is paper-only (ALPACA_TRADING_MODE=live refused)",
        )
    if not has_alpaca_keys():
        return PortfolioOrdersResponse(
            available=False,
            paper=True,
            message="Server Alpaca keys not configured",
        )
    try:
        from src import accounts as accounts_mod
        from src.alpaca_integration import get_open_orders

        glance_mode = resolve_mode()
        if glance_mode == "auto" or glance_mode not in ("swing", "day"):
            glance_mode = "swing"

        if not accounts_mod.get_all_accounts():
            accounts_mod._load_accounts()

        try:
            raw = get_open_orders(status="all", mode=glance_mode, limit=limit)
            pnl_mode = glance_mode
        except ValueError:
            accounts_mod._load_accounts()
            raw = get_open_orders(status="all", mode="swing", limit=limit)
            pnl_mode = "swing"

        try:
            pnl_by_order = _load_realized_pnl_by_order(pnl_mode)
        except Exception:
            pnl_by_order = {}

        orders: list[PortfolioOrderItem] = []
        for o in raw or []:
            if not isinstance(o, dict):
                continue
            qty_f = _order_float(o.get("qty"))
            filled_f = _order_float(o.get("filled_qty"))
            avg_f = _order_float(o.get("filled_avg_price"))
            submitted = o.get("submitted_at") or o.get("created_at")
            oid = str(o.get("id") or "")
            info = pnl_by_order.get(oid) if oid else None
            is_closing = bool(info and info.get("is_closing"))
            realized_pl = info.get("realized_pl") if is_closing else None
            realized_plpc = info.get("realized_plpc") if is_closing else None
            orders.append(
                PortfolioOrderItem(
                    symbol=o.get("symbol"),
                    side=o.get("side"),
                    qty=qty_f,
                    filled_qty=filled_f,
                    status=o.get("status"),
                    filled_avg_price=avg_f,
                    submitted_at=str(submitted) if submitted else None,
                    realized_pl=realized_pl,
                    realized_plpc=realized_plpc,
                    is_closing=is_closing,
                )
            )

        return PortfolioOrdersResponse(
            available=True,
            paper=True,
            orders=orders[:limit],
        )
    except Exception as e:
        return PortfolioOrdersResponse(
            available=False,
            paper=True,
            message=f"Could not load orders ({type(e).__name__})",
        )


@router.get(
    "/portfolio/positions",
    response_model=PortfolioPositionsResponse,
)
async def portfolio_positions():
    """Detailed paper positions for Strategies strip (sanitized)."""
    ok, glance_mode, msg = _paper_mode_or_refuse()
    if not ok:
        return PortfolioPositionsResponse(
            available=False,
            paper=alpaca_trading_mode() != "live",
            message=msg,
        )
    try:
        account, positions, _mode = _load_account_positions(glance_mode)
        items = [_sanitize_position(p) for p in (positions or []) if isinstance(p, dict)]
        return PortfolioPositionsResponse(
            available=True,
            paper=True,
            cash=float(account.get("cash") or 0),
            equity=float(account.get("equity") or account.get("portfolio_value") or 0),
            buying_power=float(account.get("buying_power") or 0),
            positions_count=len(items),
            positions=items,
        )
    except Exception as e:
        return PortfolioPositionsResponse(
            available=False,
            paper=True,
            message=f"Could not load positions ({type(e).__name__})",
        )


@router.post(
    "/portfolio/close",
    response_model=PortfolioCloseResponse,
    responses={403: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def portfolio_close(body: PortfolioCloseRequest):
    """Close (partial or full) one paper position. Refuses live."""
    if alpaca_trading_mode() == "live":
        raise HTTPException(status_code=403, detail="FAIL_CLOSED: paper-only close refused for live mode")
    ok, glance_mode, msg = _paper_mode_or_refuse()
    if not ok:
        raise HTTPException(status_code=503, detail=msg or "Unavailable")
    try:
        from src.alpaca_integration import close_position

        # Ensure accounts loaded
        _load_account_positions(glance_mode)
        result = close_position(
            body.symbol,
            percent=body.percent if body.qty is None else None,
            qty=body.qty,
            mode=glance_mode,
            dry_run=False,
        )
        return PortfolioCloseResponse(
            paper=True,
            results=[
                PortfolioCloseResult(
                    success=bool(result.get("success")),
                    symbol=str(result.get("symbol") or body.symbol),
                    side=result.get("side"),
                    qty=result.get("qty"),
                    status=result.get("status"),
                    order_id=result.get("order_id"),
                    reason=result.get("reason"),
                    dry_run=result.get("dry_run"),
                )
            ],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Close failed ({type(e).__name__})")


@router.post(
    "/portfolio/close-batch",
    response_model=PortfolioCloseResponse,
    responses={403: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def portfolio_close_batch(body: PortfolioCloseBatchRequest):
    """Close multiple paper positions (partial or full). Refuses live."""
    if alpaca_trading_mode() == "live":
        raise HTTPException(status_code=403, detail="FAIL_CLOSED: paper-only close refused for live mode")
    ok, glance_mode, msg = _paper_mode_or_refuse()
    if not ok:
        raise HTTPException(status_code=503, detail=msg or "Unavailable")
    try:
        from src.alpaca_integration import close_position

        _load_account_positions(glance_mode)
        results = []
        for item in body.items:
            result = close_position(
                item.symbol,
                percent=item.percent if item.qty is None else None,
                qty=item.qty,
                mode=glance_mode,
                dry_run=False,
            )
            results.append(
                PortfolioCloseResult(
                    success=bool(result.get("success")),
                    symbol=str(result.get("symbol") or item.symbol),
                    side=result.get("side"),
                    qty=result.get("qty"),
                    status=result.get("status"),
                    order_id=result.get("order_id"),
                    reason=result.get("reason"),
                    dry_run=result.get("dry_run"),
                )
            )
        return PortfolioCloseResponse(paper=True, results=results)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Close-batch failed ({type(e).__name__})")


@router.get(
    "/portfolio/performance",
    response_model=PortfolioPerformanceResponse,
)
async def portfolio_performance():
    """Paper portfolio performance (day / week / MTD / quarter / YTD).

    Sources:
    - Current equity/cash from Alpaca account
    - Day P/L from account equity vs last_equity when present
    - Longer periods from Alpaca /account/portfolio/history when available

    Never invents numbers — unavailable periods return available:false.
    Paper-only; sanitized (no secrets).
    """
    if alpaca_trading_mode() == "live":
        return PortfolioPerformanceResponse(
            available=False,
            paper=False,
            message="Performance dashboard is paper-only (ALPACA_TRADING_MODE=live refused)",
        )
    ok, glance_mode, msg = _paper_mode_or_refuse()
    if not ok:
        return PortfolioPerformanceResponse(
            available=False,
            paper=True,
            message=msg or "Unavailable",
        )
    try:
        from datetime import datetime, timedelta, timezone
        from src.alpaca_integration import get_alpaca_account, get_alpaca_portfolio_history

        _load_account_positions(glance_mode)
        try:
            account = get_alpaca_account(glance_mode)
        except ValueError:
            account = get_alpaca_account("swing")

        equity = float(account.get("equity") or account.get("portfolio_value") or 0)
        cash = float(account.get("cash") or 0)

        def _metric(start: float | None, end: float | None) -> PeriodPerformanceMetric:
            if start is None or end is None:
                return PeriodPerformanceMetric(available=False)
            try:
                start_f = float(start)
                end_f = float(end)
            except (TypeError, ValueError):
                return PeriodPerformanceMetric(available=False)
            if start_f <= 0:
                return PeriodPerformanceMetric(available=False)
            pnl = end_f - start_f
            pnl_pct = (pnl / start_f) * 100.0
            return PeriodPerformanceMetric(
                available=True,
                pnl=round(pnl, 2),
                pnl_pct=round(pnl_pct, 4),
                start_equity=round(start_f, 2),
                end_equity=round(end_f, 2),
            )

        # Day: prefer Alpaca last_equity (official day start)
        day = PeriodPerformanceMetric(available=False)
        last_equity_raw = account.get("last_equity")
        if last_equity_raw is not None:
            try:
                last_eq = float(last_equity_raw)
                if last_eq > 0 and equity > 0:
                    day = _metric(last_eq, equity)
            except (TypeError, ValueError):
                day = PeriodPerformanceMetric(available=False)

        week = PeriodPerformanceMetric(available=False)
        mtd = PeriodPerformanceMetric(available=False)
        quarter = PeriodPerformanceMetric(available=False)
        ytd = PeriodPerformanceMetric(available=False)

        history = None
        try:
            history = get_alpaca_portfolio_history(
                mode=glance_mode, period="1A", timeframe="1D"
            )
        except Exception:
            try:
                history = get_alpaca_portfolio_history(
                    mode="swing", period="1A", timeframe="1D"
                )
            except Exception:
                history = None

        if history and isinstance(history, dict):
            timestamps = history.get("timestamp") or []
            equities = history.get("equity") or []
            pairs: list[tuple[datetime, float]] = []
            for ts, eq in zip(timestamps, equities):
                if eq is None:
                    continue
                try:
                    eq_f = float(eq)
                except (TypeError, ValueError):
                    continue
                if eq_f <= 0:
                    continue
                try:
                    # Alpaca returns unix seconds
                    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                except (TypeError, ValueError, OSError):
                    continue
                pairs.append((dt, eq_f))

            if pairs:
                pairs.sort(key=lambda p: p[0])
                now = datetime.now(timezone.utc)
                end_eq = equity if equity > 0 else pairs[-1][1]

                def equity_at_or_before(target: datetime) -> float | None:
                    """Last equity observation on or before target; else first after."""
                    before = [eq for dt, eq in pairs if dt <= target]
                    if before:
                        return before[-1]
                    after = [eq for dt, eq in pairs if dt > target]
                    return after[0] if after else None

                # Week: ~7 calendar days ago
                week_target = now - timedelta(days=7)
                week_start_eq = equity_at_or_before(week_target)
                week = _metric(week_start_eq, end_eq)

                # MTD: first day of current month
                mtd_target = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                mtd = _metric(equity_at_or_before(mtd_target), end_eq)

                # Quarter: start of calendar quarter
                q_month = ((now.month - 1) // 3) * 3 + 1
                q_target = now.replace(month=q_month, day=1, hour=0, minute=0, second=0, microsecond=0)
                quarter = _metric(equity_at_or_before(q_target), end_eq)

                # YTD: Jan 1
                ytd_target = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
                ytd = _metric(equity_at_or_before(ytd_target), end_eq)

                # If day still missing, try history last two points
                if not day.available and len(pairs) >= 2:
                    day = _metric(pairs[-2][1], end_eq)

        # B4 — attach α vs SPY only when real snapshot data exists (never fake zeros)
        spy_alpha = None
        snapshot_as_of = None
        try:
            snaps = load_snapshots()
            spy_alpha = compute_alpha_vs_spy(snaps)
            latest = read_latest_snapshot()
            if latest:
                snapshot_as_of = latest.get("timestamp") or latest.get("date")
                # Prefer daily alpha from latest when multi-day unavailable
                if spy_alpha is None and latest.get("alpha_vs_spy_daily") is not None:
                    spy_alpha = float(latest["alpha_vs_spy_daily"])
        except Exception:
            spy_alpha = None

        as_of = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return PortfolioPerformanceResponse(
            available=True,
            paper=True,
            equity=round(equity, 2) if equity else equity,
            cash=round(cash, 2) if cash else cash,
            day=day,
            week=week,
            mtd=mtd,
            quarter=quarter,
            ytd=ytd,
            as_of=as_of,
            spy_alpha=spy_alpha,  # None unless real SPY data in snapshots
            snapshot_as_of=snapshot_as_of,
        )
    except Exception as e:
        return PortfolioPerformanceResponse(
            available=False,
            paper=True,
            message=f"Could not load performance ({type(e).__name__})",
        )


@router.get("/portfolio/performance/snapshots")
async def portfolio_performance_snapshots(limit: int = Query(default=30, ge=1, le=90)):
    """E2 — recent performance snapshots for the perf strip's Details drawer.

    Every field is a pass-through of a real snapshot write; never invents
    equity/alpha for missing days. Paper-only.
    """
    if alpaca_trading_mode() == "live":
        return {
            "available": False,
            "paper": False,
            "message": "Performance snapshots are paper-only (ALPACA_TRADING_MODE=live refused)",
            "snapshots": [],
        }
    try:
        snapshots = list_recent_snapshots(limit=limit)
        return {
            "available": True,
            "paper": True,
            "count": len(snapshots),
            "snapshots": snapshots,
        }
    except Exception as e:
        return {
            "available": False,
            "paper": True,
            "message": f"Could not load snapshots ({type(e).__name__})",
            "snapshots": [],
        }
