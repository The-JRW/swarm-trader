import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import {
  AutomationOpsStatus,
  PaperRunDecision,
  PaperRunStatusResponse,
  PortfolioOrder,
  PortfolioPosition,
  PortfolioPositionsResponse,
  Strategy,
  strategiesApi,
} from '@/services/strategies-api';
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  Lock,
  Play,
  RefreshCw,
  Shield,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';

type TradingModeChoice = 'swing' | 'day' | 'auto';
type InstrumentChoice = 'stocks' | 'options';
type PresetId = 'core' | 'value' | 'growth' | 'quant' | 'custom';

const TERMINAL = new Set(['complete', 'error', 'fail_closed']);
const CLOSE_PRESETS = [25, 50, 75, 100] as const;
const HISTORY_MAX = 10;
const ALWAYS_ON_IDS = new Set(['risk_manager', 'portfolio_manager']);

/** Exact memberships from SWARM_MASTER_PRESET_MEMBERSHIPS_t126u.md */
const PRESET_ANALYST_IDS: Record<Exclude<PresetId, 'custom'>, string[]> = {
  core: [
    'warren_buffett',
    'michael_burry',
    'cathie_wood',
    'apex',
    'autoresearch',
    'fundamentals_analyst',
    'technical_analyst',
  ],
  value: [
    'ben_graham',
    'warren_buffett',
    'charlie_munger',
    'aswath_damodaran',
    'fundamentals_analyst',
    'valuation_analyst',
  ],
  growth: [
    'cathie_wood',
    'peter_lynch',
    'phil_fisher',
    'growth_analyst',
    'technical_analyst',
  ],
  quant: [
    'technical_analyst',
    'autoresearch',
    'apex',
    'market_regime',
    'sentiment_analyst',
    'news_sentiment_analyst',
  ],
};

interface SessionRunHistoryItem {
  run_id: string;
  started_at: string;
  tickers: string[];
  mode: string;
  status: string;
  instrument?: string;
}

function fmtMoney(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
}

