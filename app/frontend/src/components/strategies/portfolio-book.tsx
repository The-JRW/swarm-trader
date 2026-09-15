import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { fmtMoney, fmtPct } from '@/components/strategies/format';
import { cn } from '@/lib/utils';
import { PortfolioOrder, PortfolioPositionsResponse } from '@/services/strategies-api';
import { RefreshCw, TrendingDown, TrendingUp } from 'lucide-react';

interface PortfolioBookProps {
  portfolio: PortfolioPositionsResponse | null;
  orders: PortfolioOrder[];
  ordersMsg: string | null;
  loading: boolean;
  closing: boolean;
  selectedPositions: Set<string>;
  onToggleSelected: (symbol: string) => void;
  onSelectAll: (checked: boolean) => void;
  onRefresh: () => void;
  onClose: (symbols: string[]) => void;
}

/** D1 — the Book pane: paper positions, closes, and recent fills. */
export function PortfolioBook({
  portfolio,
  orders,
  ordersMsg,
  loading,
  closing,
  selectedPositions,
  onToggleSelected,
  onSelectAll,
  onRefresh,
  onClose,
}: PortfolioBookProps) {
  const positions = portfolio?.positions || [];

  return (
    <Card className="border-blue-500/20">
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="text-base">Portfolio</CardTitle>
            <CardDescription>Paper account glance, open positions, recent fills</CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={onRefresh} disabled={loading || closing}>
            <RefreshCw className={cn('h-3.5 w-3.5 mr-1.5', loading && 'animate-spin')} />
            Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {!portfolio?.available ? (
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              {portfolio?.message ||
                'Portfolio unavailable — check server Alpaca keys and paper mode, then retry.'}
            </p>
            <Button variant="outline" size="sm" onClick={onRefresh} disabled={loading}>
              Retry portfolio load
            </Button>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label: 'Cash', value: fmtMoney(portfolio.cash) },
                { label: 'Equity', value: fmtMoney(portfolio.equity) },
                { label: 'Buying power', value: fmtMoney(portfolio.buying_power) },
                { label: 'Positions', value: String(portfolio.positions_count ?? positions.length) },
              ].map((k) => (
                <div key={k.label} className="rounded-lg border bg-ramp-grey-800/30 px-3 py-2">
                  <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                    {k.label}
                  </div>
                  <div className="text-sm font-semibold tabular-nums mt-0.5">{k.value}</div>
                </div>
              ))}
            </div>

            {positions.length > 0 ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Open positions
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={closing || selectedPositions.size === 0}
                    onClick={() => onClose([...selectedPositions])}
                    className="border-rose-500/40 text-rose-200 hover:bg-rose-500/10"
                  >
                    Close selected… ({selectedPositions.size})
                  </Button>
                </div>

                <div className="overflow-x-auto rounded-md border">
                  <table className="w-full text-sm">
                    <thead className="bg-ramp-grey-800/50 text-left text-xs text-muted-foreground">
                      <tr>
                        <th className="p-2 w-8">
                          <Checkbox
                            checked={positions.length > 0 && selectedPositions.size === positions.length}
                            onCheckedChange={(c) => onSelectAll(c === true)}
                          />
                        </th>
                        <th className="p-2">Symbol</th>
                        <th className="p-2">Side</th>
                        <th className="p-2">Qty</th>
                        <th className="p-2">Mkt value</th>
                        <th className="p-2">P/L $</th>
                        <th className="p-2">P/L %</th>
                        <th className="p-2" />
                      </tr>
                    </thead>
                    <tbody>
                      {positions.map((p) => {
                        const pl = p.unrealized_pl;
                        const up = pl != null && pl >= 0;
                        return (
                          <tr key={p.symbol} className="border-t border-ramp-grey-800 align-middle">
                            <td className="p-2">
                              <Checkbox
                                checked={selectedPositions.has(p.symbol)}
                                onCheckedChange={() => onToggleSelected(p.symbol)}
                              />
                            </td>
                            <td className="p-2 font-medium">{p.symbol}</td>
                            <td className="p-2 capitalize">{p.side}</td>
                            <td className="p-2 tabular-nums">{p.qty}</td>
                            <td className="p-2 tabular-nums">{fmtMoney(p.market_value)}</td>
                            <td
                              className={cn(
                                'p-2 tabular-nums',
                                pl == null ? '' : up ? 'text-emerald-300' : 'text-rose-300'
                              )}
                            >
                              <span className="inline-flex items-center gap-1">
                                {pl != null ? (
                                  up ? (
                                    <TrendingUp className="h-3 w-3" />
                                  ) : (
                                    <TrendingDown className="h-3 w-3" />
                                  )
                                ) : null}
                                {fmtMoney(pl)}
                              </span>
                            </td>
                            <td
                              className={cn(
                                'p-2 tabular-nums',
                                p.unrealized_plpc == null
                                  ? ''
                                  : (p.unrealized_plpc ?? 0) >= 0
                                    ? 'text-emerald-300'
                                    : 'text-rose-300'
                              )}
                            >
                              {fmtPct(p.unrealized_plpc)}
                            </td>
                            <td className="p-2">
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-7 text-xs border-rose-500/40 text-rose-200"
                                disabled={closing}
                                onClick={() => onClose([p.symbol])}
                              >
                                Close…
                              </Button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No open positions</p>
            )}

            <div>
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">
                Recent orders
              </div>
              {orders.length === 0 ? (
                <p className="text-sm text-muted-foreground">{ordersMsg || 'No recent orders'}</p>
              ) : (
                <div className="overflow-x-auto rounded-md border">
                  <table className="w-full text-sm">
                    <thead className="bg-ramp-grey-800/50 text-left text-xs text-muted-foreground">
                      <tr>
                        <th className="p-2">Symbol</th>
                        <th className="p-2">Side</th>
                        <th className="p-2">Qty</th>
                        <th className="p-2">Filled</th>
                        <th className="p-2">Avg</th>
                        <th className="p-2">P&L</th>
                        <th className="p-2">Status</th>
                        <th className="p-2">Submitted</th>
                      </tr>
                    </thead>
                    <tbody>
                      {orders.map((o, i) => {
                        const showPl = Boolean(o.is_closing) && o.realized_pl != null;
                        const pl = o.realized_pl;
                        const up = pl != null && pl >= 0;
                        return (
                          <tr
                            key={`${o.symbol}-${o.submitted_at}-${i}`}
                            className="border-t border-ramp-grey-800"
                          >
                            <td className="p-2 font-medium">{o.symbol || '—'}</td>
                            <td className="p-2 uppercase text-xs">{o.side || '—'}</td>
                            <td className="p-2 tabular-nums">{o.qty ?? '—'}</td>
                            <td className="p-2 tabular-nums">{o.filled_qty ?? '—'}</td>
                            <td className="p-2 tabular-nums">{fmtMoney(o.filled_avg_price)}</td>
                            <td
                              className={cn(
                                'p-2 tabular-nums whitespace-nowrap',
                                !showPl
                                  ? 'text-muted-foreground'
                                  : up
                                    ? 'text-emerald-300'
                                    : 'text-rose-300'
                              )}
                            >
                              {showPl ? (
                                <span className="inline-flex items-center gap-1">
                                  {up ? (
                                    <TrendingUp className="h-3 w-3" />
                                  ) : (
                                    <TrendingDown className="h-3 w-3" />
                                  )}
                                  {fmtMoney(pl)}
                                  {o.realized_plpc != null ? (
                                    <span className="text-[10px] opacity-80">
                                      ({fmtPct(o.realized_plpc)})
                                    </span>
                                  ) : null}
                                </span>
                              ) : (
                                '—'
                              )}
                            </td>
                            <td className="p-2">
                              <Badge variant="outline" className="text-[10px]">
                                {o.status || '—'}
                              </Badge>
                            </td>
                            <td className="p-2 text-xs text-muted-foreground whitespace-nowrap">
                              {o.submitted_at
                                ? new Date(o.submitted_at).toLocaleString(undefined, {
                                    month: 'short',
                                    day: 'numeric',
                                    hour: '2-digit',
                                    minute: '2-digit',
                                  })
                                : '—'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
