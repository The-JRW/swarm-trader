import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { SessionDigest } from '@/services/strategies-api';
import { LayoutList, Loader2, RefreshCw } from 'lucide-react';

interface SessionDigestPanelProps {
  digests: SessionDigest[];
  loading: boolean;
  onRefresh: () => void;
  /** Deep-link — reuses the Book pane's existing run viewer. */
  onViewRun: (runId: string) => void;
  className?: string;
}

/**
 * E3 — Session digest center.
 *
 * Each row is built from real run fields only (action_counts, decision
 * count, conviction digest counts, trade_results filled/blocked) — no
 * invented scores. Deep-links back into Book run history.
 */
export function SessionDigestPanel({
  digests,
  loading,
  onRefresh,
  onViewRun,
  className,
}: SessionDigestPanelProps) {
  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              <LayoutList className="h-4 w-4 text-indigo-300" />
              Session digest center
            </CardTitle>
            <CardDescription>
              Durable digest after every paper run (UI or cron) — real fields only, no
              invented scores.
            </CardDescription>
          </div>
          <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onRefresh} disabled={loading}>
            {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            <span className="ml-1">Refresh</span>
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {digests.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No session digests yet — complete a paper run to populate this list.
          </p>
        ) : (
          <ul className="space-y-2">
            {digests.map((d) => (
              <li key={d.run_id} className="rounded-lg border px-3 py-2 space-y-1">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-sm font-medium truncate">
                      {(d.tickers || []).slice(0, 5).join(', ') || '—'}
                      {(d.tickers || []).length > 5 ? ` +${(d.tickers || []).length - 5}` : ''}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {d.timestamp ? new Date(d.timestamp).toLocaleString() : '—'} · {d.mode || '—'} ·{' '}
                      <span className="font-mono">{d.run_id.slice(0, 8)}</span>
                    </div>
                  </div>
                  <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => onViewRun(d.run_id)}>
                    View
                  </Button>
                </div>
                <div className="flex flex-wrap gap-1.5 text-[11px]">
                  <Badge variant="outline">decisions {d.decision_count ?? 0}</Badge>
                  {Object.entries(d.action_counts || {}).map(([k, v]) =>
                    v ? (
                      <Badge key={k} variant="secondary" className="capitalize">
                        {k} {v}
                      </Badge>
                    ) : null
                  )}
                  <Badge variant="success">consensus {d.conviction?.consensus_count ?? 0}</Badge>
                  <Badge variant="warning">contested {d.conviction?.contested_count ?? 0}</Badge>
                  <Badge variant="destructive">risk-rejected {d.conviction?.risk_rejected_count ?? 0}</Badge>
                  {d.trade_results && d.trade_results.total > 0 && (
                    <>
                      <Badge variant="success">filled {d.trade_results.filled}</Badge>
                      {d.trade_results.blocked > 0 && (
                        <Badge variant="destructive">blocked {d.trade_results.blocked}</Badge>
                      )}
                    </>
                  )}
                </div>
                {d.execute_blocked_reason && (
                  <p className="text-[11px] text-amber-200/90">{d.execute_blocked_reason}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
