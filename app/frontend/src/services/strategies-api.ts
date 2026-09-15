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

/** E4 — mode auto-resolver lite: last persisted VIX/gap/calendar resolution. */
export interface ModeAutoResolution {
  active: 'override' | 'explicit' | 'auto';
  resolved_mode: string;
  reason: string;
  matched_rule?: string;
  override?: string | null;
  computed_at?: string;
  signals?: {
    vix?: number | null;
    gap_pct?: number | null;
    event_day?: boolean;
  } | null;
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
  auto_resolution?: ModeAutoResolution | null;
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
    conviction_digest?: ConvictionDigest | null;
  } | null;
  decisions?: Record<string, unknown> | null;
  conviction_digest?: ConvictionDigest | null;
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
  /** SPY alpha for this period — only present when backend has real benchmark data */
  spy_alpha?: number | null;
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
  /** ISO timestamp of last successful performance fetch (server clock) */
  as_of?: string | null;
  /** Overall SPY alpha when real data exists; omit/null otherwise — never fake zeros */
  spy_alpha?: number | null;
  /** Timestamp/date of last performance snapshot when present */
  snapshot_as_of?: string | null;
}

export interface PortfolioOrder {
  symbol?: string | null;
  side?: string | null;
  qty?: number | null;
  filled_qty?: number | null;
  status?: string | null;
  filled_avg_price?: number | null;
  submitted_at?: string | null;
  /** Closing fills only; opening orders are null (UI shows —). */
  realized_pl?: number | null;
  realized_plpc?: number | null;
  is_closing?: boolean;
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


export interface ConvictionDigest {
  consensus?: Array<{
    ticker: string;
    direction: string;
    agree?: number;
    total?: number;
    signals?: Array<{ agent: string; signal: string }>;
  }>;
  contested?: Array<{
    ticker: string;
    bullish?: number;
    bearish?: number;
    neutral?: number;
    signals?: Array<{ agent: string; signal: string }>;
  }>;
  risk_rejected?: Array<{
    ticker: string;
    reason?: string;
    remaining_position_limit?: number;
  }>;
  ticker_count?: number;
  source?: string;
}

export interface CronRecipe {
  tickers: string[];
  preset: string;
  mode: string;
  execute_trades: boolean;
  updated_at?: string | null;
  paper_only?: boolean;
  cron_execute_env_allows?: boolean;
  effective_execute_trades?: boolean;
  note?: string;
}

export interface DurableRunSummary {
  run_id: string;
  status: string;
  mode?: string;
  instrument?: string;
  tickers?: string[];
  execute_trades?: boolean;
  created_at?: string;
  started_at?: string;
  completed_at?: string;
  error?: string | null;
  action_counts?: Record<string, number> | null;
  conviction_digest?: {
    consensus_count?: number;
    contested_count?: number;
    risk_rejected_count?: number;
  } | null;
  paper?: boolean;
}

export interface ScanCandidate {
  symbol: string;
  sources: string[];
  price?: number;
  change_pct?: number;
  trade_count?: number;
  volume?: number;
}

export interface SwarmScanResult {
  paper_only?: boolean;
  timestamp?: string;
  mode?: string;
  intersect_universe?: boolean;
  intersected?: boolean;
  candidates?: ScanCandidate[];
  tickers?: string[];
  candidate_count?: number;
  auto_launch_env_allows?: boolean;
  source?: string;
}

export interface ScanHistoryEntry {
  updated_at?: string;
  timestamp?: string;
  mode?: string;
  intersect_universe?: boolean;
  candidate_count?: number;
  tickers?: string[];
  candidates_preview?: Array<{ symbol?: string; sources?: string[] }>;
  paper_only?: boolean;
}

/** D2 — read-only hard risk caps (display only; never widened from the UI). */
export interface RiskPolicySector {
  key: string;
  label: string;
  max_sector_pct?: number | null;
  max_per_stock_pct?: number | null;
  ticker_count?: number;
  tickers?: string[];
}

export interface RiskPolicyCircuitBreaker {
  rule: string;
  label: string;
  limit_pct?: number | null;
  effect?: string;
}

export interface RiskPolicy {
  paper_only: boolean;
  read_only: boolean;
  mode: string;
  mode_label?: string;
  caps: {
    max_position_pct?: number | null;
    max_sector_pct?: number | null;
    max_tactical_pct?: number | null;
    min_cash_pct?: number | null;
    stop_loss_pct?: number | null;
    trailing_stop_pct?: number | null;
    max_trades_per_day?: number | null;
    max_open_positions?: number | null;
  };
  sectors: RiskPolicySector[];
  circuit_breakers: RiskPolicyCircuitBreaker[];
  flatten: { flatten_eod: boolean; flatten_by?: string | null };
  blocklists?: {
    leveraged_etfs_allowed?: boolean;
    leveraged_etfs?: string[];
    moonshots_blocked_all_modes?: boolean;
    moonshots?: string[];
  };
  source?: string;
  note?: string;
}

/** D3 — sector-aware apply telemetry. */
export interface ApplySectorRow {
  sector: string;
  label: string;
  picked: number;
  slot_cap: number;
  max_sector_pct?: number | null;
  candidates_seen?: number;
  in_current_recipe?: number;
}

export interface ApplySkippedRow {
  symbol: string;
  sector?: string;
  sector_label?: string;
  kind: 'sector_cap' | 'slot_cap' | string;
  reason: string;
}

export interface ApplyScanResponse {
  recipe: CronRecipe;
  applied_tickers: string[];
  applied_count: number;
  cap: number;
  candidates: ScanCandidate[];
  sector_aware?: boolean;
  sector_mode?: string;
  sectors?: ApplySectorRow[];
  skipped?: ApplySkippedRow[];
  skipped_count?: number;
  sector_caps_trimmed?: boolean;
  candidate_pool_count?: number;
  notes?: string[];
  paper_only: boolean;
}

/** D5 — display-only next-recipe hints; never auto-written. */
export interface RecipeHint {
  ticker: string;
  kind: 'contested' | 'consensus' | string;
  reason: string;
  in_current_recipe?: boolean;
}

export interface RecipeHintsResponse {
  suggested_tickers: string[];
  hints: RecipeHint[];
  excluded: Array<{ ticker: string; kind: string; reason: string }>;
  cap: number;
  display_only: boolean;
  auto_write: boolean;
  requires_explicit_apply: boolean;
  source?: string;
  note?: string;
  run_id?: string | null;
  digest_updated_at?: string | null;
  current_recipe_tickers?: string[];
  paper_only?: boolean;
}

export interface AutomationOpsStatus {
  paper_only: boolean;
  monitor_dry_run_env: boolean;
  cron_execute_env_allows?: boolean;
  auto_launch_env_allows?: boolean;
  apply_cap?: number;
  updated_at?: string | null;
  recipe?: CronRecipe | null;
  last_conviction_digest?: ConvictionDigest | null;
  last_conviction_digest_meta?: {
    run_id?: string | null;
    updated_at?: string | null;
  } | null;
  last_paper_run?: {
    run_id?: string | null;
    status?: string | null;
    mode?: string | null;
    tickers?: string[] | null;
    execute_trades?: boolean | null;
    created_at?: string | null;
    message?: string | null;
    store_note?: string | null;
    conviction_digest?: ConvictionDigest | null;
  } | null;
  last_monitor?: {
    timestamp?: string | null;
    dry_run?: boolean | null;
    trading_mode?: string | null;
    positions_checked?: number | null;
    stops_triggered?: number | null;
    eod_flatten?: boolean | null;
    actions?: Array<Record<string, unknown>> | null;
    warnings?: string[] | null;
    error?: string | null;
  } | null;
  last_scan?: {
    updated_at?: string | null;
    mode?: string | null;
    intersect_universe?: boolean | null;
    candidate_count?: number | null;
    tickers?: string[] | null;
    paper_only?: boolean;
  } | null;
  recent_scans?: ScanHistoryEntry[] | null;
  paths?: Record<string, string> | null;
}

/** E1 — weekday dry-run streak + exit checklist (display/record only). */
export interface DryRunWouldFireSummary {
  timestamp?: string;
  dry_run?: boolean;
  trading_mode?: string | null;
  positions_checked?: number | null;
  would_fire_count?: number;
  would_fire?: Array<{ symbol?: string | null; stop_type?: string | null; reason?: string | null }>;
  warnings_count?: number;
}

export interface DryRunStreak {
  consecutive_weekday_count: number;
  target: number;
  streak_met: boolean;
  last_date?: string | null;
  last_weekday_label?: string | null;
  last_result?: string | null;
  summaries: DryRunWouldFireSummary[];
  ack: {
    acknowledged: boolean;
    by?: string | null;
    note?: string | null;
    at?: string | null;
  };
  ready_to_flip: boolean;
  updated_at?: string | null;
  note?: string;
}

/** E2 — one real performance snapshot row for the Details drawer. */
export interface PerformanceSnapshotRow {
  date?: string | null;
  timestamp?: string | null;
  equity?: number | null;
  cash?: number | null;
  position_count?: number | null;
  daily_pnl?: number | null;
  daily_pnl_pct?: number | null;
  spy_price?: number | null;
  spy_daily_pct?: number | null;
  alpha_vs_spy_daily?: number | null;
}

export interface PerformanceSnapshotsResponse {
  available: boolean;
  paper: boolean;
  count?: number;
  snapshots: PerformanceSnapshotRow[];
  message?: string | null;
}

/** E3 — session digest from real run fields only (no invented scores). */
export interface SessionDigest {
  run_id: string;
  timestamp?: string;
  mode?: string | null;
  instrument?: string | null;
  tickers?: string[];
  ticker_count?: number;
  analyst_count?: number | null;
  action_counts?: Record<string, number>;
  decision_count?: number;
  conviction?: {
    consensus_count?: number;
    contested_count?: number;
    risk_rejected_count?: number;
  };
  executed_trades?: boolean;
  execute_blocked_reason?: string | null;
  trade_results?: { filled: number; blocked: number; other: number; total: number };
  mode_auto_resolution_reason?: string | null;
  source?: string;
  paper?: boolean;
}

export interface SessionDigestsResponse {
  paper_only: boolean;
  limit: number;
  digests: SessionDigest[];
  note?: string;
}

/** E5 — empty-book redeploy suggestion (display-only; execute stays dual-gated). */
export interface RedeploySuggestion {
  available: boolean;
  paper: boolean;
  suggest?: boolean;
  positions_count?: number | null;
  cash?: number | null;
  threshold?: number;
  message?: string | null;
  execute_dual_gated?: boolean;
}

/** E6 — AutoResearch review queue (stub); approve/reject is display/UX only. */
export interface AutoResearchReview {
  decision: 'approved' | 'rejected';
  by?: string | null;
  note?: string | null;
  at?: string | null;
  applied?: boolean;
}

export interface AutoResearchExperiment {
  experiment_id: string;
  timestamp?: string;
  iteration?: number;
  mode?: string | null;
  hypothesis?: string | null;
  fitness_score?: number | null;
  kept?: boolean;
  error?: string | null;
  metrics?: Record<string, number | null>;
  diff_preview?: string | null;
  review?: AutoResearchReview | null;
}

export interface AutoResearchRun {
  run_id: string;
  timestamp_start?: string;
  timestamp_end?: string;
  mode?: string | null;
  iterations_requested?: number;
  iterations_completed?: number;
  stop_reason?: string | null;
  baseline_fitness?: number | null;
  best_fitness?: number | null;
  improvement?: number | null;
  keep_count?: number;
  total_experiments?: number;
  error_count?: number;
  top_hypothesis?: string | null;
}

export interface AutoResearchQueueResponse {
  paper_only: boolean;
  read_only_source: boolean;
  limit: number;
  experiments: AutoResearchExperiment[];
  recent_runs: AutoResearchRun[];
  note?: string;
  source_files?: string[];
}

/**
 * F5/G4 — Ops HIT strip latency observatory. HIT = High-frequency Intraday
 * Turnover (paper), NOT true HFT, NOT colocated µs HFT (see
 * docs/WAVE_G_LATENCY_MAX.md). decision/client_submit are this codebase's
 * own clock reads; broker_ack/filled are Alpaca's own order-response
 * timestamps. Any field can be null — never fabricated.
 */
export interface HitFillLatency {
  ticker?: string | null;
  order_id?: string | null;
  decision_at?: string | null;
  client_submit_at?: string | null;
  broker_ack_at?: string | null;
  submitted_at?: string | null;
  filled_at?: string | null;
  decision_to_submit_ms?: number | null;
  submit_to_ack_ms?: number | null;
  ack_to_fill_ms?: number | null;
  decision_to_fill_ms?: number | null;
  /** F5 (unchanged measure) — Alpaca's own submitted_at -> filled_at. */
  latency_ms?: number | null;
}

export interface HitCostGateReject {
  ticker?: string | null;
  action?: string | null;
  qty?: number | null;
  notional?: number | null;
  half_spread_bps?: number | null;
  round_trip_cost_bps?: number | null;
  cost_budget_bps?: number | null;
  quote_source?: string | null;
  /** G3 — age (ms) of the live quote backing this check; null when a
   * ticker-class default was used instead (never claimed to be "live"). */
  quote_age_ms?: number | null;
  max_quote_age_ms?: number | null;
  reason?: string | null;
  /** "cost_gate" (bps/turnover, Wave F) | "stale_quote" (G3) */
  rule?: string | null;
}

export interface HitLastPulse {
  run_id?: string | null;
  at?: string | null;
  execute_requested?: boolean;
  execute_effective?: boolean;
  trades_filled?: number;
  cost_gate_rejects?: number;
  turnover_added?: number;
  would_fire_count?: number;
}

export interface HitOps {
  date?: string;
  trades_today: number;
  turnover_today: number;
  cost_gate_rejects_today: number;
  would_fire_today?: number;
  pulses_today?: number;
  last_pulse: HitLastPulse | null;
  recent_fill_latencies: HitFillLatency[];
  recent_cost_gate_rejects: HitCostGateReject[];
  note?: string;
  /** G4 — latency-observatory honesty note (see docs/WAVE_G_LATENCY_MAX.md). */
  latency_note?: string;
  updated_at?: string | null;
  paper_only?: boolean;
  hit_execute_env_allows?: boolean;
  not_true_hft?: boolean;
}

/** F6 — HIT dry-run streak (mirrors A2/E1); record/ack only — never flips SWARM_HIT_EXECUTE. */
export interface HitDryRunSummary {
  timestamp?: string;
  mode?: string | null;
  would_fire_count?: number;
  risk_blocked_count?: number;
  cost_gate_reject_count?: number;
  executed_trades?: boolean;
}

export interface HitDryRunStreak {
  consecutive_weekday_count: number;
  target: number;
  streak_met: boolean;
  last_date?: string | null;
  last_weekday_label?: string | null;
  last_result?: string | null;
  summaries: HitDryRunSummary[];
  ack: {
    acknowledged: boolean;
    by?: string | null;
    note?: string | null;
    at?: string | null;
  };
  ready_to_flip: boolean;
  updated_at?: string | null;
  note?: string;
}

export interface HitPulseResponse {
  run_id: string;
  status: string;
  mode: string;
  tickers: string[];
  strategy_ids: string[];
  /** G2 — true (default): fast analyst preset only. false: also includes
   * apex + news_sentiment_analyst (slow path — one full LLM call per ticker
   * each). See docs/WAVE_G_LATENCY_MAX.md. */
  fast?: boolean;
  execute_trades: boolean;
  execute_requested: boolean;
  hit_execute_env_allows?: boolean;
  paper: boolean;
  paper_only: boolean;
  message?: string;
  cadence_note?: string;
  fast_path_note?: string;
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

