import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { fmtCapPct } from '@/components/strategies/format';
import { cn } from '@/lib/utils';
import { RiskPolicy, strategiesApi } from '@/services/strategies-api';
import { Loader2, RefreshCw, ShieldCheck } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

interface RiskPolicyPanelProps {
  /** swing | day | auto — the panel resolves auto server-side. */
  mode?: string;
  className?: string;
}

/**
 * D2 — read-only glance at the hard risk caps enforced by risk_manager.
 * There is no write path here: caps are rendered from server config only.
 */
export function RiskPolicyPanel({ mode, className }: RiskPolicyPanelProps) {
  const [policy, setPolicy] = useState<RiskPolicy | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPolicy(await strategiesApi.getRiskPolicy(mode));
    } catch (e: any) {
      setError(e?.message || 'Risk policy unavailable');
    } finally {
      setLoading(false);
    }
  }, [mode]);

  useEffect(() => {
    load();
  }, [load]);

  const caps = policy?.caps;

  return (
    <Card className={cn('border-emerald-500/20', className)}>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-emerald-400" />
              Risk policy
            </CardTitle>
            <CardDescription>
              Hard caps enforced in code by the Risk Manager. Display only — no LLM or UI
              override, and nothing here widens risk.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="secondary">read-only</Badge>
            {policy?.mode ? (
              <Badge variant="outline" className="capitalize">
                {policy.mode}
              </Badge>
            ) : null}
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={() => load()}
              disabled={loading}
            >
              {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {error ? (
          <p className="text-sm text-muted-foreground">{error}</p>
        ) : !policy ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading risk caps…
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {[
                { label: 'Max position', value: fmtCapPct(caps?.max_position_pct) },
                { label: 'Max sector', value: fmtCapPct(caps?.max_sector_pct) },
                { label: 'Min cash', value: fmtCapPct(caps?.min_cash_pct) },
                { label: 'Stop loss', value: fmtCapPct(caps?.stop_loss_pct) },
                { label: 'Trailing stop', value: fmtCapPct(caps?.trailing_stop_pct) },
                { label: 'Max tactical', value: fmtCapPct(caps?.max_tactical_pct) },
                { label: 'Trades / day', value: String(caps?.max_trades_per_day ?? '—') },
                { label: 'Open positions', value: String(caps?.max_open_positions ?? '—') },
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
                Circuit breakers
              </div>
              <ul className="text-xs text-muted-foreground space-y-0.5">
                {policy.circuit_breakers.map((cb) => (
                  <li key={cb.rule}>
                    {cb.label}: <span className="text-primary font-medium">−{fmtCapPct(cb.limit_pct)}</span>
                    {cb.effect ? ` — ${cb.effect}` : ''}
                  </li>
                ))}
                <li>
                  Flatten EOD:{' '}
                  <span className="text-primary font-medium">
                    {policy.flatten.flatten_eod
                      ? `required by ${policy.flatten.flatten_by || '15:45'} ET`
                      : 'off (holds overnight)'}
                  </span>
                </li>
                {policy.blocklists ? (
                  <li>
                    Blocked: moonshots (all modes)
                    {policy.blocklists.leveraged_etfs_allowed
                      ? '; leveraged ETFs allowed in this mode'
                      : '; leveraged ETFs blocked in this mode'}
                  </li>
                ) : null}
              </ul>
            </div>

            <div className="space-y-1">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Sector caps
              </div>
              <div className="overflow-x-auto rounded-md border">
                <table className="w-full text-xs">
                  <thead className="bg-ramp-grey-800/50 text-left text-muted-foreground">
                    <tr>
                      <th className="p-2">Sector</th>
                      <th className="p-2">Sector cap</th>
                      <th className="p-2">Per stock</th>
                      <th className="p-2">Universe</th>
                    </tr>
                  </thead>
                  <tbody>
                    {policy.sectors.map((s) => (
                      <tr key={s.key} className="border-t border-ramp-grey-800">
                        <td className="p-2">{s.label}</td>
                        <td className="p-2 tabular-nums">{fmtCapPct(s.max_sector_pct)}</td>
                        <td className="p-2 tabular-nums">{fmtCapPct(s.max_per_stock_pct)}</td>
                        <td className="p-2 tabular-nums text-muted-foreground">
                          {s.ticker_count ?? 0} tickers
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <p className="text-[11px] text-muted-foreground">
              {policy.note} Source: {policy.source}.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
