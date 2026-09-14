/**
 * Strategies UI / paper trading API client.
 * Uses server env keys — never send Alpaca secrets from the browser.
 */

import { getApiBaseUrl } from '@/lib/api-base';

const API_BASE_URL = getApiBaseUrl();

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
}

export interface PaperRunStatusResponse {
  run_id: string;
  status: string;
  mode?: string;
  tickers?: string[];
  strategy_ids?: string[];
  created_at?: string;
  started_at?: string;
  completed_at?: string;
  error?: string | null;
  summary?: {
    mode?: string;
    ticker_count?: number;
    analyst_count?: number;
    action_counts?: Record<string, number>;
    decisions?: PaperRunDecision[];
    paper?: boolean;
    executed_trades?: boolean;
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
    const response = await fetch(`${API_BASE_URL}/strategies`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  getTradingMode: async (): Promise<TradingModeResponse> => {
    const response = await fetch(`${API_BASE_URL}/trading/mode`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  setTradingMode: async (mode: string): Promise<TradingModeResponse> => {
    const response = await fetch(`${API_BASE_URL}/trading/mode`, {
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
  }): Promise<PaperRunCreateResponse> => {
    const response = await fetch(`${API_BASE_URL}/runs/paper`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...params, sync: false }),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  getRun: async (runId: string): Promise<PaperRunStatusResponse> => {
    const response = await fetch(`${API_BASE_URL}/runs/${runId}`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  portfolioGlance: async (): Promise<PortfolioGlance> => {
    const response = await fetch(`${API_BASE_URL}/portfolio/glance`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },
};
