import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { fmtMoney } from '@/components/strategies/format';
import { cn } from '@/lib/utils';
import { HitOps, strategiesApi } from '@/services/strategies-api';
import { Loader2, RefreshCw, Timer } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

/**
 * F5 — Ops HIT strip: trades today, gross turnover, cost-gate rejects, last
 * pulse. HIT = High-frequency **Intraday Turnover** (paper; minutes-hours
 * holds) — this is explicitly NOT true HFT (no co-location, no LOB
 * imbalance modeling). Read-only; polls a persisted counter file, never
 * opens a live WebSocket connection from the browser.
 */
export function HitOpsPanel({ className }: { className?: string }) {
  const [ops, setOps] = useState<HitOps | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setOps(await strategiesApi.getHitOps());
    } catch {
      setOps(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const lastPulse = ops?.last_pulse;
  const latencies = ops?.recent_fill_latencies || [];
  const rejects = ops?.recent_cost_gate_rejects || [];

  return (
    <Card className={cn('border-amber-500/20', className)}>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              <Timer className="h-4 w-4 text-amber-300" />
              HIT ops strip
            </CardTitle>
            <CardDescription>
              High-frequency <strong>Intraday Turnover</strong> — paper only, minutes-hours
              holds. Not true HFT (no co-location, no LOB imbalance modeling).
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={ops?.hit_execute_env_allows ? 'warning' : 'success'}>
              HIT execute env: {ops?.hit_execute_env_allows ? 'allows' : 'blocked (safe)'}
            </Badge>
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => load()} disabled={loading}>
              {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {!ops ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading HIT ops…
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {[
                { label: 'Trades today', value: String(ops.trades_today ?? 0) },
                { label: 'Gross turnover', value: fmtMoney(ops.turnover_today) },
                { label: 'Cost-gate rejects', value: String(ops.cost_gate_rejects_today ?? 0) },
                { label: 'Pulses today', value: String(ops.pulses_today ?? 0) },
              ].map((k) => (
                <div key={k.label} className="rounded-lg border bg-ramp-grey-800/30 px-3 py-2">
                  <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                    {k.label}
                  </div>
                  <div className="text-sm font-semibold tabular-nums mt-0.5">{k.value}</div>
                </div>
              ))}
            </div>

            <div className="space-y-1">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Last pulse
              </div>
              {!lastPulse ? (
                <p className="text-xs text-muted-foreground">No HIT pulse yet today.</p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  {lastPulse.at ? new Date(lastPulse.at).toLocaleString() : '—'} · run{' '}
                  <span className="font-mono">{(lastPulse.run_id || '').slice(0, 8)}</span> ·{' '}
                  {lastPulse.execute_effective ? 'executed' : 'analysis-only'} · would-fire{' '}
                  {lastPulse.would_fire_count ?? 0} · filled {lastPulse.trades_filled ?? 0} ·
                  cost-gate rejects {lastPulse.cost_gate_rejects ?? 0}
                </p>
              )}
            </div>

            <div className="space-y-1">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Recent fill latency (when Alpaca returns timestamps — blank otherwise)
              </div>
              {latencies.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No fill timestamps recorded yet — never fabricated.
                </p>
              ) : (
                <ul className="space-y-0.5 max-h-28 overflow-auto font-mono text-xs text-muted-foreground">
                  {latencies.slice(0, 8).map((l, i) => (
                    <li key={`${l.order_id || i}`}>
                      {l.ticker} · {l.latency_ms != null ? `${l.latency_ms}ms` : '—'}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="space-y-1">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Recent cost-gate rejects (F2)
              </div>
              {rejects.length === 0 ? (
                <p className="text-xs text-muted-foreground">No cost-gate rejects recorded yet.</p>
              ) : (
                <ul className="space-y-0.5 max-h-28 overflow-auto text-xs text-muted-foreground">
                  {rejects.slice(0, 8).map((r, i) => (
                    <li key={`${r.ticker}-${i}`}>
                      <span className="font-mono text-primary">{r.ticker}</span>{' '}
                      {r.round_trip_cost_bps != null ? `${r.round_trip_cost_bps}bps` : ''} — {r.reason}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <p className="text-[11px] text-muted-foreground">{ops.note}</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
