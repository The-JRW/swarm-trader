import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { RedeploySuggestion } from '@/services/strategies-api';
import { Loader2, Sprout } from 'lucide-react';

interface RedeployBannerProps {
  suggestion: RedeploySuggestion | null;
  scanLoading?: boolean;
  onScan: () => void;
  className?: string;
}

/**
 * E5 — Empty-book redeploy assist.
 *
 * Display-only nudge shown on Run/Ops when the book has zero positions and
 * cash sits above a sensible threshold. Suggests the existing
 * Scan → Apply → Launch **analysis** path; execute stays dual-gated off by
 * default regardless — this banner never starts anything by itself beyond
 * the same "Scan market" action already on the Ops card.
 */
export function RedeployBanner({ suggestion, scanLoading, onScan, className }: RedeployBannerProps) {
  if (!suggestion?.available || !suggestion.suggest) return null;

  return (
    <div
      className={cn(
        'rounded-md border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100 flex flex-wrap items-center justify-between gap-3',
        className
      )}
      role="status"
    >
      <div className="flex items-start gap-2">
        <Sprout className="h-4 w-4 mt-0.5 shrink-0" />
        <span>{suggestion.message}</span>
      </div>
      <Button
        size="sm"
        variant="outline"
        className="h-8 border-emerald-500/40 text-emerald-100 hover:bg-emerald-500/20"
        onClick={onScan}
        disabled={scanLoading}
      >
        {scanLoading ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
        Scan market
      </Button>
    </div>
  );
}
