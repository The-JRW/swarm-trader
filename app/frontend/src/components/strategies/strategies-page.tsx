import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import {
  PaperRunDecision,
  PaperRunStatusResponse,
  Strategy,
  strategiesApi,
} from '@/services/strategies-api';
import { Loader2, Play, RefreshCw, Shield } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

type TradingModeChoice = 'swing' | 'day' | 'auto';

const TERMINAL = new Set(['complete', 'error', 'fail_closed']);

export function StrategiesPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [mode, setMode] = useState<TradingModeChoice>('swing');
  const [tickers, setTickers] = useState('NVDA, AAPL, MSFT');
  const [serverKeys, setServerKeys] = useState(false);
  const [alpacaMode, setAlpacaMode] = useState('paper');
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [run, setRun] = useState<PaperRunStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

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
  }, [load]);

  // Poll active run
  useEffect(() => {
    if (!run?.run_id || TERMINAL.has(run.status)) return;
    const id = setInterval(async () => {
      try {
        const next = await strategiesApi.getRun(run.run_id);
        setRun(next);
        if (TERMINAL.has(next.status)) {
          setRunning(false);
          if (next.status === 'complete') toast.success('Paper analysis complete');
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
  }, [run?.run_id, run?.status]);

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

    setRunning(true);
    setRun(null);
    try {
      const created = await strategiesApi.startPaperRun({
        tickers: parsed,
        strategy_ids: Array.from(selected),
        mode,
      });
      const status = await strategiesApi.getRun(created.run_id);
      setRun(status);
      toast('Paper analysis started', { description: created.run_id.slice(0, 8) });
    } catch (e: any) {
      setRunning(false);
      setError(e?.message || 'Failed to start paper run');
      toast.error(e?.message || 'Failed to start paper run');
    }
  };

  const decisions: PaperRunDecision[] = run?.summary?.decisions || [];

  return (
    <div className="h-full w-full overflow-auto bg-panel">
      <div className="max-w-5xl mx-auto p-6 space-y-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-primary">Strategies</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Easy paper analysis — pick mode, strategies, and tickers. No CLI required.
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
            <Button variant="ghost" size="sm" onClick={load} disabled={loading}>
              <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
            </Button>
          </div>
        </div>

        {error && (
          <div className="rounded-md border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {error}
          </div>
        )}

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
            <CardTitle className="text-base">Tickers</CardTitle>
            <CardDescription>Comma-separated, max 20. Example: NVDA, AAPL, MSFT</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col sm:flex-row gap-3">
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
              className="bg-blue-600 hover:bg-blue-500 text-white min-w-[200px]"
            >
              {running ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Running…
                </>
              ) : (
                <>
                  <Play className="h-4 w-4 mr-2" />
                  Run paper analysis
                </>
              )}
            </Button>
          </CardContent>
        </Card>

        {run && (
          <Card>
            <CardHeader className="pb-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle className="text-base">Run status</CardTitle>
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
              <CardDescription className="font-mono text-xs">{run.run_id}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {run.error && (
                <div className="text-sm text-red-300 whitespace-pre-wrap">{run.error}</div>
              )}
              {run.summary?.action_counts && (
                <div className="flex flex-wrap gap-2 text-xs">
                  {Object.entries(run.summary.action_counts).map(([k, v]) => (
                    <Badge key={k} variant="outline">
                      {k}: {v}
                    </Badge>
                  ))}
                </div>
              )}
              {decisions.length > 0 && (
                <div className="overflow-x-auto rounded-md border">
                  <table className="w-full text-sm">
                    <thead className="bg-ramp-grey-800/50 text-left text-xs text-muted-foreground">
                      <tr>
                        <th className="p-2">Ticker</th>
                        <th className="p-2">Action</th>
                        <th className="p-2">Qty</th>
                        <th className="p-2">Conf</th>
                        <th className="p-2">Reasoning</th>
                      </tr>
                    </thead>
                    <tbody>
                      {decisions.map((d) => (
                        <tr key={d.ticker} className="border-t border-ramp-grey-800">
                          <td className="p-2 font-medium">{d.ticker}</td>
                          <td className="p-2 uppercase">{d.action}</td>
                          <td className="p-2">{d.quantity ?? '—'}</td>
                          <td className="p-2">{d.confidence != null ? `${Number(d.confidence).toFixed(0)}%` : '—'}</td>
                          <td className="p-2 text-muted-foreground max-w-md truncate" title={d.reasoning}>
                            {d.reasoning || '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {!run.error && decisions.length === 0 && !TERMINAL.has(run.status) && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
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
