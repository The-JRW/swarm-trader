import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { AutoResearchQueueResponse, strategiesApi } from '@/services/strategies-api';
import { FlaskConical, Loader2, RefreshCw, ThumbsDown, ThumbsUp, Undo2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

/**
 * E6 — AutoResearch review queue (stub).
 *
 * Read-only view over `autoresearch/experiments/{log,runs}.jsonl` — the
 * existing offline evolution loop's own artifacts. Approve/reject here is
 * **display/UX only**: it records a note for the record and never writes
 * `autoresearch/strategy.py` or any production config, and never triggers
 * `evolve.py` or a backtest.
 */
export function AutoResearchReviewPanel({ className }: { className?: string }) {
  const [data, setData] = useState<AutoResearchQueueResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [deciding, setDeciding] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await strategiesApi.getAutoResearchQueue(20));
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const decide = async (experimentId: string, decision: 'approved' | 'rejected' | 'pending') => {
    setDeciding(experimentId);
    try {
      await strategiesApi.reviewAutoResearchExperiment(experimentId, decision);
      toast.success(
        decision === 'pending'
          ? 'Review cleared — no config was touched'
          : `Marked ${decision} — display only, no config was written`
      );
      await load();
    } catch (e: any) {
      toast.error(e?.message || 'Failed to record review');
    } finally {
      setDeciding(null);
    }
  };

  const experiments = data?.experiments || [];
  const runs = data?.recent_runs || [];

  return (
    <Card className={cn('border-fuchsia-500/20', className)}>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              <FlaskConical className="h-4 w-4 text-fuchsia-300" />
              AutoResearch review queue
            </CardTitle>
            <CardDescription>
              Recent fitness/experiments from the offline evolution loop. Approve/reject is
              display only — it never writes strategy.py or any production config.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="secondary">display / UX only</Badge>
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => load()} disabled={loading}>
              {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {runs.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Recent evolution runs
            </div>
            <ul className="text-xs text-muted-foreground space-y-0.5">
              {runs.slice(0, 5).map((r) => (
                <li key={r.run_id} className="font-mono truncate">
                  {r.timestamp_end ? new Date(r.timestamp_end).toLocaleDateString() : '—'} · {r.mode || '—'} ·{' '}
                  best {r.best_fitness?.toFixed?.(2) ?? '—'} (baseline {r.baseline_fitness?.toFixed?.(2) ?? '—'}) ·{' '}
                  kept {r.keep_count ?? 0}/{r.total_experiments ?? 0}
                </li>
              ))}
            </ul>
          </div>
        )}

        {experiments.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No experiments found under autoresearch/experiments/ yet.
          </p>
        ) : (
          <ul className="space-y-2 max-h-96 overflow-auto">
            {experiments.map((exp) => {
              const decision = exp.review?.decision;
              return (
                <li key={exp.experiment_id} className="rounded-lg border px-3 py-2 space-y-1.5">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="text-sm text-primary line-clamp-2">{exp.hypothesis || '—'}</div>
                      <div className="text-xs text-muted-foreground mt-0.5">
                        {exp.timestamp ? new Date(exp.timestamp).toLocaleString() : '—'} · {exp.mode || '—'} ·{' '}
                        <span className="font-mono">{exp.experiment_id.slice(0, 8)}</span>
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5 shrink-0">
                      <Badge variant={exp.kept ? 'success' : 'secondary'} className="text-[10px]">
                        {exp.kept ? 'kept by evolve.py' : 'reverted'}
                      </Badge>
                      {exp.fitness_score != null && (
                        <Badge variant="outline" className="text-[10px] tabular-nums">
                          fitness {exp.fitness_score.toFixed(2)}
                        </Badge>
                      )}
                      {decision && (
                        <Badge
                          variant={decision === 'approved' ? 'success' : 'destructive'}
                          className="text-[10px] capitalize"
                        >
                          {decision}
                        </Badge>
                      )}
                    </div>
                  </div>

                  {exp.error && <p className="text-xs text-red-300">{exp.error}</p>}

                  <div className="flex flex-wrap items-center gap-1.5">
                    <Button
                      size="sm"
                      variant="outline"
                      className={cn('h-7 text-xs', decision === 'approved' && 'border-emerald-500/50 text-emerald-300')}
                      disabled={deciding === exp.experiment_id}
                      onClick={() => decide(exp.experiment_id, 'approved')}
                    >
                      <ThumbsUp className="h-3 w-3 mr-1" />
                      Approve
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className={cn('h-7 text-xs', decision === 'rejected' && 'border-rose-500/50 text-rose-300')}
                      disabled={deciding === exp.experiment_id}
                      onClick={() => decide(exp.experiment_id, 'rejected')}
                    >
                      <ThumbsDown className="h-3 w-3 mr-1" />
                      Reject
                    </Button>
                    {decision && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 text-xs"
                        disabled={deciding === exp.experiment_id}
                        onClick={() => decide(exp.experiment_id, 'pending')}
                      >
                        <Undo2 className="h-3 w-3 mr-1" />
                        Clear
                      </Button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        <p className="text-[11px] text-muted-foreground">{data?.note}</p>
      </CardContent>
    </Card>
  );
}