  setTradingMode: async (
    mode: string,
    opts?: { reason?: string; override?: boolean; override_hours?: number | null }
  ): Promise<TradingModeResponse> => {
    const response = await fetch(`${getApiBaseUrl()}/trading/mode`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode,
        reason: opts?.reason || 'Set from Strategies UI',
        override: opts?.override === true,
        override_hours: opts?.override_hours ?? null,
      }),
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
  getAutomationStatus: async (): Promise<AutomationOpsStatus> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/status`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  getRecipe: async (): Promise<CronRecipe> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/recipe`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  putRecipe: async (body: {
    tickers?: string[];
    preset?: string;
    mode?: string;
    execute_trades?: boolean;
  }): Promise<CronRecipe> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/recipe`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  getRunHistory: async (limit = 50): Promise<{
    runs: DurableRunSummary[];
    count: number;
    note?: string;
  }> => {
    const response = await fetch(
      `${getApiBaseUrl()}/runs/history?limit=${encodeURIComponent(String(limit))}`
    );
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  runSwarmScan: async (body?: {
    mode?: string;
    intersect_universe?: boolean;
    max_tickers?: number;
    include_core?: boolean;
  }): Promise<SwarmScanResult> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/swarm-scan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || { intersect_universe: true }),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  getSwarmScan: async (): Promise<{
    paper_only: boolean;
    last_scan: SwarmScanResult | null;
    recent_scans: ScanHistoryEntry[];
    auto_launch_env_allows: boolean;
    apply_cap: number;
  }> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/swarm-scan`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  applyScanToRecipe: async (body?: {
    top_n?: number;
    tickers?: string[];
    sector_aware?: boolean;
    mode?: string;
  }): Promise<ApplyScanResponse> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/swarm-scan/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || { top_n: 15, sector_aware: true }),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  /** D2 — read-only risk caps. No write counterpart by design. */
  getRiskPolicy: async (mode?: string): Promise<RiskPolicy> => {
    const qs = mode ? `?mode=${encodeURIComponent(mode)}` : '';
    const response = await fetch(`${getApiBaseUrl()}/automation/risk-policy${qs}`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  /** D5 — display-only hints; applying still goes through applyScanToRecipe. */
  getRecipeHints: async (): Promise<RecipeHintsResponse> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/recipe-hints`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  launchFromScan: async (body?: {
    execute_trades?: boolean;
    confirm_execute?: boolean;
    tickers?: string[];
  }): Promise<PaperRunCreateResponse & { execute_trades?: boolean; tickers?: string[] }> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/swarm-scan/launch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || { execute_trades: false }),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  /** E1 — weekday dry-run streak + last would-fire summaries (record only). */
  getDryRunStreak: async (): Promise<DryRunStreak> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/dry-run-streak`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  /** E1 — record a James/Reviewer ack. Never flips SWARM_MONITOR_DRY_RUN. */
  ackDryRunStreak: async (by?: string, note?: string): Promise<DryRunStreak> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/dry-run-streak/ack`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ by, note }),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  clearDryRunAck: async (): Promise<DryRunStreak> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/dry-run-streak/clear-ack`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  /** E2 — recent real performance snapshots for the perf strip's Details drawer. */
  getPerformanceSnapshots: async (limit = 30): Promise<PerformanceSnapshotsResponse> => {
    const response = await fetch(
      `${getApiBaseUrl()}/portfolio/performance/snapshots?limit=${encodeURIComponent(String(limit))}`
    );
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  /** E3 — durable session digests built from real run fields only. */
  getSessionDigests: async (limit = 10): Promise<SessionDigestsResponse> => {
    const response = await fetch(
      `${getApiBaseUrl()}/automation/session-digests?limit=${encodeURIComponent(String(limit))}`
    );
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  /** E4 — cached mode auto-resolution (cheap; last computed VIX/gap/calendar reason). */
  getModeResolution: async (): Promise<ModeAutoResolution> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/mode-resolution`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  /** E4 — force a fresh resolution. Human override still wins server-side. */
  refreshModeResolution: async (): Promise<ModeAutoResolution> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/mode-resolution/refresh`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  /** E5 — empty-book redeploy suggestion; display-only, execute stays dual-gated. */
  getRedeploySuggestion: async (): Promise<RedeploySuggestion> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/redeploy-suggestion`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  /** E6 — AutoResearch review queue (read-only view over evolve.py's own logs). */
  getAutoResearchQueue: async (limit = 20): Promise<AutoResearchQueueResponse> => {
    const response = await fetch(
      `${getApiBaseUrl()}/automation/autoresearch/queue?limit=${encodeURIComponent(String(limit))}`
    );
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  /** E6 — display/UX-only approve/reject; never writes strategy.py or config. */
  reviewAutoResearchExperiment: async (
    experimentId: string,
    decision: 'approved' | 'rejected' | 'pending',
    by?: string,
    note?: string,
  ): Promise<{ experiment_id: string; review: AutoResearchReview | null }> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/autoresearch/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ experiment_id: experimentId, decision, by, note }),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  /** F5 — Ops HIT strip (trades today, turnover, cost-gate rejects, last pulse). */
  getHitOps: async (): Promise<HitOps> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/hit/ops`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  /** F3 — UI-facing HIT pulse trigger. Analysis-only unless SWARM_HIT_EXECUTE ∧ requested.
   * G2 — `fast` defaults true server-side when omitted (fast analyst preset only). */
  runHitPulse: async (body?: {
    tickers?: string[];
    execute_trades?: boolean;
    top_n?: number;
    fast?: boolean;
  }): Promise<HitPulseResponse> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/hit/pulse`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || { execute_trades: false }),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  /** F6 — weekday HIT streak + last would-fire/blocked/cost-gate summaries (record only). */
  getHitDryRunStreak: async (): Promise<HitDryRunStreak> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/hit-dry-run-streak`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  /** F6 — record a James/Reviewer ack. Never flips SWARM_HIT_EXECUTE. */
  ackHitDryRunStreak: async (by?: string, note?: string): Promise<HitDryRunStreak> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/hit-dry-run-streak/ack`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ by, note }),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },

  clearHitDryRunAck: async (): Promise<HitDryRunStreak> => {
    const response = await fetch(`${getApiBaseUrl()}/automation/hit-dry-run-streak/clear-ack`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
  },
};

