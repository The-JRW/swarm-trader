# Control Wave B (B1–B5) — Ops recipe, history, digest, snapshots, mode override

Paper-only control plane for **The-JRW/swarm-trader**. Image tag: `strategies-ux-10`.

Reviewer binding: no live trading; do **not** set `SWARM_MONITOR_DRY_RUN=false` without ack.

## Single-replica assumption

Automation status, cron recipe, durable run history (`/app/data/runs/`), and performance snapshots are **local disk** on the backend volume (`swarm_data`). They are **not** shared across multi-replica deploys. Prefer **one backend replica** for Strategies + cron.

## B1 — Ops recipe control

Persisted at `/app/data/automation/cron_recipe.json` (same area as `automation_store`):

```json
{
  "tickers": ["NVDA", "AAPL", "MSFT"],
  "preset": "core",
  "mode": "swing",
  "execute_trades": false
}
```

- `preset`: `core` | `value` | `growth` | `quant` | `custom`
- `mode`: `swing` | `day` | `auto`
- **No secrets** in this file.

### Public recipe API (no cron secret)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/automation/recipe` | Read recipe + whether env allows execute |
| `PUT`/`POST` | `/api/automation/recipe` | Write recipe (paper-only config) |

### Cron applies recipe defaults

`POST /api/cron/paper-run` (still requires `X-Swarm-Cron-Secret`): when body omits `tickers` / `mode` / `execute_trades` / `strategy_ids`, values come from the recipe (preset → analyst set).

### Dual gate for execute

`execute_trades` is effective **only if**:

1. Recipe or request body/query says `true`, **and**
2. Env `SWARM_CRON_EXECUTE_TRADES` is truthy (`1` / `true` / `yes` / `on`)

Otherwise cron **forces** `execute_trades=false` (analysis-only). Strategies Ops card shows whether env allows execute and requires a confirm dialog before setting recipe `execute_trades=true`.

## B2 — Durable run history

- Path: `/app/data/runs/` (per-run JSON + `index.jsonl`)
- Last **N=50** paper runs (Strategies + cron)
- Hooked from `paper_run_service` create/update/complete
- `GET /api/runs/history` — sanitized summaries
- Strategies UI lists durable history (survives refresh; still single-replica)

## B3 — Conviction digest

After a paper run completes, digest is computed from **real** `analyst_signals`:

- **consensus** — majority agree buy (bullish) or sell (bearish)
- **contested** — bullish vs bearish split
- **risk-rejected** — risk `remaining_position_limit=0` with bullish lean

No invented confidence scores. Stored on the run record, on `/api/automation/status` as `last_conviction_digest`, and shown in Strategies results + Ops card.

## B4 — Performance snapshots

| Method | Path | Auth |
|--------|------|------|
| `POST` | `/api/cron/performance-snapshot` | `X-Swarm-Cron-Secret` |

Writes under `/app/data/performance_snapshots/` (equity + SPY/QQQ when available).

`GET /api/portfolio/performance` returns `as_of` and `spy_alpha` **only when real snapshot/benchmark data exists** — never fake zeros. Performance dashboard shows α vs SPY when present.

## B5 — Mode override UX

Strategies / Ops: human override control (`swing` / `day` / `auto`) with a **reason** field. Calls existing `POST /api/trading/mode` with `override=true`. Override wins over auto; last reason is displayed. No live trading path (`ALPACA_TRADING_MODE` unchanged).

## Env (Elestio)

| Env | Default | Notes |
|-----|---------|--------|
| `SWARM_CRON_SECRET` | (required for cron) | Header auth |
| `SWARM_CRON_EXECUTE_TRADES` | unset/false | Dual gate with recipe |
| `SWARM_MONITOR_DRY_RUN` | `true` | Leave true until ack |
| `SWARM_AUTOMATION_DIR` | `/app/data/automation` | Optional |
| `SWARM_RUNS_DIR` | `/app/data/runs` | Optional |
| `SWARM_PERF_SNAPSHOTS_DIR` | `/app/data/performance_snapshots` | Optional |

## Curl examples

```bash
# Recipe (no secret)
curl -sS https://<host>/api/automation/recipe
curl -sS -X PUT -H 'Content-Type: application/json' \
  -d '{"tickers":["NVDA","AAPL"],"preset":"core","mode":"swing","execute_trades":false}' \
  https://<host>/api/automation/recipe

# History
curl -sS https://<host>/api/runs/history

# Performance snapshot (secret)
curl -sS -X POST -H "X-Swarm-Cron-Secret: $SWARM_CRON_SECRET" \
  https://<host>/api/cron/performance-snapshot
```