function fmtPct(frac?: number | null) {
  if (frac == null || Number.isNaN(frac)) return '—';
  const pct = Math.abs(frac) <= 1 ? frac * 100 : frac;
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct.toFixed(2)}%`;
}

function actionTone(action: string) {
  const a = action.toLowerCase();
  if (a === 'buy' || a === 'cover') return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40';
  if (a === 'sell' || a === 'short') return 'bg-rose-500/15 text-rose-300 border-rose-500/40';
  return 'bg-slate-500/15 text-slate-300 border-slate-500/40';
}

function ConfidenceBar({ value }: { value?: number | null }) {
  const v = value == null || Number.isNaN(Number(value)) ? null : Math.max(0, Math.min(100, Number(value)));
  if (v == null) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <div className="flex items-center gap-2 min-w-[110px]">
      <div className="h-1.5 flex-1 rounded-full bg-ramp-grey-800 overflow-hidden">
        <div
          className={cn(
            'h-full rounded-full transition-all',
            v >= 70 ? 'bg-emerald-400' : v >= 40 ? 'bg-amber-400' : 'bg-slate-400'
          )}
          style={{ width: `${v}%` }}
        />
      </div>
      <span className="text-xs tabular-nums text-muted-foreground w-8 text-right">{v.toFixed(0)}%</span>
    </div>
  );
}

function CloseSheet({
  open,
  onOpenChange,
  title,
  description,
  percent,
  onPercentChange,
  confirming,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  description: string;
  percent: number;
  onPercentChange: (n: number) => void;
  confirming: boolean;
  onConfirm: () => void;
}) {
  const set = (n: number) => onPercentChange(Math.max(1, Math.min(100, Math.round(n))));
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Close percent</div>
          <div className="flex flex-wrap gap-2">
            {CLOSE_PRESETS.map((p) => (
              <Button
                key={p}
                type="button"
                size="sm"
                variant={percent === p ? undefined : 'outline'}
                className={cn('h-8 px-3', percent === p && 'bg-blue-600 hover:bg-blue-500 text-white')}
                onClick={() => set(p)}
                disabled={confirming}
              >
                {p}%
              </Button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <Input
              type="number"
              min={1}
              max={100}
              value={percent}
              disabled={confirming}
              onChange={(e) => set(Number(e.target.value) || 1)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !confirming) onConfirm();
              }}
              className="w-24 h-8"
              aria-label="Custom close percent"
            />
            <span className="text-sm text-muted-foreground">%</span>
          </div>
        </div>
        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={confirming}>
            Cancel
          </Button>
          <Button
            className="bg-rose-600 hover:bg-rose-500 text-white"
            onClick={onConfirm}
            disabled={confirming}
          >
            {confirming ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
            Confirm close {percent}%
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function StrategiesPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [preset, setPreset] = useState<PresetId>('core');
  const [mode, setMode] = useState<TradingModeChoice>('swing');
  const [resolvedMode, setResolvedMode] = useState<string>('swing');
  const [modeReason, setModeReason] = useState<string | null>(null);
  const [instrument, setInstrument] = useState<InstrumentChoice>('stocks');
  const [executeTrades, setExecuteTrades] = useState(false);
  const [tickers, setTickers] = useState('NVDA, AAPL, MSFT');
  const [serverKeys, setServerKeys] = useState(false);
  const [alpacaMode, setAlpacaMode] = useState('paper');
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [run, setRun] = useState<PaperRunStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [runElapsedSec, setRunElapsedSec] = useState(0);
  const runStartedAtRef = useRef<number | null>(null);

  const [portfolio, setPortfolio] = useState<PortfolioPositionsResponse | null>(null);
  const [orders, setOrders] = useState<PortfolioOrder[]>([]);
  const [ordersMsg, setOrdersMsg] = useState<string | null>(null);
  const [portfolioLoading, setPortfolioLoading] = useState(false);
  const [selectedPositions, setSelectedPositions] = useState<Set<string>>(new Set());
  const [closing, setClosing] = useState(false);

  const [closeSheetOpen, setCloseSheetOpen] = useState(false);
  const [closeSheetPercent, setCloseSheetPercent] = useState(100);
  const [closeSheetSymbols, setCloseSheetSymbols] = useState<string[]>([]);

  const [runHistory, setRunHistory] = useState<SessionRunHistoryItem[]>([]);
  const [opsStatus, setOpsStatus] = useState<AutomationOpsStatus | null>(null);
  const [opsLoading, setOpsLoading] = useState(false);
  const [stickyDismissed, setStickyDismissed] = useState(false);

  const analystStrategies = useMemo(
    () => strategies.filter((s) => s.category === 'analyst'),
    [strategies]
  );
  const alwaysOnStrategies = useMemo(
    () => strategies.filter((s) => ALWAYS_ON_IDS.has(s.id)),
    [strategies]
  );

  const applyPreset = useCallback((id: Exclude<PresetId, 'custom'>, catalog: Strategy[]) => {
    const want = new Set(PRESET_ANALYST_IDS[id]);
    const available = new Set(catalog.filter((s) => s.category === 'analyst').map((s) => s.id));
    const next = new Set([...want].filter((x) => available.has(x)));
    setSelected(next);
    setPreset(id);
  }, []);

  const refreshPortfolio = useCallback(async () => {
    setPortfolioLoading(true);
    try {
      const [pos, ord] = await Promise.all([
        strategiesApi.portfolioPositions().catch(async () => {
          const g = await strategiesApi.portfolioGlance();
          return {
            available: g.available,
            paper: g.paper,
            cash: g.cash,
            equity: g.equity,
            buying_power: g.buying_power,
            positions_count: g.positions_count,
            positions: [] as PortfolioPosition[],
            message: g.message || (g.available ? 'Positions detail unavailable' : g.message),
          } as PortfolioPositionsResponse;
        }),
        strategiesApi.portfolioOrders(20).catch(() => null),
      ]);
      setPortfolio(pos);
      if (ord?.available) {
        setOrders((ord.orders || []).slice(0, 10));
        setOrdersMsg(null);
      } else {
        setOrders([]);
        setOrdersMsg(ord?.message || 'Recent orders unavailable');
      }
      setSelectedPositions((prev) => {
        const syms = new Set((pos.positions || []).map((p) => p.symbol));
        return new Set([...prev].filter((s) => syms.has(s)));
      });
    } catch (e: any) {
      setPortfolio({
        available: false,
        paper: true,
        positions: [],
        message: e?.message || 'Could not load portfolio',
      });
      setOrders([]);
      setOrdersMsg(e?.message || 'Could not load orders');
    } finally {
      setPortfolioLoading(false);
    }
  }, []);


  const refreshOps = useCallback(async () => {
    setOpsLoading(true);
    try {
      const s = await strategiesApi.getAutomationStatus();
      setOpsStatus(s);
    } catch {
      setOpsStatus(null);
    } finally {
      setOpsLoading(false);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, trading] = await Promise.all([
        strategiesApi.listStrategies(),
        strategiesApi.getTradingMode(),
      ]);
      setStrategies(list.strategies);
      setServerKeys(list.server_keys);
      setAlpacaMode(list.alpaca_trading_mode || trading.alpaca_trading_mode || 'paper');
      const m = (trading.mode || 'swing').toLowerCase();
      if (m === 'swing' || m === 'day' || m === 'auto') setMode(m);
      const resolved = (trading.resolved_mode || 'swing').toLowerCase();
      setResolvedMode(resolved === 'day' ? 'day' : 'swing');
      setModeReason(
        trading.last_mode_reason ||
          (m === 'auto' ? 'UI deterministic fallback — agent VIX pick not wired' : null)
      );
      applyPreset('core', list.strategies);
    } catch (e: any) {
      setError(e?.message || 'Failed to load strategies');
    } finally {
      setLoading(false);
    }
  }, [applyPreset]);

  useEffect(() => {
    load();
    refreshPortfolio();
    refreshOps();
  }, [load, refreshPortfolio, refreshOps]);

  useEffect(() => {
    const active = run && !TERMINAL.has(run.status);
    if (!active) {
      runStartedAtRef.current = null;
      return;
    }
    if (!runStartedAtRef.current) {
      runStartedAtRef.current = Date.now();
      setRunElapsedSec(0);
    }
    const id = setInterval(() => {
      if (runStartedAtRef.current) {
        setRunElapsedSec(Math.floor((Date.now() - runStartedAtRef.current) / 1000));
      }
    }, 1000);
    return () => clearInterval(id);
  }, [run?.run_id, run?.status]);

  useEffect(() => {
    if (!run?.run_id || TERMINAL.has(run.status)) return;
    const id = setInterval(async () => {
      try {
        const next = await strategiesApi.getRun(run.run_id);
        setRun(next);
        if (TERMINAL.has(next.status)) {
          setRunning(false);
          setRunHistory((prev) => {
            const item: SessionRunHistoryItem = {
              run_id: next.run_id,
              started_at: next.started_at || next.created_at || new Date().toISOString(),
              tickers: next.tickers || [],
              mode: next.mode || mode,
              status: next.status,
              instrument: next.instrument || instrument,
            };
            const without = prev.filter((h) => h.run_id !== next.run_id);
            return [item, ...without].slice(0, HISTORY_MAX);
          });
          if (next.status === 'complete') {
            const executed = next.summary?.executed_trades;
            toast.success(executed ? 'Paper run complete — trades submitted' : 'Paper analysis complete');
            if (next.summary?.execute_blocked_reason) {
              toast.message(next.summary.execute_blocked_reason);
            }
            void refreshPortfolio();
          }
          if (next.status === 'error' || next.status === 'fail_closed') {
            toast.error(next.error || 'Paper run failed');
          }
        }
      } catch (e: any) {
        setRunning(false);
        setError(e?.message || 'Failed to poll run');
      }
    }, 2000);
    return () => clearInterval(id);
  }, [run?.run_id, run?.status, refreshPortfolio, mode, instrument]);

  const toggle = (id: string) => {
    if (ALWAYS_ON_IDS.has(id)) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setPreset('custom');
  };

  const onPresetClick = (id: PresetId) => {
    if (id === 'custom') {
      setPreset('custom');
      return;
    }
    applyPreset(id, strategies);
  };

  const onModeChange = async (next: TradingModeChoice) => {
    setMode(next);
    try {
      const trading = await strategiesApi.setTradingMode(next);
      const resolved = (trading.resolved_mode || 'swing').toLowerCase();
      setResolvedMode(resolved === 'day' ? 'day' : 'swing');
      setModeReason(
        trading.last_mode_reason ||
          (next === 'auto' ? 'UI deterministic fallback — agent VIX pick not wired' : null)
      );
      toast.success(`Mode set to ${next}`);
    } catch (e: any) {
      toast.error(e?.message || 'Failed to set mode');
    }
  };

  const onInstrumentChange = (next: InstrumentChoice) => {
    setInstrument(next);
    if (next === 'options' && executeTrades) {
      setExecuteTrades(false);
      toast.message('Options is research-only — Execute paper trades turned off');
    }
  };

  const onRun = async () => {
    setError(null);
    const parsed = tickers
      .split(/[\s,]+/)
      .map((t) => t.trim().toUpperCase())
      .filter(Boolean);
    if (parsed.length === 0) {
      toast.error('Enter at least one ticker');
      return;
    }
    if (selected.size === 0) {
      toast.error('Select at least one strategy');
      return;
    }
    if (!serverKeys) {
      toast.error('Server Alpaca keys missing — FAIL_CLOSED');
      setError(
        'FAIL_CLOSED: server Alpaca keys are missing. Paper runs cannot start until ALPACA_API_KEY / ALPACA_API_SECRET are set in the deployment environment.'
      );
      return;
    }
    if (executeTrades && instrument === 'options') {
      toast.error('Options paper execute not wired yet — research-only');
      return;
    }

    setRunning(true);
    setStickyDismissed(false);
    setRun(null);
    setExpanded(new Set());
    runStartedAtRef.current = Date.now();
    setRunElapsedSec(0);
    try {
      const created = await strategiesApi.startPaperRun({
        tickers: parsed,
        strategy_ids: Array.from(selected),
        mode,
        execute_trades: executeTrades,
        instrument,
      });
      const status = await strategiesApi.getRun(created.run_id);
      setRun(status);
      setRunHistory((prev) => {
        const item: SessionRunHistoryItem = {
          run_id: created.run_id,
          started_at: status.started_at || status.created_at || new Date().toISOString(),
          tickers: parsed,
          mode,
          status: status.status,
          instrument,
        };
        const without = prev.filter((h) => h.run_id !== created.run_id);
        return [item, ...without].slice(0, HISTORY_MAX);
      });
      toast(executeTrades ? 'Paper run + execute started' : 'Paper analysis started', {
        description: created.run_id.slice(0, 8),
      });
    } catch (e: any) {
      setRunning(false);
      const msg = e?.message || 'Failed to start paper run';
      setError(msg);
      toast.error(msg);
    }
  };

  const openCloseSheet = (symbols: string[]) => {
    if (symbols.length === 0) {
      toast.error('Select at least one position');
      return;
    }
    setCloseSheetSymbols(symbols);
    setCloseSheetPercent(100);
    setCloseSheetOpen(true);
  };

  const confirmClose = async () => {
    if (closeSheetSymbols.length === 0) return;
    setClosing(true);
    try {
      if (closeSheetSymbols.length === 1) {
        const symbol = closeSheetSymbols[0];
        const res = await strategiesApi.closePosition({ symbol, percent: closeSheetPercent });
        const r = res.results?.[0];
        if (r?.success) toast.success(`Closed ${closeSheetPercent}% of ${symbol}`);
        else toast.error(r?.reason || `Failed to close ${symbol}`);
      } else {
        const items = closeSheetSymbols.map((symbol) => ({
          symbol,
          percent: closeSheetPercent,
        }));
        const res = await strategiesApi.closePositionsBatch(items);
        const ok = (res.results || []).filter((r) => r.success).length;
        const fail = (res.results || []).length - ok;
        if (ok) toast.success(`Closed ${ok} position(s)`);
        if (fail) toast.error(`${fail} close(s) failed`);
        setSelectedPositions(new Set());
      }
      setCloseSheetOpen(false);
      await refreshPortfolio();
    } catch (e: any) {
      toast.error(e?.message || 'Close failed');
    } finally {
      setClosing(false);
    }
  };

  const viewHistoryRun = async (item: SessionRunHistoryItem) => {
    try {
      const status = await strategiesApi.getRun(item.run_id);
      setRun(status);
      setStickyDismissed(TERMINAL.has(status.status));
      toast.message(`Showing run ${item.run_id.slice(0, 8)}`);
    } catch (e: any) {
      toast.error(e?.message || 'Run no longer available in this session');
    }
  };

  const decisions: PaperRunDecision[] = run?.summary?.decisions || [];
  const actionCounts = run?.summary?.action_counts || {};
  const tradeResults = run?.summary?.trade_results || [];
  const positions = portfolio?.positions || [];

  const runButtonLabel =
    executeTrades && instrument === 'stocks'
      ? 'Run & execute paper trades'
      : 'Run paper analysis';

  const runActive = Boolean(run && !TERMINAL.has(run.status));
  const showSticky = Boolean(run && (runActive || (!stickyDismissed && TERMINAL.has(run.status))));

  const autoLabel = mode === 'auto' ? `Auto (resolved: ${resolvedMode})` : mode;
  const autoReasonCopy =
    mode === 'auto'
      ? modeReason || 'UI deterministic fallback — agent VIX pick not wired'
      : null;

  return (
    <TooltipProvider delayDuration={200}>
      <div className="h-full w-full overflow-auto bg-panel pb-16">
        <div className="max-w-5xl mx-auto p-4 sm:p-6 space-y-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-primary">Strategies</h1>
              <p className="text-sm text-muted-foreground mt-1">
                Paper swarm research — pick mode, instrument, analysts, and tickers. No CLI required.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="success">Paper trading — no real money</Badge>
              {serverKeys ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Badge variant="secondary" className="gap-1 cursor-help">
                      <Shield className="h-3 w-3" />
                      using server keys
                    </Badge>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs text-xs">
                    Trading keys (Alpaca) come from the server environment only. Settings API keys are for
                    LLM / data providers — not trading secrets.
                  </TooltipContent>
                </Tooltip>
              ) : (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Badge variant="warning" className="cursor-help">
                      server keys missing
                    </Badge>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs text-xs">
                    FAIL_CLOSED: set ALPACA_API_KEY and ALPACA_API_SECRET on the server. Paper runs will not
                    start without them. Do not paste trading secrets in Settings.
                  </TooltipContent>
                </Tooltip>
              )}
              <Badge variant="outline">Alpaca: {alpacaMode}</Badge>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  load();
                  refreshPortfolio();
                }}
                disabled={loading || portfolioLoading}
              >
                <RefreshCw className={cn('h-4 w-4', (loading || portfolioLoading) && 'animate-spin')} />
              </Button>
            </div>
          </div>

          {!serverKeys && (
            <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
              <strong className="font-medium">FAIL_CLOSED — server Alpaca keys missing.</strong>{' '}
              Paper analysis cannot start until trading keys are present in the deployment environment.
              Settings keys are LLM/data only; they do not unlock trading.
            </div>
          )}

          {error && (
            <div className="rounded-md border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
              {error}
            </div>
          )}

          <Card className="border-blue-500/20">
            <CardHeader className="pb-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <CardTitle className="text-base">Portfolio</CardTitle>
                  <CardDescription>Paper account glance, open positions, recent fills</CardDescription>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => refreshPortfolio()}
                  disabled={portfolioLoading || closing}
                >
                  <RefreshCw className={cn('h-3.5 w-3.5 mr-1.5', portfolioLoading && 'animate-spin')} />
                  Refresh
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {!portfolio?.available ? (
                <div className="space-y-2">
                  <p className="text-sm text-muted-foreground">
                    {portfolio?.message ||
                      'Portfolio unavailable — check server Alpaca keys and paper mode, then retry.'}
                  </p>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => refreshPortfolio()}
                    disabled={portfolioLoading}
                  >
                    Retry portfolio load
                  </Button>
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    {[
                      { label: 'Cash', value: fmtMoney(portfolio.cash) },
                      { label: 'Equity', value: fmtMoney(portfolio.equity) },
                      { label: 'Buying power', value: fmtMoney(portfolio.buying_power) },
                      { label: 'Positions', value: String(portfolio.positions_count ?? positions.length) },
                    ].map((k) => (
                      <div key={k.label} className="rounded-lg border bg-ramp-grey-800/30 px-3 py-2">
                        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{k.label}</div>
                        <div className="text-sm font-semibold tabular-nums mt-0.5">{k.value}</div>
                      </div>
                    ))}
                  </div>

                  {positions.length > 0 ? (
                    <div className="space-y-3">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          Open positions
                        </div>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={closing || selectedPositions.size === 0}
                          onClick={() => openCloseSheet([...selectedPositions])}
                          className="border-rose-500/40 text-rose-200 hover:bg-rose-500/10"
                        >
                          Close selected… ({selectedPositions.size})
                        </Button>
                      </div>

                      <div className="overflow-x-auto rounded-md border">
                        <table className="w-full text-sm">
                          <thead className="bg-ramp-grey-800/50 text-left text-xs text-muted-foreground">
                            <tr>
                              <th className="p-2 w-8">
                                <Checkbox
                                  checked={
                                    positions.length > 0 && selectedPositions.size === positions.length
                                  }
                                  onCheckedChange={(c) => {
                                    if (c) setSelectedPositions(new Set(positions.map((p) => p.symbol)));
                                    else setSelectedPositions(new Set());
                                  }}
                                />
                              </th>
                              <th className="p-2">Symbol</th>
                              <th className="p-2">Side</th>
                              <th className="p-2">Qty</th>
                              <th className="p-2">Mkt value</th>
                              <th className="p-2">P/L $</th>
                              <th className="p-2">P/L %</th>
                              <th className="p-2" />
                            </tr>
                          </thead>
                          <tbody>
                            {positions.map((p) => {
                              const pl = p.unrealized_pl;
                              const up = pl != null && pl >= 0;
                              return (
                                <tr key={p.symbol} className="border-t border-ramp-grey-800 align-middle">
                                  <td className="p-2">
                                    <Checkbox
                                      checked={selectedPositions.has(p.symbol)}
                                      onCheckedChange={() => {
                                        setSelectedPositions((prev) => {
                                          const next = new Set(prev);
                                          if (next.has(p.symbol)) next.delete(p.symbol);
                                          else next.add(p.symbol);
                                          return next;
                                        });
                                      }}
                                    />
                                  </td>
                                  <td className="p-2 font-medium">{p.symbol}</td>
                                  <td className="p-2 capitalize">{p.side}</td>
                                  <td className="p-2 tabular-nums">{p.qty}</td>
                                  <td className="p-2 tabular-nums">{fmtMoney(p.market_value)}</td>
                                  <td
                                    className={cn(
                                      'p-2 tabular-nums',
                                      pl == null ? '' : up ? 'text-emerald-300' : 'text-rose-300'
                                    )}
                                  >
                                    <span className="inline-flex items-center gap-1">
                                      {pl != null ? (
                                        up ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />
                                      ) : null}
                                      {fmtMoney(pl)}
                                    </span>
                                  </td>
                                  <td
                                    className={cn(
                                      'p-2 tabular-nums',
                                      p.unrealized_plpc == null
                                        ? ''
                                        : (p.unrealized_plpc ?? 0) >= 0
                                          ? 'text-emerald-300'
                                          : 'text-rose-300'
                                    )}
                                  >
                                    {fmtPct(p.unrealized_plpc)}
                                  </td>
                                  <td className="p-2">
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      className="h-7 text-xs border-rose-500/40 text-rose-200"
                                      disabled={closing}
                                      onClick={() => openCloseSheet([p.symbol])}
                                    >
                                      Close…
                                    </Button>
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">No open positions</p>
                  )}

                  <div>
                    <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">
                      Recent orders
                    </div>
                    {orders.length === 0 ? (
                      <p className="text-sm text-muted-foreground">{ordersMsg || 'No recent orders'}</p>
                    ) : (
                      <div className="overflow-x-auto rounded-md border">
                        <table className="w-full text-sm">
                          <thead className="bg-ramp-grey-800/50 text-left text-xs text-muted-foreground">
                            <tr>
                              <th className="p-2">Symbol</th>
                              <th className="p-2">Side</th>
                              <th className="p-2">Qty</th>
                              <th className="p-2">Filled</th>
                              <th className="p-2">Avg</th>
                              <th className="p-2">P&L</th>
                              <th className="p-2">Status</th>
                              <th className="p-2">Submitted</th>
                            </tr>
                          </thead>
                          <tbody>
                            {orders.map((o, i) => {
                              const showPl = Boolean(o.is_closing) && o.realized_pl != null;
                              const pl = o.realized_pl;
                              const up = pl != null && pl >= 0;
                              return (
                                <tr
                                  key={`${o.symbol}-${o.submitted_at}-${i}`}
                                  className="border-t border-ramp-grey-800"
                                >
                                  <td className="p-2 font-medium">{o.symbol || '—'}</td>
                                  <td className="p-2 uppercase text-xs">{o.side || '—'}</td>
                                  <td className="p-2 tabular-nums">{o.qty ?? '—'}</td>
                                  <td className="p-2 tabular-nums">{o.filled_qty ?? '—'}</td>
                                  <td className="p-2 tabular-nums">{fmtMoney(o.filled_avg_price)}</td>
                                  <td
                                    className={cn(
                                      'p-2 tabular-nums whitespace-nowrap',
                                      !showPl
                                        ? 'text-muted-foreground'
                                        : up
                                          ? 'text-emerald-300'
                                          : 'text-rose-300'
                                    )}
                                  >
                                    {showPl ? (
                                      <span className="inline-flex items-center gap-1">
                                        {up ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                                        {fmtMoney(pl)}
                                        {o.realized_plpc != null ? (
                                          <span className="text-[10px] opacity-80">({fmtPct(o.realized_plpc)})</span>
                                        ) : null}
                                      </span>
                                    ) : (
                                      '—'
                                    )}
                                  </td>
                                  <td className="p-2">
                                    <Badge variant="outline" className="text-[10px]">
                                      {o.status || '—'}
                                    </Badge>
                                  </td>
                                  <td className="p-2 text-xs text-muted-foreground whitespace-nowrap">
                                    {o.submitted_at
                                      ? new Date(o.submitted_at).toLocaleString(undefined, {
                                          month: 'short',
                                          day: 'numeric',
                                          hour: '2-digit',
                                          minute: '2-digit',
                                        })
                                      : '—'}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          <div className="grid lg:grid-cols-2 gap-5">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Trading mode</CardTitle>
                <CardDescription>
                  Swing (multi-day) or day (intraday). Auto uses deterministic UI resolution — not live
                  VIX/agent pick.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="flex flex-wrap gap-2">
                  {(['swing', 'day', 'auto'] as TradingModeChoice[]).map((m) => (
                    <Button
                      key={m}
                      variant={mode === m ? undefined : 'outline'}
                      size="sm"
                      onClick={() => onModeChange(m)}
                      className={cn(mode === m && 'bg-blue-600 hover:bg-blue-500 text-white')}
                    >
                      {m === 'auto' ? autoLabel : m}
                    </Button>
                  ))}
                </div>
                {mode === 'auto' && (
                  <p className="text-xs text-muted-foreground">
                    Resolved mode: <span className="text-primary font-medium">{resolvedMode}</span>
                    {' · '}
                    {autoReasonCopy}
                  </p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Instrument</CardTitle>
                <CardDescription>
                  User override wins for execution. Options is research-only for now.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="inline-flex rounded-lg border p-0.5 bg-ramp-grey-800/30">
                  {(['stocks', 'options'] as InstrumentChoice[]).map((inst) => (
                    <Button
                      key={inst}
                      size="sm"
                      variant="ghost"
                      onClick={() => onInstrumentChange(inst)}
                      className={cn(
                        'rounded-md capitalize min-w-[96px]',
                        instrument === inst && 'bg-blue-600 hover:bg-blue-500 text-white'
                      )}
                    >
                      {inst}
                    </Button>
                  ))}
                </div>
                {instrument === 'options' && (
                  <p className="text-xs text-amber-200/90">
                    Options paper execute is not wired yet — analysis runs are research-only. Execute toggle
                    stays off.
                  </p>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader className="pb-3">
              <div>
                <CardTitle className="text-base">Strategies</CardTitle>
                <CardDescription>
                  Presets set optional analysts. Risk Manager + Portfolio Manager are always included.
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap gap-2" role="group" aria-label="Strategy presets">
                {(
                  [
                    ['core', 'Core'],
                    ['value', 'Value'],
                    ['growth', 'Growth'],
                    ['quant', 'Quant'],
                    ['custom', 'Custom'],
                  ] as [PresetId, string][]
                ).map(([id, label]) => (
                  <Button
                    key={id}
                    variant={preset === id ? undefined : 'outline'}
                    size="sm"
                    onClick={() => onPresetClick(id)}
                    className={cn(preset === id && 'bg-blue-600 hover:bg-blue-500 text-white')}
                  >
                    {label}
                  </Button>
                ))}
              </div>

              <div className="flex flex-wrap gap-2 items-center">
                <span className="text-xs uppercase tracking-wide text-muted-foreground mr-1">
                  Always included
                </span>
                {alwaysOnStrategies.length === 0 ? (
                  <>
                    <Badge variant="secondary" className="gap-1">
                      <Lock className="h-3 w-3" />
                      Risk Manager
                    </Badge>
                    <Badge variant="secondary" className="gap-1">
                      <Lock className="h-3 w-3" />
                      Portfolio Manager
                    </Badge>
                  </>
                ) : (
                  alwaysOnStrategies.map((s) => (
                    <Badge key={s.id} variant="secondary" className="gap-1" title={s.description}>
                      <Lock className="h-3 w-3" />
                      {s.name}
                    </Badge>
                  ))
                )}
              </div>

              {loading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" /> Loading strategies…
                </div>
              ) : (
                <div>
                  <div className="text-xs uppercase tracking-wide text-muted-foreground mb-2">
                    Analysts {preset !== 'custom' ? `(${preset})` : '(custom)'}
                  </div>
                  <div className="grid sm:grid-cols-2 gap-2">
                    {analystStrategies.map((s) => {
                      const checked = selected.has(s.id);
                      return (
                        <label
                          key={s.id}
                          className={cn(
                            'flex items-start gap-3 rounded-lg border p-3 cursor-pointer hover:bg-ramp-grey-800/40',
                            checked && 'border-blue-500/50 bg-blue-500/5'
                          )}
                        >
                          <Checkbox
                            checked={checked}
                            onCheckedChange={() => toggle(s.id)}
                            className="mt-0.5"
                          />
                          <div className="min-w-0">
                            <div className="text-sm font-medium text-primary">{s.name}</div>
                            <div className="text-xs text-muted-foreground line-clamp-2">{s.description}</div>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Tickers & run</CardTitle>
              <CardDescription>Comma-separated, max 20. Example: NVDA, AAPL, MSFT</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-col sm:flex-row gap-3">
                <Input
                  value={tickers}
                  onChange={(e) => setTickers(e.target.value)}
                  placeholder="NVDA, AAPL, MSFT"
                  className="flex-1"
                />
                <Button
                  size="lg"
                  onClick={onRun}
                  disabled={running || loading || !serverKeys}
                  className="bg-blue-600 hover:bg-blue-500 text-white min-w-[220px]"
                  title={!serverKeys ? 'FAIL_CLOSED: server Alpaca keys missing' : undefined}
                >
                  {running ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin mr-2" />
                      Running…
                    </>
                  ) : (
                    <>
                      <Play className="h-4 w-4 mr-2" />
                      {runButtonLabel}
                    </>
                  )}
                </Button>
              </div>

              <label
                className={cn(
                  'flex items-start gap-3 rounded-lg border p-3 cursor-pointer',
                  executeTrades && 'border-blue-500/50 bg-blue-500/5',
                  instrument === 'options' && 'opacity-60 cursor-not-allowed'
                )}
              >
                <Checkbox
                  checked={executeTrades}
                  disabled={instrument === 'options'}
                  onCheckedChange={(c) => setExecuteTrades(c === true)}
                  className="mt-0.5"
                />
                <div className="min-w-0">
                  <div className="text-sm font-medium text-primary">Execute paper trades on Alpaca</div>
                  <div className="text-xs text-muted-foreground mt-0.5">
                    Default is analysis-only. When checked, Run places paper orders after the swarm finishes
                    (stocks only). Never live.
                    {instrument === 'options' ? ' Disabled for options (research-only).' : ''}
                  </div>
                </div>
              </label>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Recent paper runs</CardTitle>
              <CardDescription>
                Session history — clears on refresh. Not a durable archive.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {runHistory.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No paper runs yet this session. Complete a run to see it listed here (clears on refresh).
                </p>
              ) : (
                <ul className="space-y-2">
                  {runHistory.map((h) => (
                    <li
                      key={h.run_id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2"
                    >
                      <div className="min-w-0">
                        <div className="text-sm font-medium truncate">
                          {h.tickers.slice(0, 5).join(', ') || '—'}
                          {h.tickers.length > 5 ? ` +${h.tickers.length - 5}` : ''}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {new Date(h.started_at).toLocaleString(undefined, {
                            month: 'short',
                            day: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit',
                          })}{' '}
                          · {h.mode} · {h.instrument || 'stocks'} ·{' '}
                          <span className="font-mono">{h.run_id.slice(0, 8)}</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge
                          variant={
                            h.status === 'complete'
                              ? 'success'
                              : h.status === 'error' || h.status === 'fail_closed'
                                ? 'destructive'
                                : 'warning'
                          }
                          className="capitalize text-[10px]"
                        >
                          {h.status}
                        </Badge>
                        <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => viewHistoryRun(h)}>
                          View
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>


          <Card>
            <CardHeader className="pb-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <CardTitle className="text-base">Ops / Automation</CardTitle>
                  <CardDescription>
                    Last cron paper-run and portfolio monitor (read-only). Paper-only; no secrets shown.
                  </CardDescription>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs"
                  onClick={() => refreshOps()}
                  disabled={opsLoading}
                >
                  {opsLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                  <span className="ml-1">Refresh</span>
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex flex-wrap gap-2 items-center">
                <Badge variant="outline">paper-only</Badge>
                <Badge variant={opsStatus?.monitor_dry_run_env !== false ? 'success' : 'warning'}>
                  monitor dry_run env: {opsStatus?.monitor_dry_run_env === false ? 'false (hot allowed)' : 'true'}
                </Badge>
              </div>
              <div className="rounded-lg border px-3 py-2 space-y-1">
                <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Last cron paper-run
                </div>
                {opsStatus?.last_paper_run?.run_id ? (
                  <>
                    <div className="font-mono text-xs break-all">{opsStatus.last_paper_run.run_id}</div>
                    <div className="text-xs text-muted-foreground">
                      status: <span className="capitalize">{opsStatus.last_paper_run.status || '—'}</span>
                      {opsStatus.last_paper_run.mode ? ` · ${opsStatus.last_paper_run.mode}` : ''}
                      {opsStatus.last_paper_run.created_at
                        ? ` · ${new Date(opsStatus.last_paper_run.created_at).toLocaleString()}`
                        : ''}
                    </div>
                  </>
                ) : (
                  <p className="text-xs text-muted-foreground">No cron paper-run recorded yet.</p>
                )}
              </div>
              <div className="rounded-lg border px-3 py-2 space-y-1">
                <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Last monitor actions
                </div>
                {opsStatus?.last_monitor ? (
                  <>
                    <div className="text-xs text-muted-foreground">
                      {opsStatus.last_monitor.timestamp
                        ? new Date(opsStatus.last_monitor.timestamp).toLocaleString()
                        : '—'}
                      {' · '}
                      dry_run={String(opsStatus.last_monitor.dry_run ?? '—')}
                      {opsStatus.last_monitor.trading_mode
                        ? ` · ${opsStatus.last_monitor.trading_mode}`
                        : ''}
                      {typeof opsStatus.last_monitor.stops_triggered === 'number'
                        ? ` · stops ${opsStatus.last_monitor.stops_triggered}`
                        : ''}
                    </div>
                    {(opsStatus.last_monitor.actions || []).length === 0 ? (
                      <p className="text-xs text-muted-foreground">No would-sell / sell actions.</p>
                    ) : (
                      <ul className="space-y-1 max-h-40 overflow-auto">
                        {(opsStatus.last_monitor.actions || []).slice(0, 12).map((a, i) => (
                          <li key={i} className="text-xs font-mono truncate">
                            {String(a.stop_type || a.action || 'action')}:{' '}
                            {String(a.symbol || a.ticker || '?')}
                            {a.dry_run ? ' [dry-run]' : ''}
                            {a.reason ? ` — ${String(a.reason).slice(0, 80)}` : ''}
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                ) : (
                  <p className="text-xs text-muted-foreground">No monitor run recorded yet.</p>
                )}
              </div>
            </CardContent>
          </Card>

          {run && (
            <Card className="overflow-hidden">
              <CardHeader className="pb-3 border-b border-ramp-grey-800/80 bg-ramp-grey-800/20">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <CardTitle className="text-base">Swarm research results</CardTitle>
                    <CardDescription className="font-mono text-xs mt-1">{run.run_id}</CardDescription>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline" className="capitalize">
                      {(run.instrument || run.summary?.instrument || instrument) as string}
                    </Badge>
                    <Badge variant="outline" className="capitalize">
                      {run.mode || mode}
                    </Badge>
                    <Badge
                      variant={
                        run.status === 'complete'
                          ? 'success'
                          : run.status === 'error' || run.status === 'fail_closed'
                            ? 'destructive'
                            : 'warning'
                      }
                    >
                      {run.status}
                    </Badge>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-5 pt-5">
                {run.error && (
                  <div className="text-sm text-red-300 whitespace-pre-wrap rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2">
                    {run.error}
                  </div>
                )}
                {run.summary?.execute_blocked_reason && (
                  <div className="text-sm text-amber-200 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2">
                    {run.summary.execute_blocked_reason}
                  </div>
                )}

                {Object.keys(actionCounts).length > 0 && (
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                    {(['buy', 'sell', 'short', 'cover', 'hold'] as const).map((k) => (
                      <div key={k} className={cn('rounded-lg border px-3 py-2 text-center', actionTone(k))}>
                        <div className="text-[10px] uppercase tracking-wide opacity-80">{k}</div>
                        <div className="text-lg font-semibold tabular-nums">{actionCounts[k] ?? 0}</div>
                      </div>
                    ))}
                  </div>
                )}

                {decisions.length > 0 && (
                  <div className="space-y-2">
                    <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Decisions
                    </div>
                    <div className="grid gap-2">
                      {decisions.map((d) => {
                        const open = expanded.has(d.ticker);
                        const agentInst = d.agent_instrument;
                        const effective = d.instrument || run.summary?.instrument || instrument;
                        const override =
                          agentInst && effective && agentInst !== effective
                            ? `agent: ${agentInst} → you: ${effective}`
                            : agentInst
                              ? `agent: ${agentInst}`
                              : null;
                        return (
                          <div
                            key={d.ticker}
                            className="rounded-xl border bg-ramp-grey-800/20 overflow-hidden"
                          >
                            <button
                              type="button"
                              className="w-full flex flex-wrap items-center gap-3 p-3 text-left hover:bg-ramp-grey-800/40"
                              onClick={() =>
                                setExpanded((prev) => {
                                  const next = new Set(prev);
                                  if (next.has(d.ticker)) next.delete(d.ticker);
                                  else next.add(d.ticker);
                                  return next;
                                })
                              }
                            >
                              {open ? (
                                <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
                              ) : (
                                <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                              )}
                              <span className="font-semibold tracking-tight min-w-[64px]">{d.ticker}</span>
                              <span
                                className={cn(
                                  'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium uppercase',
                                  actionTone(d.action)
                                )}
                              >
                                {d.action}
                              </span>
                              <span className="text-xs text-muted-foreground">qty {d.quantity ?? '—'}</span>
                              <div className="flex-1 min-w-[120px]">
                                <ConfidenceBar value={d.confidence} />
                              </div>
                              {override && (
                                <Badge variant="outline" className="text-[10px] font-normal">
                                  {override}
                                </Badge>
                              )}
                            </button>
                            {open && (
                              <div className="px-4 pb-3 pt-0 border-t border-ramp-grey-800/80">
                                <p className="text-sm text-muted-foreground whitespace-pre-wrap leading-relaxed pt-3">
                                  {d.reasoning || 'No reasoning provided.'}
                                </p>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {tradeResults.length > 0 && (
                  <div className="space-y-2">
                    <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Trade results
                    </div>
                    <div className="overflow-x-auto rounded-md border">
                      <table className="w-full text-sm">
                        <thead className="bg-ramp-grey-800/50 text-left text-xs text-muted-foreground">
                          <tr>
                            <th className="p-2">Ticker</th>
                            <th className="p-2">Action</th>
                            <th className="p-2">Qty</th>
                            <th className="p-2">Status</th>
                            <th className="p-2">Note</th>
                          </tr>
                        </thead>
                        <tbody>
                          {tradeResults.map((tr, i) => (
                            <tr key={i} className="border-t border-ramp-grey-800">
                              <td className="p-2 font-medium">{String(tr.ticker ?? '—')}</td>
                              <td className="p-2 uppercase text-xs">{String(tr.action ?? '—')}</td>
                              <td className="p-2 tabular-nums">{String(tr.qty ?? tr.quantity ?? '—')}</td>
                              <td className="p-2">
                                <Badge
                                  variant={tr.success ? 'success' : 'destructive'}
                                  className="text-[10px]"
                                >
                                  {String(tr.status ?? (tr.success ? 'ok' : 'failed'))}
                                </Badge>
                              </td>
                              <td className="p-2 text-xs text-muted-foreground truncate max-w-xs">
                                {String(tr.reason ?? '')}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {!run.error && decisions.length === 0 && !TERMINAL.has(run.status) && (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground py-6 justify-center">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Agents analyzing… this can take a few minutes.
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        {showSticky && run && (
          <div
            className="fixed bottom-0 inset-x-0 z-40 border-t border-blue-500/30 bg-panel/95 backdrop-blur supports-[backdrop-filter]:bg-panel/90 shadow-[0_-4px_24px_rgba(0,0,0,0.35)]"
            role="status"
            aria-live="polite"
          >
            <div className="max-w-5xl mx-auto px-4 py-2 flex flex-wrap items-center gap-3 text-sm">
              {runActive ? <Loader2 className="h-4 w-4 animate-spin text-blue-400 shrink-0" /> : null}
              <Badge
                variant={
                  run.status === 'complete'
                    ? 'success'
                    : run.status === 'error' || run.status === 'fail_closed'
                      ? 'destructive'
                      : 'warning'
                }
                className="capitalize shrink-0"
              >
                {run.status}
              </Badge>
              <span className="font-mono text-xs text-muted-foreground shrink-0">
                {run.run_id.slice(0, 8)}
              </span>
              <span className="text-xs text-muted-foreground truncate">
                {(run.tickers || []).length} ticker{(run.tickers || []).length === 1 ? '' : 's'}
                {run.summary?.analyst_count != null
                  ? ` · ${run.summary.analyst_count} analysts`
                  : ` · ${selected.size} analysts`}
                {runActive ? ` · ${runElapsedSec}s` : ''}
              </span>
              {runActive && (
                <div className="flex-1 min-w-[120px] h-1.5 rounded-full bg-ramp-grey-800 overflow-hidden">
                  <div className="h-full w-1/3 rounded-full bg-blue-500 animate-pulse" />
                </div>
              )}
              {!runActive && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 text-xs ml-auto"
                  onClick={() => setStickyDismissed(true)}
                >
                  Dismiss
                </Button>
              )}
            </div>
          </div>
        )}

        <CloseSheet
          open={closeSheetOpen}
          onOpenChange={setCloseSheetOpen}
          title={
            closeSheetSymbols.length === 1
              ? `Close ${closeSheetSymbols[0]}`
              : `Close ${closeSheetSymbols.length} positions`
          }
          description="Choose a close percent, then confirm. Paper only — no live trading."
          percent={closeSheetPercent}
          onPercentChange={setCloseSheetPercent}
          confirming={closing}
          onConfirm={confirmClose}
        />
      </div>
    </TooltipProvider>
  );
}
