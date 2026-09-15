/** Shared money/percent formatting for the Strategies Run + Book panes. */

export function fmtMoney(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  });
}

/** Accepts a fraction (0.0123) or an already-scaled percent (1.23). */
export function fmtPct(frac?: number | null) {
  if (frac == null || Number.isNaN(frac)) return '—';
  const pct = Math.abs(frac) <= 1 ? frac * 100 : frac;
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct.toFixed(2)}%`;
}

/** Percent value already expressed as 0–100 from the risk policy endpoint. */
export function fmtCapPct(pct?: number | null) {
  if (pct == null || Number.isNaN(pct)) return '—';
  return `${Number(pct) % 1 === 0 ? pct.toFixed(0) : pct.toFixed(2)}%`;
}

export function actionTone(action: string) {
  const a = action.toLowerCase();
  if (a === 'buy' || a === 'cover') return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40';
  if (a === 'sell' || a === 'short') return 'bg-rose-500/15 text-rose-300 border-rose-500/40';
  return 'bg-slate-500/15 text-slate-300 border-slate-500/40';
}
