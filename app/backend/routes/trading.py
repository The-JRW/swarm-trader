"""Trading mode endpoints (swing | day | auto) — paper UI control plane."""

from fastapi import APIRouter, HTTPException

from app.backend.models.schemas import (
    ErrorResponse,
    TradingModeResponse,
    TradingModeSetRequest,
)
from app.backend.services.paper_run_service import alpaca_trading_mode
from src.config import MODES, resolve_mode, set_mode

router = APIRouter(prefix="/trading")


def _mode_payload() -> TradingModeResponse:
    import json
    from pathlib import Path

    resolved = resolve_mode()
    display_resolved = resolved if resolved != "auto" else "swing"

    mf: dict = {}
    mode_file = Path(__file__).resolve().parents[3] / "trading_mode.json"
    if mode_file.exists():
        try:
            mf = json.loads(mode_file.read_text())
        except (json.JSONDecodeError, OSError):
            mf = {}

    return TradingModeResponse(
        mode=mf.get("mode") or resolved,
        resolved_mode=display_resolved if resolved != "auto" else "swing",
        override=mf.get("override"),
        override_until=mf.get("override_until"),
        last_mode_used=mf.get("last_mode_used"),
        last_mode_reason=mf.get("last_mode_reason"),
        last_updated=mf.get("last_updated"),
        updated_by=mf.get("updated_by"),
        alpaca_trading_mode=alpaca_trading_mode(),
        paper_only=True,
    )


@router.get(
    "/mode",
    response_model=TradingModeResponse,
    responses={500: {"model": ErrorResponse}},
)
async def get_trading_mode():
    try:
        return _mode_payload()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read trading mode: {e}")


@router.post(
    "/mode",
    response_model=TradingModeResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def set_trading_mode(body: TradingModeSetRequest):
    """Set swing|day|auto. Strategies UI is paper-only (does not flip ALPACA_TRADING_MODE)."""
    mode = (body.mode or "").strip().lower()
    if mode not in MODES and mode != "auto":
        raise HTTPException(status_code=400, detail=f"Invalid mode '{mode}'. Use swing, day, or auto.")
    try:
        set_mode(
            mode=mode,
            reason=body.reason or "Set from Strategies UI",
            updated_by="strategies-ui",
            override=body.override,
            override_hours=body.override_hours,
        )
        return _mode_payload()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set trading mode: {e}")
