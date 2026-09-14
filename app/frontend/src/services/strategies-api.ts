/**
 * Strategies UI / paper trading API client.
 * Uses server env keys — never send Alpaca secrets from the browser.
 */

import { getApiBaseUrl } from '@/lib/api-base';

export type StrategyCategory = 'analyst' | 'risk' | 'pm';

export interface Strategy {
  id: string;
  name: string;
  description: string;
  category: StrategyCategory;
  enabled_default: boolean;
}

export interface StrategiesListResponse {
  strategies: Strategy[];
  server_keys: boolean;
  alpaca_trading_mode: string;
}

export interface TradingModeResponse {
  mode: string;
  resolved_mode: string;
  override?: string | null;
  override_until?: string | null;
  last_mode_used?: string | null;
  last_mode_reason?: string | null;
  last_updated?: string | null;
  updated_by?: string | null;
  alpaca_trading_mode: string;
  paper_only: boolean;
}

export interface PaperRunCreateResponse {
  run_id: string;
  status: string;
  message: string;
}

export interface PaperRunDecision {
  ticker: string;
  action: string;
  quantity?: number;
  confidence?: number;
  reasoning?: string;
  /** Agent-recommended instrument when model returns it */
  agent_instrument?: string | null;
  /** Effective instrument used for this run (user override) */
  instrument?: string | null;
}

export interface PaperRunStatusResponse {
  run_id: string;
  status: string;
  mode?: string;
  instrument?: string;
  tickers?: string[];
  strategy_ids?: string[];
  created_at?: string;
  started_at?: string;
  completed_at?: string;
  error?: string | null;
  summary?: {
    mode?: string;
    instrument?: string;
    ticker_count?: number;
    analyst_count?: number;
    action_counts?: Record<string, number>;
    decisions?: PaperRunDecision[];
    paper?: boolean;
    executed_trades?: boolean;
    execute_blocked_reason?: string | null;
    trade_results?: Array<Record<string, unknown>>;
  } | null;
  decisions?: Record<string, unknown> | null;
}

export interface PortfolioGlance {
  available: boolean;
  paper: boolean;
  cash?: number | null;
  equity?: number | null;
  buying_power?: number | null;
  positions_count?: number | null;
  message?: string | null;
}


export interface PeriodPerformanceMetric {
  available: boolean;
  pnl?: number | null;
  pnl_pct?: number | null;
  start_equity?: number | null;
  end_equity?: number | null;
}

export interface PortfolioPerformance {
  available: boolean;
  paper: boolean;
  equity?: number | null;
  cash?: number | null;
  day: PeriodPerformanceMetric;
  week: PeriodPerformanceMetric;
  mtd: PeriodPerformanceMetric;
  quarter: PeriodPerformanceMetric;
  ytd: PeriodPerformanceMetric;
  message?: string | null;
}

export interface PortfolioOrder {
  symbol?: string | null;
  side?: string | null;
  qty?: number | null;
  filled_qty?: number | null;
  status?: string | null;
  filled_avg_price?: number | null;
  submitted_at?: string | null;
}

export interface PortfolioOrdersResponse {
  available: boolean;
  paper: boolean;
  orders: PortfolioOrder[];
  message?: string | null;
}

export interface PortfolioPosition {
  symbol: string;
  side: string;
  qty: number;
  market_value?: number | null;
  unrealized_pl?: number | null;
  unrealized_plpc?: number | null;
  current_price?: number | null;
  avg_entry_price?: number | null;
}

export interface PortfolioPositionsResponse {
  available: boolean;
  paper: boolean;
  cash?: number | null;
  equity?: number | null;
  buying_power?: number | null;
  positions_count?: number | null;
  positions: PortfolioPosition[];
  message?: string | null;
}

export interface PortfolioCloseResult {
  success: boolean;
  symbol: string;
  side?: string | null;
  qty?: number | null;
  status?: string | null;
  order_id?: string | null;
  reason?: string | null;
  dry_run?: boolean | null;
}

export interface PortfolioCloseResponse {
  paper: boolean;
  results: PortfolioCloseResult[];
  message?: string | null;
}

async function parseError(response: Response): Promise<string> {
  try {
    const data = await response.json();
    if (typeof data?.detail === 'string') return data.detail;
    if (Array.isArray(data?.detail)) {
      return data.detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join('; ');
    }
    return data?.message || response.statusText;
  } catch {
    return response.statusText || `HTTP ${response.status}`;
  }
}

export const strategiesApi = {
  listStrategies: async (): Promise<StrategiesListResponse> => {
    const response = await fetch(`${getApiBaseUrl()}/strategies`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  getTradingMode: async (): Promise<TradingModeResponse> => {
    const response = await fetch(`${getApiBaseUrl()}/trading/mode`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  setTradingMode: async (mode: string): Promise<TradingModeResponse> => {
    const response = await fetch(`${getApiBaseUrl()}/trading/mode`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, reason: 'Set from Strategies UI' }),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  startPaperRun: async (params: {
    tickers: string[];
    strategy_ids: string[];
    mode: string;
    execute_trades?: boolean;
    instrument?: 'stocks' | 'options';
  }): Promise<PaperRunCreateResponse> => {
    const response = await fetch(`${getApiBaseUrl()}/runs/paper`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...params,
        sync: false,
        execute_trades: params.execute_trades === true,
      }),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  getRun: async (runId: string): Promise<PaperRunStatusResponse> => {
    const response = await fetch(`${getApiBaseUrl()}/runs/${runId}`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },


  portfolioPerformance: async (): Promise<PortfolioPerformance> => {
    const response = await fetch(`${getApiBaseUrl()}/portfolio/performance`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  portfolioGlance: async (): Promise<PortfolioGlance> => {
    const response = await fetch(`${getApiBaseUrl()}/portfolio/glance`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  portfolioOrders: async (limit = 20): Promise<PortfolioOrdersResponse> => {
    const response = await fetch(
      `${getApiBaseUrl()}/portfolio/orders?limit=${encodeURIComponent(String(limit))}`
    );
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  portfolioPositions: async (): Promise<PortfolioPositionsResponse> => {
    const response = await fetch(`${getApiBaseUrl()}/portfolio/positions`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  closePosition: async (params: {
    symbol: string;
    percent?: number;
    qty?: number;
  }): Promise<PortfolioCloseResponse> => {
    const response = await fetch(`${getApiBaseUrl()}/portfolio/close`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  closePositionsBatch: async (
    items: Array<{ symbol: string; percent?: number; qty?: number }>
  ): Promise<PortfolioCloseResponse> => {
    const response = await fetch(`${getApiBaseUrl()}/portfolio/close-batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },
};
