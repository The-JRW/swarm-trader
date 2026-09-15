import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { PerformanceSnapshotRow, strategiesApi } from '@/services/strategies-api';
import { Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';

function fmtMoney(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
}

function fmtPct(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—';
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toFixed(2)}%`;
}

interface PerformanceSnapshotsDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * E2 — Details drawer listing recent real performance snapshots.
 *
 * α vs SPY is only ever shown when the underlying snapshot actually has a
 * real spy_daily_pct — never a fabricated zero.
 */
export function PerformanceSnapshotsDrawer({ open, onOpenChange }: PerformanceSnapshotsDrawerProps) {
  const [rows, setRows] = useState<PerformanceSnapshotRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    strategiesApi
      .getPerformanceSnapshots(30)
      .then((res) => {
        if (cancelled) return;
        setRows(res.snapshots || []);
        setMessage(res.available ? null : res.message || 'Snapshots unavailable');
      })
      .catch((e) => {
        if (cancelled) return;
        setRows([]);
        setMessage(e?.message || 'Could not load snapshots');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="sm:max-w-lg w-full overflow-auto">
        <SheetHeader>
          <SheetTitle>Recent performance snapshots</SheetTitle>
          <SheetDescription>
            Real equity/cash + SPY/QQQ snapshots from the daily cron (B4/E2). α vs SPY only
            appears when the underlying snapshot has real benchmark data — never a fake zero.
          </SheetDescription>
        </SheetHeader>
        <div className="mt-4">
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-6 justify-center">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading snapshots…
            </div>
          ) : rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {message || 'No snapshots recorded yet — the daily performance-snapshot cron writes one per day.'}
            </p>
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full text-sm">
                <thead className="bg-ramp-grey-800/50 text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="p-2">Date</th>
                    <th className="p-2">Equity</th>
                    <th className="p-2">Day P/L</th>
                    <th className="p-2">SPY day</th>
                    <th className="p-2">α vs SPY</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((s, i) => (
                    <tr key={`${s.date}-${i}`} className="border-t border-ramp-grey-800">
                      <td className="p-2 whitespace-nowrap">{s.date || '—'}</td>
                      <td className="p-2 tabular-nums">{fmtMoney(s.equity)}</td>
                      <td className="p-2 tabular-nums">{fmtPct(s.daily_pnl_pct)}</td>
                      <td className="p-2 tabular-nums">{fmtPct(s.spy_daily_pct)}</td>
                      <td className="p-2 tabular-nums">
                        {s.alpha_vs_spy_daily != null ? fmtPct(s.alpha_vs_spy_daily) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
