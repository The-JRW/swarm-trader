import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { RecipeHintsResponse } from '@/services/strategies-api';
import { Lightbulb, Loader2, RefreshCw } from 'lucide-react';

interface RecipeHintsPanelProps {
  hints: RecipeHintsResponse | null;
  loading?: boolean;
  applying?: boolean;
  onRefresh: () => void;
  /** Explicit user action — hints never write the recipe on their own. */
  onApply: (tickers: string[]) => void;
  className?: string;
}

const KIND_TONE: Record<string, string> = {
  contested: 'border-amber-500/40 text-amber-200',
  consensus: 'border-emerald-500/40 text-emerald-200',
};

/** D5 — display-only next-recipe suggestions from the last paper run's digest. */
export function RecipeHintsPanel({
  hints,
  loading,
  applying,
  onRefresh,
  onApply,
  className,
}: RecipeHintsPanelProps) {
  const suggested = hints?.suggested_tickers || [];

  return (
    <Card className={cn('border-amber-500/20', className)}>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              <Lightbulb className="h-4 w-4 text-amber-300" />
              Next recipe hints
            </CardTitle>
            <CardDescription>
              Suggestions from the last paper run's conviction digest — contested names first,
              then consensus. Nothing is written until you press Apply.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="secondary">display only</Badge>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={onRefresh}
              disabled={loading}
            >
              {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {suggested.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No hints yet — complete a paper run and the swarm's contested / consensus tickers show
            up here for the next Apply.
          </p>
        ) : (
          <>
            <ul className="space-y-1">
              {(hints?.hints || []).map((h) => (
                <li
                  key={h.ticker}
                  className="flex flex-wrap items-center gap-2 rounded-md border px-2 py-1.5 text-xs"
                >
                  <span className="font-semibold font-mono">{h.ticker}</span>
                  <Badge
                    variant="outline"
                    className={cn('text-[10px] capitalize', KIND_TONE[h.kind] || '')}
                  >
                    {h.kind}
                  </Badge>
                  <span className="text-muted-foreground">{h.reason}</span>
                  {h.in_current_recipe ? (
                    <Badge variant="secondary" className="text-[10px]">
                      already in recipe
                    </Badge>
                  ) : null}
                </li>
              ))}
            </ul>

            {(hints?.excluded || []).length > 0 && (
              <p className="text-xs text-muted-foreground">
                Excluded (risk-rejected, never suggested):{' '}
                <span className="font-mono">
                  {(hints?.excluded || []).map((e) => e.ticker).join(', ')}
                </span>
              </p>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                className="h-8 bg-amber-600 hover:bg-amber-500 text-white"
                disabled={applying}
                onClick={() => onApply(suggested)}
              >
                {applying ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
                Apply {suggested.length} hint{suggested.length === 1 ? '' : 's'} to recipe
              </Button>
              <span className="text-xs text-muted-foreground">
                Sector-aware apply, capped at {hints?.cap ?? 15}
                {hints?.run_id ? ` · from run ${hints.run_id.slice(0, 8)}` : ''}
              </span>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
