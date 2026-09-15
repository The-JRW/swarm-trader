import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { fmtMoney } from '@/components/strategies/format';
import { cn } from '@/lib/utils';
import { HitOps, strategiesApi } from '@/services/strategies-api';
import { Loader2, PlayCircle, RefreshCw, Timer, Turtle, Zap } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

/** G2 Ops-visible amendment — fallback fast-preset labels, used only until
 * the first `getHitOps()` response arrives (which carries the backend's own
 * `fast_path_analyst_ids`/`slow_path_analyst_ids` — the real source of
 * truth). Kept identical to `hit_service.HIT_PRESET_ANALYST_IDS` /
 * `HIT_SLOW_LLM_ANALYST_IDS` so there is never a visible flash of "no
 * analysts" while ops is still loading. */
const FALLBACK_FAST_ANALYSTS = ['technical_analyst', 'market_regime', 'autoresearch', 'sentiment_analyst'];
const FALLBACK_SLOW_ANALYSTS = ['apex', 'news_sentiment_analyst'];

/**
 * F5 — Ops HIT strip: trades today, gross turnover, cost-gate rejects, last
 * pulse. HIT = High-frequency **Intraday Turnover** (paper; minutes-hours
 * holds) — this is explicitly NOT true HFT (no co-location, no LOB
 * imbalance modeling). Read-only counters; polls a persisted counter file,
 * never opens a live WebSocket connection from the browser.
 *
 * G2 (Wave G) Ops-visible amendment — Chrome review found the fast HIT
 * path (default analyst preset, skips the heavy apex/news_sentiment LLM
 * pair) had no Ops/UI copy anywhere, only a backend `fast` field. This card
 * now surfaces: (1) a badge + labeled analyst set for whichever path the
 * last pulse actually ran, and (2) a read-only fast/slow selector + "Run
 * HIT pulse now" button so James can trigger an analysis-only pulse on
 * either path from Ops/Book without touching the API directly. This
 * control never flips `SWARM_HIT_EXECUTE` and never sets `execute_trades`
 * — it always calls `runHitPulse` analysis-only.
 */
