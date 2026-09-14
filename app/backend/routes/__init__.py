from fastapi import APIRouter

from app.backend.routes.hedge_fund import router as hedge_fund_router
from app.backend.routes.health import router as health_router
from app.backend.routes.storage import router as storage_router
from app.backend.routes.flows import router as flows_router
from app.backend.routes.flow_runs import router as flow_runs_router
from app.backend.routes.ollama import router as ollama_router
from app.backend.routes.language_models import router as language_models_router
from app.backend.routes.api_keys import router as api_keys_router
from app.backend.routes.strategies import router as strategies_router
from app.backend.routes.trading import router as trading_router
from app.backend.routes.runs import router as runs_router
from app.backend.routes.build_info import router as build_info_router

# Main API router
api_router = APIRouter()

# Include sub-routers
api_router.include_router(health_router, tags=["health"])
api_router.include_router(hedge_fund_router, tags=["hedge-fund"])
api_router.include_router(storage_router, tags=["storage"])
api_router.include_router(flows_router, tags=["flows"])
api_router.include_router(flow_runs_router, tags=["flow-runs"])
api_router.include_router(ollama_router, tags=["ollama"])
api_router.include_router(language_models_router, tags=["language-models"])
api_router.include_router(api_keys_router, tags=["api-keys"])
api_router.include_router(build_info_router, tags=["build"])

# Strategies UI / paper trading (also mounted under /api for direct + docs clarity)
for _prefix in ("", "/api"):
    api_router.include_router(strategies_router, prefix=_prefix, tags=["strategies"])
    api_router.include_router(trading_router, prefix=_prefix, tags=["trading"])
    api_router.include_router(runs_router, prefix=_prefix, tags=["runs"])
