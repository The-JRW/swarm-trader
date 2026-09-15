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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { BookRecords } from '@/components/strategies/book-records';
import { actionTone } from '@/components/strategies/format';
import { PortfolioBook } from '@/components/strategies/portfolio-book';
import { RecipeHintsPanel } from '@/components/strategies/recipe-hints-panel';
import { RiskPolicyPanel } from '@/components/strategies/risk-policy-panel';
import { cn } from '@/lib/utils';
import {
  ApplyScanResponse,
  AutomationOpsStatus,
  ConvictionDigest,
  CronRecipe,
  DurableRunSummary,
  PaperRunDecision,
  PaperRunStatusResponse,
  PortfolioOrder,
  PortfolioPosition,
  PortfolioPositionsResponse,
  RecipeHintsResponse,
  ScanCandidate,
  ScanHistoryEntry,
  Strategy,
  SwarmScanResult,
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

  // B1 recipe
  const [recipe, setRecipe] = useState<CronRecipe | null>(null);
  const [recipeTickers, setRecipeTickers] = useState('NVDA, AAPL, MSFT, AMZN, META, GOOGL, SPY');
  const [recipePreset, setRecipePreset] = useState<PresetId>('core');
  const [recipeMode, setRecipeMode] = useState<TradingModeChoice>('swing');
  const [recipeSaving, setRecipeSaving] = useState(false);
  const [executeConfirmOpen, setExecuteConfirmOpen] = useState(false);

  // Wave C — swarm scan
  const [scanResult, setScanResult] = useState<SwarmScanResult | null>(null);
  const [scanCandidates, setScanCandidates] = useState<ScanCandidate[]>([]);
  const [recentScans, setRecentScans] = useState<ScanHistoryEntry[]>([]);
  const [scanLoading, setScanLoading] = useState(false);
  const [applyLoading, setApplyLoading] = useState(false);
  const [launchLoading, setLaunchLoading] = useState(false);
  const [intersectUniverse, setIntersectUniverse] = useState(true);
  const [applyTopN, setApplyTopN] = useState(15);

  // Wave D
  const [pane, setPane] = useState<'run' | 'book'>('run');
  const [sectorAware, setSectorAware] = useState(true);
  const [applyResult, setApplyResult] = useState<ApplyScanResponse | null>(null);
  const [hints, setHints] = useState<RecipeHintsResponse | null>(null);
  const [hintsLoading, setHintsLoading] = useState(false);

  // B5 mode override reason
  const [overrideReason, setOverrideReason] = useState('');
  const [useOverride, setUseOverride] = useState(true);
  const [modeOverrideActive, setModeOverrideActive] = useState<string | null>(null);

  // B2 durable history
  const [durableHistory, setDurableHistory] = useState<DurableRunSummary[]>([]);

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


  /** D5 — pull display-only hints; never writes the recipe. */
  const refreshHints = useCallback(async () => {
    setHintsLoading(true);
    try {
      setHints(await strategiesApi.getRecipeHints());
    } catch {
      setHints(null);
    } finally {
      setHintsLoading(false);
    }
  }, []);

  const refreshOps = useCallback(async () => {
    setOpsLoading(true);
    try {
      const [s, r, hist] = await Promise.all([
        strategiesApi.getAutomationStatus(),
        strategiesApi.getRecipe().catch(() => null),
        strategiesApi.getRunHistory(50).catch(() => ({ runs: [] as DurableRunSummary[] })),
      ]);
      setOpsStatus(s);
      if (r) {
        setRecipe(r);
        setRecipeTickers((r.tickers || []).join(', '));
        const p = (r.preset || 'core') as PresetId;
        if (['core', 'value', 'growth', 'quant', 'custom'].includes(p)) setRecipePreset(p);
        const m = (r.mode || 'swing').toLowerCase();
        if (m === 'swing' || m === 'day' || m === 'auto') setRecipeMode(m);
      } else if (s.recipe) {
        setRecipe(s.recipe as CronRecipe);
      }
      setDurableHistory(hist.runs || []);
      if (s.recent_scans) setRecentScans(s.recent_scans);
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
      setModeOverrideActive(trading.override || null);
      if (trading.last_mode_reason) setOverrideReason(trading.last_mode_reason);
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
    refreshHints();
  }, [load, refreshPortfolio, refreshOps, refreshHints]);

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
          void strategiesApi.getRunHistory(50).then((h) => setDurableHistory(h.runs || [])).catch(() => {});
          void refreshHints();
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
  }, [run?.run_id, run?.status, refreshPortfolio, refreshHints, mode, instrument]);

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
      const reason =
        overrideReason.trim() ||
        (useOverride ? `Human override to ${next} from Strategies UI` : `Set to ${next} from Strategies UI`);
      const trading = await strategiesApi.setTradingMode(next, {
        reason,
        override: useOverride && next !== 'auto',
      });
      const resolved = (trading.resolved_mode || 'swing').toLowerCase();
      setResolvedMode(resolved === 'day' ? 'day' : 'swing');
      setModeReason(
        trading.last_mode_reason ||
          (next === 'auto' ? 'UI deterministic fallback — agent VIX pick not wired' : null)
      );
      setModeOverrideActive(trading.override || null);
      toast.success(useOverride && next !== 'auto' ? `Override set to ${next}` : `Mode set to ${next}`);
    } catch (e: any) {
      toast.error(e?.message || 'Failed to set mode');
    }
  };

  const saveRecipe = async (opts?: { execute_trades?: boolean }) => {
    setRecipeSaving(true);
    try {
      const parsed = recipeTickers
        .split(/[\s,]+/)
        .map((t) => t.trim().toUpperCase())
        .filter(Boolean);
      if (parsed.length === 0) {
        toast.error('Recipe needs at least one ticker');
        return;
      }
      const body: {
        tickers: string[];
        preset: string;
        mode: string;
        execute_trades?: boolean;
      } = {
        tickers: parsed,
        preset: recipePreset,
        mode: recipeMode,
      };
      if (opts && 'execute_trades' in opts) {
        body.execute_trades = opts.execute_trades;
      }
      const saved = await strategiesApi.putRecipe(body);
      setRecipe(saved);
      toast.success('Cron recipe saved');
      await refreshOps();
    } catch (e: any) {
      toast.error(e?.message || 'Failed to save recipe');
    } finally {
      setRecipeSaving(false);
      setExecuteConfirmOpen(false);
    }
  };

  const runSwarmScan = async () => {
    setScanLoading(true);
    try {
      const res = await strategiesApi.runSwarmScan({
        mode: recipeMode,
        intersect_universe: intersectUniverse,
        include_core: true,
      });
      setScanResult(res);
      setScanCandidates(res.candidates || []);
      toast.success(
        `Scan complete — ${res.candidate_count ?? (res.candidates || []).length} candidates`
      );
      await refreshOps();
      const hist = await strategiesApi.getSwarmScan().catch(() => null);
      if (hist?.recent_scans) setRecentScans(hist.recent_scans);
    } catch (e: any) {
      toast.error(e?.message || 'Scan failed');
    } finally {
      setScanLoading(false);
    }
  };

  /** D3 — sector-aware apply. `explicitTickers` comes from an explicit user action. */
  const applyScanToRecipe = async (explicitTickers?: string[]) => {
    setApplyLoading(true);
    try {
      const n = Math.max(1, Math.min(applyTopN || 15, 15));
      const tickers =
        explicitTickers && explicitTickers.length > 0
          ? explicitTickers.slice(0, 15)
          : scanCandidates.length > 0
            ? scanCandidates.map((c) => c.symbol)
            : undefined;
      const res = await strategiesApi.applyScanToRecipe({
        top_n: explicitTickers?.length ? Math.min(explicitTickers.length, 15) : n,
        tickers,
        sector_aware: sectorAware,
        mode: recipeMode,
      });
      setRecipe(res.recipe);
      setRecipeTickers((res.applied_tickers || []).join(', '));
      setApplyResult(res);
      const trimmed = res.sector_caps_trimmed ? ' — sector caps trimmed some tickers' : '';
      toast.success(
        `Applied ${res.applied_count} tickers to recipe (cap ${res.cap})${trimmed}`
      );
      await refreshOps();
      await refreshHints();
    } catch (e: any) {
      toast.error(e?.message || 'Apply to recipe failed');
    } finally {
      setApplyLoading(false);
    }
  };

  const launchAnalysisFromScan = async () => {
    setLaunchLoading(true);
    try {
      const res = await strategiesApi.launchFromScan({
        execute_trades: false,
        confirm_execute: false,
      });
      toast.success(res.message || `Analysis queued: ${res.run_id?.slice(0, 8)}`);
      await refreshOps();
    } catch (e: any) {
      toast.error(e?.message || 'Launch analysis failed');
    } finally {
      setLaunchLoading(false);
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

  const viewHistoryRun = async (item: { run_id: string }) => {
    try {
      const status = await strategiesApi.getRun(item.run_id);
      setRun(status);
      setStickyDismissed(TERMINAL.has(status.status));
      toast.message(`Showing run ${item.run_id.slice(0, 8)}`);
    } catch (e: any) {
      toast.error(e?.message || 'Run no longer available');
    }
  };

  const convictionDigest: ConvictionDigest | null =
    run?.conviction_digest || run?.summary?.conviction_digest || null;

  /** Book pane run list — durable history when present, session history otherwise. */
  const bookRuns: DurableRunSummary[] =
    durableHistory.length > 0
      ? durableHistory
      : runHistory.map((h) => ({
          run_id: h.run_id,
          status: h.status,
          mode: h.mode,
          instrument: h.instrument,
          tickers: h.tickers,
          created_at: h.started_at,
          started_at: h.started_at,
        }));

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
                <span className="text-primary font-medium">Run</span> is the paper swarm: mode,
                instrument, analysts, tickers, and scan → recipe → launch ops.{' '}
                <span className="text-primary font-medium">Book</span> holds the portfolio, closes,
                orders, and run records. Flow graphs live under Advanced.
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

          <Tabs
            value={pane}
            onValueChange={(v) => setPane(v === 'book' ? 'book' : 'run')}
            className="w-full"
          >
            <TabsList className="bg-ramp-grey-800/40">
              <TabsTrigger value="run">Run</TabsTrigger>
              <TabsTrigger value="book">Book</TabsTrigger>
            </TabsList>

            <TabsContent value="run" className="space-y-5 mt-4">
              <div className="grid lg:grid-cols-2 gap-5">
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base">Trading mode</CardTitle>
                    <CardDescription>
                      Human override wins for swing/day. Auto uses deterministic UI resolution — not live
                      VIX/agent pick. Paper-only; never flips live Alpaca mode.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
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
                    <label className="flex items-start gap-2 text-xs cursor-pointer">
                      <Checkbox
                        checked={useOverride}
                        onCheckedChange={(c) => setUseOverride(c === true)}
                        className="mt-0.5"
                      />
                      <span className="text-muted-foreground">
                        Apply as human override (wins over auto until cleared)
                      </span>
                    </label>
                    <div className="space-y-1">
                      <div className="text-xs font-medium text-muted-foreground">Override reason</div>
                      <Input
                        value={overrideReason}
                        onChange={(e) => setOverrideReason(e.target.value)}
                        placeholder="Why are you changing mode?"
                        className="h-8 text-sm"
                      />
                    </div>
                    {modeOverrideActive && (
                      <p className="text-xs text-amber-200/90">
                        Active override: <span className="font-medium">{modeOverrideActive}</span>
                      </p>
                    )}
                    {(modeReason || overrideReason) && (
                      <p className="text-xs text-muted-foreground">
                        Last reason: <span className="text-primary">{modeReason || overrideReason}</span>
                      </p>
                    )}
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

              <RiskPolicyPanel mode={mode} />

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
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <CardTitle className="text-base">Ops — scan, recipe, launch</CardTitle>
                      <CardDescription>
                        Cron recipe plus swarm scan → apply → launch, on the Run surface. Paper-only; no
                        secrets. Monitor, digest, and cron receipts live in the Book pane.
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
                    <Badge variant={opsStatus?.cron_execute_env_allows ? 'warning' : 'success'}>
                      cron execute env: {opsStatus?.cron_execute_env_allows ? 'allows' : 'blocked (safe)'}
                    </Badge>
                  </div>

                  <div className="rounded-lg border px-3 py-3 space-y-3">
                    <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      Cron recipe (B1)
                    </div>
                    <div className="space-y-1">
                      <div className="text-xs text-muted-foreground">Tickers</div>
                      <Input
                        value={recipeTickers}
                        onChange={(e) => setRecipeTickers(e.target.value)}
                        className="h-8 text-sm"
                        placeholder="NVDA, AAPL, MSFT"
                      />
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {(['core', 'value', 'growth', 'quant', 'custom'] as PresetId[]).map((p) => (
                        <Button
                          key={p}
                          size="sm"
                          variant={recipePreset === p ? undefined : 'outline'}
                          className={cn('h-7 capitalize', recipePreset === p && 'bg-blue-600 text-white')}
                          onClick={() => setRecipePreset(p)}
                        >
                          {p}
                        </Button>
                      ))}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {(['swing', 'day', 'auto'] as TradingModeChoice[]).map((m) => (
                        <Button
                          key={m}
                          size="sm"
                          variant={recipeMode === m ? undefined : 'outline'}
                          className={cn('h-7', recipeMode === m && 'bg-blue-600 text-white')}
                          onClick={() => setRecipeMode(m)}
                        >
                          {m}
                        </Button>
                      ))}
                    </div>
                    <div className="flex flex-wrap gap-2 items-center">
                      <Button
                        size="sm"
                        className="h-8 bg-blue-600 hover:bg-blue-500 text-white"
                        disabled={recipeSaving}
                        onClick={() => saveRecipe()}
                      >
                        {recipeSaving ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
                        Save recipe
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-8"
                        disabled={recipeSaving}
                        onClick={() => setExecuteConfirmOpen(true)}
                      >
                        Enable execute for next cron…
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-8 text-xs"
                        disabled={recipeSaving || !recipe?.execute_trades}
                        onClick={() => saveRecipe({ execute_trades: false })}
                      >
                        Clear execute flag
                      </Button>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Recipe execute_trades: <strong>{String(recipe?.execute_trades ?? false)}</strong>
                      {' · '}
                      Effective next cron:{' '}
                      <strong>
                        {String(
                          Boolean(recipe?.execute_trades) && Boolean(opsStatus?.cron_execute_env_allows)
                        )}
                      </strong>
                      {' '}
                      (dual gate: recipe + SWARM_CRON_EXECUTE_TRADES)
                    </p>
                  </div>

                  <div className="rounded-lg border px-3 py-3 space-y-3">
                    <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      Swarm scan (Wave C)
                    </div>
                    <div className="flex flex-wrap gap-2 items-center">
                      <Badge variant={opsStatus?.auto_launch_env_allows ? 'warning' : 'success'}>
                        auto-launch env:{' '}
                        {opsStatus?.auto_launch_env_allows ? 'on' : 'off (scan-only cron)'}
                      </Badge>
                      <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
                        <Checkbox
                          checked={intersectUniverse}
                          onCheckedChange={(v) => setIntersectUniverse(v === true)}
                        />
                        Intersect mode universe (default ON)
                      </label>
                      <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
                        <Checkbox
                          checked={sectorAware}
                          onCheckedChange={(v) => setSectorAware(v === true)}
                        />
                        Sector-aware apply (underweight first, default ON)
                      </label>
                    </div>
                    <div className="flex flex-wrap gap-2 items-center">
                      <Button
                        size="sm"
                        className="h-8 bg-blue-600 hover:bg-blue-500 text-white"
                        disabled={scanLoading}
                        onClick={() => runSwarmScan()}
                      >
                        {scanLoading ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
                        Scan market
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-8"
                        disabled={applyLoading || (!scanCandidates.length && !opsStatus?.last_scan)}
                        onClick={() => applyScanToRecipe()}
                      >
                        {applyLoading ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
                        Apply to recipe
                      </Button>
                      <div className="flex items-center gap-1 text-xs text-muted-foreground">
                        top
                        <Input
                          type="number"
                          min={1}
                          max={15}
                          value={applyTopN}
                          onChange={(e) =>
                            setApplyTopN(Math.max(1, Math.min(15, Number(e.target.value) || 15)))
                          }
                          className="h-7 w-14 text-xs"
                        />
                        /15
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-8"
                        disabled={launchLoading}
                        onClick={() => launchAnalysisFromScan()}
                      >
                        {launchLoading ? (
                          <Loader2 className="h-3 w-3 animate-spin mr-1" />
                        ) : (
                          <Play className="h-3 w-3 mr-1" />
                        )}
                        Run analysis
                      </Button>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Paper-only. Run analysis uses recipe/CORE analysts (analysis-only default).
                      Execute still dual-gated. Cron apply/launch only if SWARM_AUTO_LAUNCH.
                    </p>
                    {scanResult?.mode ? (
                      <p className="text-xs text-muted-foreground">Last run mode: {scanResult.mode}</p>
                    ) : null}
                    {scanCandidates.length > 0 ? (
                      <ul className="space-y-0.5 max-h-36 overflow-auto font-mono text-xs">
                        {scanCandidates.slice(0, 20).map((c) => (
                          <li key={c.symbol}>
                            {c.symbol}{' '}
                            <span className="text-muted-foreground">
                              [{(c.sources || []).join('+') || '—'}]
                              {typeof c.change_pct === 'number' ? ` ${c.change_pct}%` : ''}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : opsStatus?.last_scan?.tickers?.length ? (
                      <p className="text-xs text-muted-foreground font-mono">
                        Last scan: {(opsStatus.last_scan.tickers || []).slice(0, 12).join(', ')}
                        {opsStatus.last_scan.candidate_count
                          ? ` (${opsStatus.last_scan.candidate_count})`
                          : ''}
                      </p>
                    ) : (
                      <p className="text-xs text-muted-foreground">No scan yet — click Scan market.</p>
                    )}
                    {recentScans.length > 0 ? (
                      <div className="space-y-1">
                        <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                          Recent scans (C5)
                        </div>
                        <ul className="space-y-0.5 max-h-28 overflow-auto text-xs text-muted-foreground">
                          {recentScans.slice(0, 8).map((s, i) => (
                            <li key={`${s.updated_at || s.timestamp || i}`}>
                              {s.updated_at || s.timestamp || '—'} · {s.mode || '—'} ·{' '}
                              {s.candidate_count ?? (s.tickers || []).length} tickers
                              {s.intersect_universe ? ' · intersect' : ''}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}

                    {applyResult ? (
                      <div className="space-y-2 rounded-md border border-blue-500/30 bg-blue-500/5 px-3 py-2">
                        <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                          Last apply — sector-aware (D3)
                        </div>
                        <div className="text-xs text-muted-foreground">
                          Applied{' '}
                          <span className="font-mono text-primary">
                            {(applyResult.applied_tickers || []).join(', ')}
                          </span>{' '}
                          ({applyResult.applied_count}/{applyResult.cap})
                          {applyResult.sector_aware === false ? ' · sector-aware off' : ''}
                        </div>
                        {(applyResult.sectors || []).length > 0 ? (
                          <ul className="text-xs text-muted-foreground space-y-0.5">
                            {(applyResult.sectors || []).map((s) => (
                              <li key={s.sector}>
                                {s.label}: {s.picked}/{s.slot_cap} picked
                                {s.max_sector_pct != null ? ` (≤${s.max_sector_pct}% sector cap)` : ' (uncapped)'}
                                {s.in_current_recipe ? ` · ${s.in_current_recipe} already held in recipe` : ''}
                              </li>
                            ))}
                          </ul>
                        ) : null}
                        {(applyResult.skipped || []).length > 0 ? (
                          <div className="space-y-0.5">
                            <div className="text-xs font-medium text-amber-200/90">
                              Skipped {applyResult.skipped_count ?? applyResult.skipped?.length} — why
                            </div>
                            <ul className="text-xs text-muted-foreground max-h-28 overflow-auto space-y-0.5">
                              {(applyResult.skipped || []).slice(0, 15).map((s) => (
                                <li key={`${s.symbol}-${s.kind}`}>
                                  <span className="font-mono text-primary">{s.symbol}</span> — {s.reason}
                                </li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                        {(applyResult.notes || []).map((n) => (
                          <p key={n} className="text-xs text-amber-200/90">
                            {n}
                          </p>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </CardContent>
              </Card>

              <RecipeHintsPanel
                hints={hints}
                loading={hintsLoading}
                applying={applyLoading}
                onRefresh={() => refreshHints()}
                onApply={(t) => applyScanToRecipe(t)}
              />

              <Dialog open={executeConfirmOpen} onOpenChange={setExecuteConfirmOpen}>
                <DialogContent className="sm:max-w-md">
                  <DialogHeader>
                    <DialogTitle>Enable execute_trades for next cron?</DialogTitle>
                    <DialogDescription>
                      This sets recipe execute_trades=true. Cron will still force false unless env
                      SWARM_CRON_EXECUTE_TRADES is truthy (dual gate). Paper-only — never live.
                      {opsStatus?.cron_execute_env_allows
                        ? ' Env currently ALLOWS execute.'
                        : ' Env currently BLOCKS execute (safe).'}
                    </DialogDescription>
                  </DialogHeader>
                  <DialogFooter className="gap-2 sm:gap-0">
                    <Button variant="outline" onClick={() => setExecuteConfirmOpen(false)}>
                      Cancel
                    </Button>
                    <Button
                      className="bg-amber-600 hover:bg-amber-500 text-white"
                      disabled={recipeSaving}
                      onClick={() => saveRecipe({ execute_trades: true })}
                    >
                      Confirm enable
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>

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

                    {convictionDigest && (
                      <div className="rounded-lg border px-3 py-3 space-y-2">
                        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          Conviction digest (from agent signals)
                        </div>
                        <div className="flex flex-wrap gap-2 text-xs">
                          <Badge variant="success">
                            consensus {(convictionDigest.consensus || []).length}
                          </Badge>
                          <Badge variant="warning">
                            contested {(convictionDigest.contested || []).length}
                          </Badge>
                          <Badge variant="destructive">
                            risk-rejected {(convictionDigest.risk_rejected || []).length}
                          </Badge>
                        </div>
                        <ul className="text-xs font-mono space-y-0.5 max-h-36 overflow-auto">
                          {(convictionDigest.consensus || []).map((c) => (
                            <li key={`rc-${c.ticker}`}>
                              ✓ {c.ticker} agree {c.direction} ({c.agree}/{c.total})
                            </li>
                          ))}
                          {(convictionDigest.contested || []).map((c) => (
                            <li key={`rx-${c.ticker}`}>
                              ? {c.ticker} bull {c.bullish} / bear {c.bearish} / neu {c.neutral}
                            </li>
                          ))}
                          {(convictionDigest.risk_rejected || []).map((c) => (
                            <li key={`rr-${c.ticker}`}>⛔ {c.ticker} — {c.reason}</li>
                          ))}
                        </ul>
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
            </TabsContent>

            <TabsContent value="book" className="space-y-5 mt-4">
              <PortfolioBook
                portfolio={portfolio}
                orders={orders}
                ordersMsg={ordersMsg}
                loading={portfolioLoading}
                closing={closing}
                selectedPositions={selectedPositions}
                onToggleSelected={(symbol) =>
                  setSelectedPositions((prev) => {
                    const next = new Set(prev);
                    if (next.has(symbol)) next.delete(symbol);
                    else next.add(symbol);
                    return next;
                  })
                }
                onSelectAll={(checked) =>
                  setSelectedPositions(checked ? new Set(positions.map((p) => p.symbol)) : new Set())
                }
                onRefresh={() => refreshPortfolio()}
                onClose={openCloseSheet}
              />

              <BookRecords
                runs={bookRuns}
                opsStatus={opsStatus}
                opsLoading={opsLoading}
                onRefresh={() => refreshOps()}
                onViewRun={(h) => {
                  void viewHistoryRun(h);
                  setPane('run');
                }}
              />
            </TabsContent>
          </Tabs>
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
