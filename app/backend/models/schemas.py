from datetime import datetime, timedelta
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
from src.llm.models import ModelProvider
from enum import Enum
from app.backend.services.graph import extract_base_agent_key


class FlowRunStatus(str, Enum):
    IDLE = "IDLE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"


class AgentModelConfig(BaseModel):
    agent_id: str
    model_name: Optional[str] = None
    model_provider: Optional[ModelProvider] = None


class PortfolioPosition(BaseModel):
    ticker: str
    quantity: float
    trade_price: float

    @field_validator('trade_price')
    @classmethod
    def price_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError('Trade price must be positive!')
        return v


class GraphNode(BaseModel):
    id: str
    type: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    position: Optional[Dict[str, Any]] = None


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class HedgeFundResponse(BaseModel):
    decisions: dict
    analyst_signals: dict


class ErrorResponse(BaseModel):
    message: str
    error: str | None = None


# Base class for shared fields between HedgeFundRequest and BacktestRequest
class BaseHedgeFundRequest(BaseModel):
    tickers: List[str]
    graph_nodes: List[GraphNode]
    graph_edges: List[GraphEdge]
    agent_models: Optional[List[AgentModelConfig]] = None
    model_name: Optional[str] = "gpt-4.1"
    model_provider: Optional[ModelProvider] = ModelProvider.OPENAI
    margin_requirement: float = 0.0
    portfolio_positions: Optional[List[PortfolioPosition]] = None
    api_keys: Optional[Dict[str, str]] = None

    def get_agent_ids(self) -> List[str]:
        """Extract agent IDs from graph structure"""
        return [node.id for node in self.graph_nodes]

    def get_agent_model_config(self, agent_id: str) -> tuple[str, ModelProvider]:
        """Get model configuration for a specific agent"""
        if self.agent_models:
            # Extract base agent key from unique node ID for matching
            base_agent_key = extract_base_agent_key(agent_id)
            
            for config in self.agent_models:
                # Check both unique node ID and base agent key for matches
                config_base_key = extract_base_agent_key(config.agent_id)
                if config.agent_id == agent_id or config_base_key == base_agent_key:
                    return (
                        config.model_name or self.model_name,
                        config.model_provider or self.model_provider
                    )
        # Fallback to global model settings
        return self.model_name, self.model_provider


class BacktestRequest(BaseHedgeFundRequest):
    start_date: str
    end_date: str
    initial_capital: float = 100000.0


class BacktestDayResult(BaseModel):
    date: str
    portfolio_value: float
    cash: float
    decisions: Dict[str, Any]
    executed_trades: Dict[str, int]
    analyst_signals: Dict[str, Any]
    current_prices: Dict[str, float]
    long_exposure: float
    short_exposure: float
    gross_exposure: float
    net_exposure: float
    long_short_ratio: Optional[float] = None


class BacktestPerformanceMetrics(BaseModel):
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    max_drawdown_date: Optional[str] = None
    long_short_ratio: Optional[float] = None
    gross_exposure: Optional[float] = None
    net_exposure: Optional[float] = None


class BacktestResponse(BaseModel):
    results: List[BacktestDayResult]
    performance_metrics: BacktestPerformanceMetrics
    final_portfolio: Dict[str, Any]