export function HitOpsPanel({ className }: { className?: string }) {
  const [ops, setOps] = useState<HitOps | null>(null);
  const [loading, setLoading] = useState(false);
  const [fastSelection, setFastSelection] = useState(true);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

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

  const runPulse = useCallback(async () => {
    setRunning(true);
    setRunError(null);
    try {
      await strategiesApi.runHitPulse({ execute_trades: false, fast: fastSelection });
      await load();
    } catch (e) {
      setRunError(e instanceof Error ? e.message : 'HIT pulse failed to start');
    } finally {
      setRunning(false);
    }
  }, [fastSelection, load]);

  const lastPulse = ops?.last_pulse;
  const latencies = ops?.recent_fill_latencies || [];
  const rejects = ops?.recent_cost_gate_rejects || [];

  // G2 Ops-visible — the analyst path actually used by the last pulse when
  // known; otherwise the server's static default (fast=true), never guessed
  // from the UI's own toggle selection.
  const lastPulseFast = lastPulse?.fast ?? ops?.fast_default ?? true;
  const fastAnalysts = ops?.fast_path_analyst_ids?.length
    ? ops.fast_path_analyst_ids
    : FALLBACK_FAST_ANALYSTS;
  const slowAnalysts = ops?.slow_path_analyst_ids?.length
    ? ops.slow_path_analyst_ids
    : FALLBACK_SLOW_ANALYSTS;
  const lastPulseAnalysts = lastPulse?.analyst_ids?.length
    ? lastPulse.analyst_ids
    : lastPulseFast
      ? fastAnalysts
      : [...fastAnalysts, ...slowAnalysts];

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
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={lastPulseFast ? 'success' : 'warning'} className="gap-1">
              {lastPulseFast ? <Zap className="h-3 w-3" /> : <Turtle className="h-3 w-3" />}
              {lastPulseFast ? 'Fast HIT path' : 'Slow path (opt-in)'}
            </Badge>
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

            {/* G2 Ops-visible amendment — fast vs. slow analyst path, always
                rendered (even with no pulse yet today), plus a read-only
                selector + manual "Run HIT pulse now" trigger. Never touches
                SWARM_HIT_EXECUTE; always calls runHitPulse analysis-only. */}
            <div className="space-y-2 rounded-lg border border-amber-500/20 bg-ramp-grey-800/20 px-3 py-2">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Fast HIT path — analyst set
              </div>
              <p className="text-xs text-muted-foreground">
                {lastPulse ? 'Last pulse ran: ' : 'Default (no pulse yet today): '}
                <span className="font-mono text-primary">{lastPulseAnalysts.join(' + ')}</span>
                {lastPulseFast ? (
                  <> — fast preset only, skips heavy per-ticker LLM calls.</>
                ) : (
                  <>
                    {' '}— includes the slow-path pair (
                    <span className="font-mono">{slowAnalysts.join(' + ')}</span>: one full LLM
                    call per ticker each).
                  </>
                )}
              </p>
              {ops?.fast_path_note ? (
                <p className="text-[11px] text-muted-foreground">{ops.fast_path_note}</p>
              ) : null}

              <div className="flex flex-wrap items-center gap-2 pt-1">
                <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
                  Run controls:
                </span>
                <div className="inline-flex overflow-hidden rounded-md border">
                  <Button
                    type="button"
                    size="sm"
                    variant={fastSelection ? 'default' : 'ghost'}
                    className="h-7 rounded-none text-xs gap-1"
                    onClick={() => setFastSelection(true)}
                  >
                    <Zap className="h-3 w-3" /> Fast (default)
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant={!fastSelection ? 'default' : 'ghost'}
                    className="h-7 rounded-none text-xs gap-1"
                    onClick={() => setFastSelection(false)}
                  >
                    <Turtle className="h-3 w-3" /> Slow (opt-in)
                  </Button>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs gap-1"
                  onClick={() => runPulse()}
                  disabled={running}
                >
                  {running ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <PlayCircle className="h-3 w-3" />
                  )}
                  Run HIT pulse now (analysis-only)
                </Button>
              </div>
              <p className="text-[11px] text-muted-foreground">
                {fastSelection
                  ? `Will run: ${fastAnalysts.join(' + ')}.`
                  : `Will run: ${fastAnalysts.join(' + ')} + ${slowAnalysts.join(' + ')} (slow pair).`}{' '}
                Always analysis-only from this button — never flips SWARM_HIT_EXECUTE.
              </p>
              {runError ? <p className="text-[11px] text-red-400">{runError}</p> : null}
            </div>

            <div className="space-y-1">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Latency observatory — decision→submit→ack→fill (blank when a stage's
                timestamp is unavailable — never fabricated)
              </div>
              {latencies.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No fill timestamps recorded yet — never fabricated.
                </p>
              ) : (
                <ul className="space-y-0.5 max-h-28 overflow-auto font-mono text-xs text-muted-foreground">
                  {latencies.slice(0, 8).map((l, i) => (
                    <li key={`${l.order_id || i}`}>
                      {l.ticker} · submit→fill {l.latency_ms != null ? `${l.latency_ms}ms` : '—'}
                      {l.decision_to_fill_ms != null ? ` · decision→fill ${l.decision_to_fill_ms}ms` : ''}
                    </li>
                  ))}
                </ul>
              )}
              {ops.latency_note ? (
                <p className="text-[11px] text-muted-foreground">{ops.latency_note}</p>
              ) : null}
            </div>

            <div className="space-y-1">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Recent cost-gate rejects (F2 cost/turnover · G3 stale quote)
              </div>
              {rejects.length === 0 ? (
                <p className="text-xs text-muted-foreground">No cost-gate rejects recorded yet.</p>
              ) : (
                <ul className="space-y-0.5 max-h-28 overflow-auto text-xs text-muted-foreground">
                  {rejects.slice(0, 8).map((r, i) => (
                    <li key={`${r.ticker}-${i}`}>
                      <span className="font-mono text-primary">{r.ticker}</span>{' '}
                      {r.rule === 'stale_quote' && r.quote_age_ms != null
                        ? `quote ${Math.round(r.quote_age_ms)}ms stale`
                        : r.round_trip_cost_bps != null
                          ? `${r.round_trip_cost_bps}bps`
                          : ''}{' '}
                      — {r.reason}
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
