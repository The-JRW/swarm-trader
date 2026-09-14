"""Paper analysis runs for the Strategies UI."""

from fastapi import APIRouter, HTTPException

from app.backend.models.schemas import (
    ErrorResponse,
    PaperRunCreateResponse,
    PaperRunRequest,
    PaperRunStatusResponse,
    PortfolioGlanceResponse,
)
from app.backend.services.paper_run_service import (
    alpaca_trading_mode,
    create_run_record,
    execute_paper_run,
    get_run,
    has_alpaca_keys,
    start_paper_run_async,
)
from src.config import resolve_mode

router = APIRouter()


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
    run_id = create_run_record(
        body.tickers,
        strategy_ids,
        mode,
        execute_trades=bool(body.execute_trades),
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
    "/runs/{run_id}",
    response_model=PaperRunStatusResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_paper_run(run_id: str):
    rec = get_run(run_id)
    if not rec:
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