class HedgeFundRequest(BaseHedgeFundRequest):
    end_date: Optional[str] = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    start_date: Optional[str] = None
    initial_cash: float = 100000.0

    def get_start_date(self) -> str:
        """Calculate start date if not provided"""
        if self.start_date:
            return self.start_date
        return (datetime.strptime(self.end_date, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")


# Flow-related schemas
class FlowCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    viewport: Optional[Dict[str, Any]] = None
    data: Optional[Dict[str, Any]] = None
    is_template: bool = False
    tags: Optional[List[str]] = None


class FlowUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None
    viewport: Optional[Dict[str, Any]] = None
    data: Optional[Dict[str, Any]] = None
    is_template: Optional[bool] = None
    tags: Optional[List[str]] = None


class FlowResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    viewport: Optional[Dict[str, Any]]
    data: Optional[Dict[str, Any]]
    is_template: bool
    tags: Optional[List[str]]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class FlowSummaryResponse(BaseModel):
    """Lightweight flow response without nodes/edges for listing"""
    id: int
    name: str
    description: Optional[str]
    is_template: bool
    tags: Optional[List[str]]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


# Flow Run schemas
class FlowRunCreateRequest(BaseModel):
    """Request to create a new flow run"""
    request_data: Optional[Dict[str, Any]] = None


class FlowRunUpdateRequest(BaseModel):
    """Request to update an existing flow run"""
    status: Optional[FlowRunStatus] = None
    results: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class FlowRunResponse(BaseModel):
    """Complete flow run response"""
    id: int
    flow_id: int
    status: FlowRunStatus
    run_number: int
    created_at: datetime
    updated_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    request_data: Optional[Dict[str, Any]]
    results: Optional[Dict[str, Any]]
    error_message: Optional[str]

    class Config:
        from_attributes = True


class FlowRunSummaryResponse(BaseModel):
    """Lightweight flow run response for listing"""
    id: int
    flow_id: int
    status: FlowRunStatus
    run_number: int
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]

    class Config:
        from_attributes = True


# API Key schemas
class ApiKeyCreateRequest(BaseModel):
    """Request to create or update an API key"""
    provider: str = Field(..., min_length=1, max_length=100)
    key_value: str = Field(..., min_length=1)
    description: Optional[str] = None
    is_active: bool = True


class ApiKeyUpdateRequest(BaseModel):
    """Request to update an existing API key"""
    key_value: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ApiKeyResponse(BaseModel):
    """Complete API key response"""
    id: int
    provider: str
    key_value: str
    is_active: bool
    description: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    last_used: Optional[datetime]

    class Config:
        from_attributes = True


class ApiKeySummaryResponse(BaseModel):
    """API key response without the actual key value"""
    id: int
    provider: str
    is_active: bool
    description: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    last_used: Optional[datetime]
    has_key: bool = True  # Indicates if a key is set

    class Config:
        from_attributes = True


class ApiKeyBulkUpdateRequest(BaseModel):
    """Request to update multiple API keys at once"""
    api_keys: List[ApiKeyCreateRequest]


# ---------------------------------------------------------------------------
# Strategies UI / paper trading schemas
# ---------------------------------------------------------------------------

class StrategyInfo(BaseModel):
    id: str
    name: str
    description: str
    category: str  # analyst | risk | pm
    enabled_default: bool = False


class StrategiesListResponse(BaseModel):
    strategies: List[StrategyInfo]
    server_keys: bool = False
    alpaca_trading_mode: str = "paper"


class TradingModeResponse(BaseModel):
    mode: str  # swing | day | auto
    resolved_mode: str  # swing | day (auto resolves to swing fallback for display)
    override: Optional[str] = None
    override_until: Optional[str] = None
    last_mode_used: Optional[str] = None
    last_mode_reason: Optional[str] = None
    last_updated: Optional[str] = None
    updated_by: Optional[str] = None
    alpaca_trading_mode: str = "paper"
    paper_only: bool = True


class TradingModeSetRequest(BaseModel):
    mode: str = Field(..., description="swing | day | auto")
    reason: Optional[str] = "Set from Strategies UI"
    override: bool = False
    override_hours: Optional[float] = None


class PaperRunRequest(BaseModel):
    tickers: List[str] = Field(..., min_length=1, max_length=20)
    strategy_ids: List[str] = Field(default_factory=list)
    mode: Optional[str] = Field(default=None, description="swing | day | auto")
    sync: bool = Field(default=False, description="If true, run synchronously (short path)")
    execute_trades: bool = Field(
        default=False,
        description="If true, place paper orders after analysis (PAPER ONLY; refused when live)",
    )
    instrument: str = Field(
        default="stocks",
        description="stocks | options — user instrument mode (user override wins for execution)",
    )

    @field_validator("instrument")
    @classmethod
    def normalize_instrument(cls, v: str) -> str:
        val = str(v or "stocks").strip().lower()
        if val in ("stock", "equity", "equities"):
            val = "stocks"
        if val in ("option",):
            val = "options"
        if val not in ("stocks", "options"):
            raise ValueError("instrument must be stocks or options")
        return val

    @field_validator("tickers")
    @classmethod
    def normalize_tickers(cls, v: List[str]) -> List[str]:
        cleaned = []
        for t in v:
            if not t or not str(t).strip():
                continue
            sym = str(t).strip().upper()
            if not sym.replace(".", "").isalnum():
                raise ValueError(f"Invalid ticker: {t}")
            if sym not in cleaned:
                cleaned.append(sym)
        if not cleaned:
            raise ValueError("At least one ticker is required")
        if len(cleaned) > 20:
            raise ValueError("Max 20 tickers per paper run")
        return cleaned


class PaperRunCreateResponse(BaseModel):
    run_id: str
    status: str
    message: str


class PaperRunStatusResponse(BaseModel):
    run_id: str
    status: str  # queued | running | complete | error | fail_closed
    mode: Optional[str] = None
    instrument: Optional[str] = None  # stocks | options
    tickers: Optional[List[str]] = None
    strategy_ids: Optional[List[str]] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None
    decisions: Optional[Dict[str, Any]] = None


class PortfolioGlanceResponse(BaseModel):
    available: bool
    paper: bool = True
    cash: Optional[float] = None
    equity: Optional[float] = None
    buying_power: Optional[float] = None
    positions_count: Optional[int] = None
    message: Optional[str] = None


class PortfolioOrderItem(BaseModel):
    """Sanitized paper order — no secrets or account identifiers."""
    symbol: Optional[str] = None
    side: Optional[str] = None
    qty: Optional[float] = None
    filled_qty: Optional[float] = None
    status: Optional[str] = None
    filled_avg_price: Optional[float] = None
    submitted_at: Optional[str] = None
    # Closing fills only: realized vs FIFO cost basis. Opening → null / False.
    realized_pl: Optional[float] = None
    realized_plpc: Optional[float] = None  # fraction e.g. 0.05 = 5%
    is_closing: bool = False


class PortfolioOrdersResponse(BaseModel):
    available: bool
    paper: bool = True
    orders: List[PortfolioOrderItem] = Field(default_factory=list)
    message: Optional[str] = None


class PortfolioPositionItem(BaseModel):
    """Sanitized open position for Strategies portfolio strip."""
    symbol: str
    side: str  # long | short
    qty: float
    market_value: Optional[float] = None
    unrealized_pl: Optional[float] = None
    unrealized_plpc: Optional[float] = None  # fraction e.g. 0.05 = 5%
    current_price: Optional[float] = None
    avg_entry_price: Optional[float] = None


class PortfolioPositionsResponse(BaseModel):
    available: bool
    paper: bool = True
    cash: Optional[float] = None
    equity: Optional[float] = None
    buying_power: Optional[float] = None
    positions_count: Optional[int] = None
    positions: List[PortfolioPositionItem] = Field(default_factory=list)
    message: Optional[str] = None


class PortfolioCloseRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=16)
    percent: Optional[float] = Field(
        default=100.0,
        description="Percent of position to close (1–100). Default 100 = full close.",
    )
    qty: Optional[float] = Field(
        default=None,
        description="Exact shares to close; overrides percent when set.",
    )

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        sym = str(v or "").strip().upper()
        if not sym or not sym.replace(".", "").isalnum():
            raise ValueError(f"Invalid symbol: {v}")
        return sym

    @field_validator("percent")
    @classmethod
    def validate_percent(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return 100.0
        if v <= 0 or v > 100:
            raise ValueError("percent must be in (0, 100]")
        return float(v)


class PortfolioCloseBatchItem(BaseModel):
    symbol: str
    percent: Optional[float] = 100.0
    qty: Optional[float] = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        sym = str(v or "").strip().upper()
        if not sym or not sym.replace(".", "").isalnum():
            raise ValueError(f"Invalid symbol: {v}")
        return sym


class PortfolioCloseBatchRequest(BaseModel):
    items: List[PortfolioCloseBatchItem] = Field(..., min_length=1, max_length=50)


class PortfolioCloseResult(BaseModel):
    success: bool
    symbol: str
    side: Optional[str] = None
    qty: Optional[float] = None
    status: Optional[str] = None
    order_id: Optional[str] = None
    reason: Optional[str] = None
    dry_run: Optional[bool] = None


class PortfolioCloseResponse(BaseModel):
    paper: bool = True
    results: List[PortfolioCloseResult] = Field(default_factory=list)
    message: Optional[str] = None


class PeriodPerformanceMetric(BaseModel):
    """P/L for a calendar/trading period. available=false => show em dash."""
    available: bool = False
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    start_equity: Optional[float] = None
    end_equity: Optional[float] = None
    # Only set when real SPY benchmark data exists — never invent zeros
    spy_alpha: Optional[float] = None


class PortfolioPerformanceResponse(BaseModel):
    """Paper portfolio performance strip. Never invents numbers; missing = available:false."""
    available: bool
    paper: bool = True
    equity: Optional[float] = None
    cash: Optional[float] = None
    day: PeriodPerformanceMetric = Field(default_factory=PeriodPerformanceMetric)
    week: PeriodPerformanceMetric = Field(default_factory=PeriodPerformanceMetric)
    mtd: PeriodPerformanceMetric = Field(default_factory=PeriodPerformanceMetric)
    quarter: PeriodPerformanceMetric = Field(default_factory=PeriodPerformanceMetric)
    ytd: PeriodPerformanceMetric = Field(default_factory=PeriodPerformanceMetric)
    message: Optional[str] = None
    as_of: Optional[str] = None  # ISO timestamp of successful fetch
    spy_alpha: Optional[float] = None  # omit unless real SPY data exists


