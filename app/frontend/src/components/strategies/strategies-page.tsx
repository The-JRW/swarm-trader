import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import {
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
  Play,
  RefreshCw,
  Shield,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

type TradingModeChoice = 'swing' | 'day' | 'auto';
type InstrumentChoice = 'stocks' | 'options';

const TERMINAL = new Set(['complete', 'error', 'fail_closed']);
const CLOSE_PRESETS = [25, 50, 75, 100] as const;

function fmtMoney(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
}

function fmtPct(frac?: number | null) {
  if (frac == null || Number.isNaN(frac)) return '—';
  // Alpaca unrealized_plpc is typically a fraction (0.05 = 5%)
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

function ClosePercentControl({
  value,
  onChange,
  disabled,
}: {
  value: number;
  onChange: (n: number) => void;
  disabled?: boolean;
}) {
  const set = (n: number) => onChange(Math.max(1, Math.min(100, Math.round(n))));
  return (
    <div className="flex flex-col gap-2 min-w-[200px]">
      <div className="flex flex-wrap gap-1">
        {CLOSE_PRESETS.map((p) => (
          <Button
            key={p}
            type="button"
            size="sm"
            variant={value === p ? undefined : 'outline'}
            disabled={disabled}
            className={cn('h-7 px-2 text-xs', value === p && 'bg-blue-600 hover:bg-blue-500 text-white')}
            onClick={() => set(p)}
          >
            {p}%
          </Button>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <input
          type="range"
          min={1}
          max={100}
          value={value}
          disabled={disabled}
          onChange={(e) => set(Number(e.target.value))}
          className="flex-1 accent-blue-500 h-1.5 cursor-pointer"
          aria-label="Close percent"
        />
        <Input
          type="number"
          min={1}
          max={100}
          value={value}
          disabled={disabled}
          onChange={(e) => set(Number(e.target.value) || 1)}
          className="w-16 h-7 text-xs px-2"
        />
        <span className="text-xs text-muted-foreground">%</span>
      </div>
    </div>
  );
}

export function StrategiesPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [mode, setMode] = useState<TradingModeChoice>('swing');
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

  const [portfolio, setPortfolio] = useState<PortfolioPositionsResponse | null>(null);
  const [orders, setOrders] = useState<PortfolioOrder[]>([]);
  const [ordersMsg, setOrdersMsg] = useState<string | null>(null);
  const [portfolioLoading, setPortfolioLoading] = useState(false);
  const [selectedPositions, setSelectedPositions] = useState<Set<string>>(new Set());
  const [closePctBySymbol, setClosePctBySymbol] = useState<Record<string, number>>({});
  const [bulkClosePct, setBulkClosePct] = useState(100);
  const [closing, setClosing] = useState(false);

  const refreshPortfolio = useCallback(async () => {
    setPortfolioLoading(true);
    try {
      const [pos, ord] = await Promise.all([
        strategiesApi.portfolioPositions().catch(async () => {
          // Fallback: glance-only if positions endpoint unavailable on older deploys
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
      setSelected(new Set(list.strategies.filter((s) => s.enabled_default).map((s) => s.id)));
    } catch (e: any) {
      setError(e?.message || 'Failed to load strategies');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    refreshPortfolio();
  }, [load, refreshPortfolio]);

  // Poll active run; refresh portfolio when execute run completes
  useEffect(() => {
    if (!run?.run_id || TERMINAL.has(run.status)) return;
    const id = setInterval(async () => {
      try {
        const next = await strategiesApi.getRun(run.run_id);
        setRun(next);
        if (TERMINAL.has(next.status)) {
          setRunning(false);
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
  }, [run?.run_id, run?.status, refreshPortfolio]);

  const byCategory = useMemo(() => {
    const groups: Record<string, Strategy[]> = { analyst: [], risk: [], pm: [] };
    for (const s of strategies) {
      (groups[s.category] || (groups[s.category] = [])).push(s);
    }
    return groups;
  }, [strategies]);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectCore = () => {
    setSelected(new Set(strategies.filter((s) => s.enabled_default).map((s) => s.id)));
  };

  const selectAnalystsOnly = () => {
    setSelected(
      new Set(
        strategies
          .filter((s) => s.category === 'analyst' && s.enabled_default)
          .concat(strategies.filter((s) => s.category === 'risk' || s.category === 'pm'))
          .map((s) => s.id)
      )
    );
  };

  const onModeChange = async (next: TradingModeChoice) => {
    setMode(next);
    try {
      await strategiesApi.setTradingMode(next);
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
      return;
    }
    if (executeTrades && instrument === 'options') {
      toast.error('Options paper execute not wired yet — research-only');
      return;
    }

    setRunning(true);
    setRun(null);
    setExpanded(new Set());
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
      toast(executeTrades ? 'Paper run + execute started' : 'Paper analysis started', {
        description: created.run_id.slice(0, 8),
      });
    } catch (e: any) {
      setRunning(false);
      setError(e?.message || 'Failed to start paper run');
      toast.error(e?.message || 'Failed to start paper run');
    }
  };

  const pctFor = (symbol: string) => closePctBySymbol[symbol] ?? 100;

  const onCloseOne = async (symbol: string) => {
    const percent = pctFor(symbol);
    setClosing(true);
    try {
      const res = await strategiesApi.closePosition({ symbol, percent });
      const r = res.results?.[0];
      if (r?.success) toast.success(`Closed ${percent}% of ${symbol}`);
      else toast.error(r?.reason || `Failed to close ${symbol}`);
      await refreshPortfolio();
    } catch (e: any) {
      toast.error(e?.message || `Failed to close ${symbol}`);
    } finally {
      setClosing(false);
    }
  };

  const onCloseSelected = async () => {
    if (selectedPositions.size === 0) {
      toast.error('Select at least one position');
      return;
    }
    setClosing(true);
    try {
      const items = [...selectedPositions].map((symbol) => ({
        symbol,
        percent: pctFor(symbol) || bulkClosePct,
      }));
      const res = await strategiesApi.closePositionsBatch(items);
      const ok = (res.results || []).filter((r) => r.success).length;
      const fail = (res.results || []).length - ok;
      if (ok) toast.success(`Closed ${ok} position(s)`);
      if (fail) toast.error(`${fail} close(s) failed`);
      setSelectedPositions(new Set());
      await refreshPortfolio();
    } catch (e: any) {
      toast.error(e?.message || 'Bulk close failed');
    } finally {
      setClosing(false);
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

  return (
    <div className="h-full w-full overflow-auto bg-panel">
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
              <Badge variant="secondary" className="gap-1">
                <Shield className="h-3 w-3" />
                using server keys
              </Badge>
            ) : (
              <Badge variant="warning">server keys missing</Badge>
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

        {error && (
          <div className="rounded-md border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {error}
          </div>
        )}

        {/* Portfolio / positions / orders strip */}
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
              <p className="text-sm text-muted-foreground">
                {portfolio?.message || 'Portfolio unavailable'}
              </p>
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
                    <div className="flex flex-wrap items-end justify-between gap-3">
                      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Open positions
                      </div>
                      <div className="flex flex-wrap items-end gap-3">
                        <ClosePercentControl
                          value={bulkClosePct}
                          onChange={(n) => {
                            setBulkClosePct(n);
                            setClosePctBySymbol((prev) => {
                              const next = { ...prev };
                              for (const s of selectedPositions) next[s] = n;
                              return next;
                            });
                          }}
                          disabled={closing}
                        />
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={closing || selectedPositions.size === 0}
                          onClick={onCloseSelected}
                          className="border-rose-500/40 text-rose-200 hover:bg-rose-500/10"
                        >
                          {closing ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : null}
                          Close selected ({selectedPositions.size})
                        </Button>
                      </div>
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
                            <th className="p-2">Close %</th>
                            <th className="p-2" />
                          </tr>
                        </thead>
                        <tbody>
                          {positions.map((p) => {
                            const pl = p.unrealized_pl;
                            const up = pl != null && pl >= 0;
                            return (
                              <tr key={p.symbol} className="border-t border-ramp-grey-800 align-top">
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
                                      up ? (
                                        <TrendingUp className="h-3 w-3" />
                                      ) : (
                                        <TrendingDown className="h-3 w-3" />
                                      )
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
                                  <ClosePercentControl
                                    value={pctFor(p.symbol)}
                                    onChange={(n) =>
                                      setClosePctBySymbol((prev) => ({ ...prev, [p.symbol]: n }))
                                    }
                                    disabled={closing}
                                  />
                                </td>
                                <td className="p-2">
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    className="h-7 text-xs border-rose-500/40 text-rose-200"
                                    disabled={closing}
                                    onClick={() => onCloseOne(p.symbol)}
                                  >
                                    Close
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
                                  !showPl ? 'text-muted-foreground' : up ? 'text-emerald-300' : 'text-rose-300'
                                )}
                              >
                                {showPl ? (
                                  <span className="inline-flex items-center gap-1">
                                    {up ? (
                                      <TrendingUp className="h-3 w-3" />
                                    ) : (
                                      <TrendingDown className="h-3 w-3" />
                                    )}
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
              <CardDescription>Swing (multi-day) or day (intraday). Auto keeps agent choice rules.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {(['swing', 'day', 'auto'] as TradingModeChoice[]).map((m) => (
                <Button
                  key={m}
                  variant={mode === m ? undefined : 'outline'}
                  size="sm"
                  onClick={() => onModeChange(m)}
                  className={cn(mode === m && 'bg-blue-600 hover:bg-blue-500 text-white')}
                >
                  {m}
                </Button>
              ))}
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
                  Options paper execute is not wired yet — analysis runs are research-only.
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <CardTitle className="text-base">Strategies</CardTitle>
                <CardDescription>Core set is selected by default. Risk + PM always run with analysts.</CardDescription>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={selectCore}>
                  Core set
                </Button>
                <Button variant="outline" size="sm" onClick={selectAnalystsOnly}>
                  Defaults
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            {loading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading strategies…
              </div>
            ) : (
              (['analyst', 'risk', 'pm'] as const).map((cat) => (
                <div key={cat}>
                  <div className="text-xs uppercase tracking-wide text-muted-foreground mb-2">{cat}</div>
                  <div className="grid sm:grid-cols-2 gap-2">
                    {(byCategory[cat] || []).map((s) => {
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
              ))
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
                disabled={running || loading}
                className="bg-blue-600 hover:bg-blue-500 text-white min-w-[220px]"
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
                instrument === 'options' && 'opacity-60'
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
                </div>
              </div>
            </label>
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

              {/* KPI strip */}
              {Object.keys(actionCounts).length > 0 && (
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                  {(['buy', 'sell', 'short', 'cover', 'hold'] as const).map((k) => (
                    <div
                      key={k}
                      className={cn(
                        'rounded-lg border px-3 py-2 text-center',
                        actionTone(k)
                      )}
                    >
                      <div className="text-[10px] uppercase tracking-wide opacity-80">{k}</div>
                      <div className="text-lg font-semibold tabular-nums">{actionCounts[k] ?? 0}</div>
                    </div>
                  ))}
                </div>
              )}

              {/* Decision cards */}
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
                            <span className="text-xs text-muted-foreground">
                              qty {d.quantity ?? '—'}
                            </span>
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
                            <td className="p-2 tabular-nums">
                              {String(tr.qty ?? tr.quantity ?? '—')}
                            </td>
                            <td className="p-2">
                              <Badge variant={tr.success ? 'success' : 'destructive'} className="text-[10px]">
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
    </div>
  );
}
