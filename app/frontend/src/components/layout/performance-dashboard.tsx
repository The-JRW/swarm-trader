import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import {
  PeriodPerformanceMetric,
  PortfolioPerformance,
  strategiesApi,
} from '@/services/strategies-api';
import { Loader2, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

function fmtMoney(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  });
}

function fmtSignedMoney(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—';
  const sign = n > 0 ? '+' : '';
  return `${sign}${fmtMoney(n)}`;
}

function fmtPct(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—';
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toFixed(2)}%`;
}

function toneFor(metric?: PeriodPerformanceMetric | null) {
  if (!metric?.available || metric.pnl == null) return 'text-muted-foreground';
  if (metric.pnl > 0) return 'text-emerald-400';
  if (metric.pnl < 0) return 'text-rose-400';
  return 'text-muted-foreground';
}

function MetricCell({
  label,
  metric,
}: {
  label: string;
  metric?: PeriodPerformanceMetric | null;
}) {
  const available = metric?.available;
  return (
    <div className="flex flex-col min-w-[88px] px-2 py-0.5">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground/80">{label}</span>
      <span className={cn('text-xs font-medium tabular-nums leading-tight', toneFor(metric))}>
        {available ? fmtSignedMoney(metric?.pnl) : '—'}
      </span>
      <span className={cn('text-[10px] tabular-nums leading-tight', toneFor(metric))}>
        {available ? fmtPct(metric?.pnl_pct) : '—'}
      </span>
    </div>
  );
}

function fmtAsOf(iso?: string | null) {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return null;
  }
}

/** Prefer top-level spy_alpha, else first period that has real spy_alpha (never invent). */
function resolveSpyAlpha(data: PortfolioPerformance | null): number | null {
  if (!data?.available) return null;
  if (data.spy_alpha != null && !Number.isNaN(data.spy_alpha)) return data.spy_alpha;
  for (const m of [data.week, data.mtd, data.day, data.quarter, data.ytd]) {
    if (m?.spy_alpha != null && !Number.isNaN(m.spy_alpha)) return m.spy_alpha;
  }
  return null;
}

export function PerformanceDashboard({ className }: { className?: string }) {
  const [data, setData] = useState<PortfolioPerformance | null>(null);
  const [loading, setLoading] = useState(true);
  const [clientAsOf, setClientAsOf] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const perf = await strategiesApi.portfolioPerformance();
      setData(perf);
      if (perf.available) {
        setClientAsOf(perf.as_of || new Date().toISOString());
      }
    } catch {
      setData({
        available: false,
        paper: true,
        message: 'Performance unavailable',
        day: { available: false },
        week: { available: false },
        mtd: { available: false },
        quarter: { available: false },
        ytd: { available: false },
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), 60_000);
    return () => window.clearInterval(id);
  }, [load]);

  const dayUp = (data?.day?.pnl ?? 0) > 0;
  const dayDown = (data?.day?.pnl ?? 0) < 0;
  const asOfLabel = fmtAsOf(data?.as_of || clientAsOf);
  const spyAlpha = resolveSpyAlpha(data);

  return (
    <div
      className={cn(
        'flex items-center gap-1 overflow-x-auto scrollbar-thin max-w-[min(100vw-220px,920px)]',
        className
      )}
      aria-label="Paper portfolio performance"
    >
      <div className="flex items-center gap-1.5 px-2 py-0.5 border-r border-ramp-grey-700 mr-1 shrink-0">
        <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Equity</span>
        <span className="text-sm font-semibold tabular-nums text-foreground">
          {data?.available ? fmtMoney(data.equity) : '—'}
        </span>
        {data?.available && data.day?.available && (
          dayUp ? (
            <TrendingUp size={14} className="text-emerald-400" />
          ) : dayDown ? (
            <TrendingDown size={14} className="text-rose-400" />
          ) : null
        )}
        {data?.paper && (
          <span className="text-[9px] px-1 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30">
            PAPER
          </span>
        )}
      </div>

      <MetricCell label="Day" metric={data?.day} />
      <MetricCell label="Week" metric={data?.week} />
      <MetricCell label="MTD" metric={data?.mtd} />
      <MetricCell label="Quarter" metric={data?.quarter} />
      <MetricCell label="YTD" metric={data?.ytd} />

      {spyAlpha != null && (
        <div className="flex flex-col min-w-[72px] px-2 py-0.5 border-l border-ramp-grey-700">
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground/80">α SPY</span>
          <span
            className={cn(
              'text-xs font-medium tabular-nums',
              spyAlpha > 0 ? 'text-emerald-400' : spyAlpha < 0 ? 'text-rose-400' : 'text-muted-foreground'
            )}
          >
            {fmtPct(spyAlpha)}
          </span>
        </div>
      )}

      {asOfLabel && data?.available && (
        <span
          className="text-[10px] text-muted-foreground/80 whitespace-nowrap px-1 shrink-0"
          title={data.as_of || clientAsOf || undefined}
        >
          as of {asOfLabel}
        </span>
      )}

      {data?.snapshot_as_of && (
        <span
          className="text-[10px] text-muted-foreground/70 whitespace-nowrap px-1 shrink-0"
          title={`Last performance snapshot: ${data.snapshot_as_of}`}
        >
          snap {fmtAsOf(data.snapshot_as_of) || data.snapshot_as_of}
        </span>
      )}

      <button
        type="button"
        className="text-[10px] text-muted-foreground/60 px-1 shrink-0 cursor-default"
        title={
          data?.spy_alpha != null
            ? `α vs SPY from real snapshots: ${data.spy_alpha}`
            : 'α vs SPY shown only when real snapshot/benchmark data exists'
        }
        disabled
      >
        Details
      </button>

      <Button
        variant="ghost"
        size="sm"
        className="h-7 w-7 p-0 shrink-0 text-muted-foreground hover:text-foreground"
        onClick={() => void load()}
        disabled={loading}
        aria-label="Refresh performance"
        title="Refresh performance"
      >
        {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
      </Button>

      {!data?.available && data?.message && (
        <span className="text-[10px] text-muted-foreground truncate max-w-[160px]" title={data.message}>
          {data.message}
        </span>
      )}
    </div>
  );
}
