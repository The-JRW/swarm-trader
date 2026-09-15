import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { AutomationOpsStatus, DurableRunSummary } from '@/services/strategies-api';
import { Loader2, RefreshCw } from 'lucide-react';

interface BookRecordsProps {
  runs: DurableRunSummary[];
  opsStatus: AutomationOpsStatus | null;
  opsLoading: boolean;
  onRefresh: () => void;
  onViewRun: (run: { run_id: string }) => void;
}

/** D1 — the Book pane's records: run history plus automation/monitor receipts. */
export function BookRecords({ runs, opsStatus, opsLoading, onRefresh, onViewRun }: BookRecordsProps) {
  return (
    <>
      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle className="text-base">Recent paper runs</CardTitle>
              <CardDescription>
                Durable history (last 50 on disk). Single-replica — not shared across
                multi-replica deploys.
              </CardDescription>
            </div>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={onRefresh}
              disabled={opsLoading}
            >
              {opsLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
              <span className="ml-1">Refresh</span>
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {runs.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No paper runs recorded yet. Complete a Strategies or cron run to populate history.
            </p>
          ) : (
            <ul className="space-y-2">
              {runs.map((h) => (
                <li
                  key={h.run_id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2"
                >
                  <div className="min-w-0">
                    <div className="text-sm font-medium truncate">
                      {(h.tickers || []).slice(0, 5).join(', ') || '—'}
                      {(h.tickers || []).length > 5 ? ` +${(h.tickers || []).length - 5}` : ''}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {new Date(h.started_at || h.created_at || '').toLocaleString(undefined, {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}{' '}
                      · {h.mode} · {h.instrument || 'stocks'} ·{' '}
                      <span className="font-mono">{h.run_id.slice(0, 8)}</span>
                      {h.conviction_digest
                        ? ` · Δ${h.conviction_digest.consensus_count || 0}/?${h.conviction_digest.contested_count || 0}/⛔${h.conviction_digest.risk_rejected_count || 0}`
                        : ''}
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
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs"
                      onClick={() => onViewRun(h)}
                    >
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
          <CardTitle className="text-base">Automation records</CardTitle>
          <CardDescription>
            Last conviction digest, last cron paper-run, and last monitor actions. Read-only;
            paper-only.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="rounded-lg border px-3 py-2 space-y-1">
            <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Last conviction digest
            </div>
            {opsStatus?.last_conviction_digest ? (
              <div className="text-xs text-muted-foreground space-y-1">
                <div>
                  consensus {(opsStatus.last_conviction_digest.consensus || []).length}
                  {' · '}contested {(opsStatus.last_conviction_digest.contested || []).length}
                  {' · '}risk-rejected {(opsStatus.last_conviction_digest.risk_rejected || []).length}
                  {opsStatus.last_conviction_digest_meta?.run_id
                    ? ` · run ${opsStatus.last_conviction_digest_meta.run_id.slice(0, 8)}`
                    : ''}
                </div>
                <ul className="space-y-0.5 max-h-28 overflow-auto font-mono">
                  {(opsStatus.last_conviction_digest.consensus || []).slice(0, 6).map((c) => (
                    <li key={`c-${c.ticker}`}>
                      ✓ {c.ticker} {c.direction} ({c.agree}/{c.total})
                    </li>
                  ))}
                  {(opsStatus.last_conviction_digest.contested || []).slice(0, 4).map((c) => (
                    <li key={`x-${c.ticker}`}>
                      ? {c.ticker} bull {c.bullish} / bear {c.bearish}
                    </li>
                  ))}
                  {(opsStatus.last_conviction_digest.risk_rejected || []).slice(0, 4).map((c) => (
                    <li key={`r-${c.ticker}`}>
                      ⛔ {c.ticker} — {c.reason}
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">No digest yet — complete a paper run.</p>
            )}
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
                  {opsStatus.last_monitor.trading_mode ? ` · ${opsStatus.last_monitor.trading_mode}` : ''}
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
    </>
  );
}
