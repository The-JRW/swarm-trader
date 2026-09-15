import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { DryRunStreak, strategiesApi } from '@/services/strategies-api';
import { CheckCircle2, Circle, Loader2, RefreshCw, ShieldAlert } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

/**
 * E1 — A2 dry-run streak / exit checklist.
 *
 * Read/record only: progress toward 5 weekday dry-runs + a James/Reviewer
 * ack per docs/AUTOMATION_A1_A2.md. There is intentionally NO control here
 * (or anywhere in the UI) that flips SWARM_MONITOR_DRY_RUN — that stays an
 * Elestio env change made outside the app.
 */
export function DryRunStreakPanel({ className }: { className?: string }) {
  const [streak, setStreak] = useState<DryRunStreak | null>(null);
  const [loading, setLoading] = useState(false);
  const [ackBy, setAckBy] = useState('');
  const [ackNote, setAckNote] = useState('');
  const [acking, setAcking] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setStreak(await strategiesApi.getDryRunStreak());
    } catch {
      setStreak(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const recordAck = async () => {
    setAcking(true);
    try {
      const next = await strategiesApi.ackDryRunStreak(ackBy || undefined, ackNote || undefined);
      setStreak(next);
      toast.success('Ack recorded — does not change SWARM_MONITOR_DRY_RUN');
    } catch (e: any) {
      toast.error(e?.message || 'Failed to record ack');
    } finally {
      setAcking(false);
    }
  };

  const count = streak?.consecutive_weekday_count ?? 0;
  const target = streak?.target ?? 5;
  const acked = Boolean(streak?.ack?.acknowledged);

  return (
    <Card className={cn('border-sky-500/20', className)}>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-sky-300" />
              A2 dry-run exit checklist
            </CardTitle>
            <CardDescription>
              Progress toward 5 weekday dry-runs + a James/Reviewer ack. Streak + summaries
              only — no control here flips SWARM_MONITOR_DRY_RUN.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="secondary">record only</Badge>
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => load()} disabled={loading}>
              {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-1">
          {Array.from({ length: target }).map((_, i) => (
            <span key={i} className="flex items-center">
              {i < count ? (
                <CheckCircle2 className="h-5 w-5 text-emerald-400" />
              ) : (
                <Circle className="h-5 w-5 text-muted-foreground/40" />
              )}
            </span>
          ))}
          <span className="ml-2 text-sm tabular-nums text-muted-foreground">
            {count}/{target} consecutive weekday dry-runs
          </span>
        </div>

        {streak?.last_date && (
          <p className="text-xs text-muted-foreground">
            Last recorded: {streak.last_weekday_label || ''} {streak.last_date}
            {' · '}
            result: <span className="capitalize">{streak.last_result || '—'}</span>
          </p>
        )}

        <div className="rounded-lg border px-3 py-3 space-y-2">
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            James / Reviewer ack
          </div>
          {acked ? (
            <div className="text-sm text-emerald-300">
              Acked by <span className="font-medium">{streak?.ack?.by}</span>
              {streak?.ack?.at ? ` · ${new Date(streak.ack.at).toLocaleString()}` : ''}
              {streak?.ack?.note ? <p className="text-xs text-muted-foreground mt-1">{streak.ack.note}</p> : null}
            </div>
          ) : (
            <div className="space-y-2">
              <Input
                value={ackBy}
                onChange={(e) => setAckBy(e.target.value)}
                placeholder="Who is acking (James / Reviewer)"
                className="h-8 text-sm"
              />
              <Input
                value={ackNote}
                onChange={(e) => setAckNote(e.target.value)}
                placeholder="Optional note"
                className="h-8 text-sm"
              />
              <Button
                size="sm"
                className="h-8 bg-sky-600 hover:bg-sky-500 text-white"
                disabled={acking}
                onClick={recordAck}
              >
                {acking ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
                Record ack
              </Button>
            </div>
          )}
          <p className="text-[11px] text-muted-foreground">
            This only records a note for the exit checklist. Setting
            SWARM_MONITOR_DRY_RUN=false still requires an operator to change the Elestio
            environment directly.
          </p>
        </div>

        <div className="space-y-1">
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Last would-fire summaries
          </div>
          {!streak?.summaries?.length ? (
            <p className="text-xs text-muted-foreground">No dry-run summaries recorded yet.</p>
          ) : (
            <ul className="space-y-1 max-h-40 overflow-auto">
              {streak.summaries.slice(0, 10).map((s, i) => (
                <li key={`${s.timestamp}-${i}`} className="text-xs font-mono text-muted-foreground truncate">
                  {s.timestamp ? new Date(s.timestamp).toLocaleString() : '—'} · {s.trading_mode || '—'} ·{' '}
                  {s.would_fire_count ?? 0} would-fire
                  {s.would_fire_count ? ` (${(s.would_fire || []).map((a) => a.symbol).join(', ')})` : ''}
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
