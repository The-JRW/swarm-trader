import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { PortfolioGlance, strategiesApi } from '@/services/strategies-api';
import { ArrowRight, Landmark } from 'lucide-react';
import { useEffect, useState } from 'react';

interface OnboardingStripProps {
  onOpenStrategies: () => void;
  className?: string;
}

function formatMoney(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
}

export function OnboardingStrip({ onOpenStrategies, className }: OnboardingStripProps) {
  const [glance, setGlance] = useState<PortfolioGlance | null>(null);

  useEffect(() => {
    let cancelled = false;
    strategiesApi
      .portfolioGlance()
      .then((g) => {
        if (!cancelled) setGlance(g);
      })
      .catch(() => {
        if (!cancelled) setGlance({ available: false, paper: true, message: 'Portfolio API unavailable' });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div
      className={cn(
        'w-full max-w-xl mx-auto rounded-xl border border-blue-500/30 bg-blue-500/5 px-5 py-4 text-left space-y-3',
        className
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="success">Paper trading — no real money</Badge>
        <Badge variant="outline">Easy path</Badge>
      </div>
      <div className="text-sm text-primary">
        Start with <span className="font-semibold">Strategies</span>: the <span className="font-semibold">Run</span>{' '}
        pane picks swing/day mode, agents, and tickers for a paper analysis; the{' '}
        <span className="font-semibold">Book</span> pane holds positions, closes, and orders. Flow graphs
        stay under Advanced.
      </div>
      {glance?.available && (
        <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          <Landmark className="h-3.5 w-3.5" />
          <span>Equity {formatMoney(glance.equity)}</span>
          <span>Cash {formatMoney(glance.cash)}</span>
          <span>{glance.positions_count ?? 0} positions</span>
        </div>
      )}
      {!glance?.available && glance?.message && (
        <div className="text-xs text-muted-foreground">{glance.message}</div>
      )}
      <Button size="sm" onClick={onOpenStrategies} className="bg-blue-600 hover:bg-blue-500 text-white">
        Open Strategies
        <ArrowRight className="h-4 w-4 ml-1" />
      </Button>
    </div>
  );
}
