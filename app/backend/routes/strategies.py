"""Strategies catalog for the easy-path Strategies UI."""

from fastapi import APIRouter, HTTPException

from app.backend.models.schemas import ErrorResponse, StrategiesListResponse, StrategyInfo
from app.backend.services.paper_run_service import (
    alpaca_trading_mode,
    get_strategies_catalog,
    has_alpaca_keys,
)

router = APIRouter()


@router.get(
    "/strategies",
    response_model=StrategiesListResponse,
    responses={500: {"model": ErrorResponse}},
)
async def list_strategies():
    """List strategies/agents with category and enabled defaults."""
    try:
        raw = get_strategies_catalog()
        strategies = [StrategyInfo(**s) for s in raw]
        return StrategiesListResponse(
            strategies=strategies,
            server_keys=has_alpaca_keys(),
            alpaca_trading_mode=alpaca_trading_mode(),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list strategies: {e}")
