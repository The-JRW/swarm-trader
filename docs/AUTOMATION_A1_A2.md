# Automation A1 + A2 — Paper cron routes

Paper-only weekday automation for **The-JRW/swarm-trader**. Reviewer Phase 1 binding constraints apply: no live trading from these paths.

Image tag: `strategies-ux-9`

## Secrets (Elestio)

| Env | Required | Notes |
|-----|----------|--------|
| `SWARM_CRON_SECRET` | **Yes** for `/cron/*` | Set in Elestio env UI. Header `X-Swarm-Cron-Secret`. Never commit a real value. |
| `SWARM_MONITOR_DRY_RUN` | Recommended | Default `true`. Hot monitor sells only when this is `false` **and** body `dry_run=false`. |
| `ALPACA_API_KEY` / `ALPACA_API_SECRET` | Yes | Paper keys. |
| `ALPACA_TRADING_MODE` | Safety | Must stay `paper`. Live → FAIL_CLOSED. |
| `GIT_SHA` | Optional | Wired into `/build-info` via compose + Dockerfile build-arg. |

Placeholder: see `docs/ELESTIO_SWARM_CRON_SECRET.placeholder.md`.

## Auth

All `/cron/*` (and `/api/cron/*`) routes require:

```http
X-Swarm-Cron-Secret: <SWARM_CRON_SECRET>
```

Missing env secret, missing header, or mismatch → **401 FAIL_CLOSED**. Responses never echo secrets.

## Endpoints

Base: `https://<host>` (UI proxies `/api` → backend). Examples use `/api/cron/...`.

### A1 — Paper swarm cron

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/cron/paper-run` | Start paper analysis (CORE analysts default) |
| `GET` | `/api/cron/paper-run/{run_id}` | Poll status |
| `GET` | `/api/cron/health` | `paper_only`, `mode`, `has_alpaca_keys` |

**Defaults for `POST /cron/paper-run`:**

- `strategy_ids`: CORE analysts only
- `mode`: `resolve_mode()` / swing
- `tickers`: swing `core_tech` universe (capped) or liquid set `NVDA,AAPL,MSFT,AMZN,META,GOOGL,SPY`
- `execute_trades`: **false** (analysis-only) unless body or `?execute_trades=true`

**Store assumption:** run status uses the **single-worker in-memory** store (`paper_run_service`). Not shared across replicas; lost on restart. Prefer one backend replica for cron paper-runs.

```bash
# Health
curl -sS -H "X-Swarm-Cron-Secret: $SWARM_CRON_SECRET" \
  https://swarm-master-u73408.vm.elestio.app/api/cron/health

# Start analysis-only paper run (defaults)
curl -sS -X POST \
  -H "X-Swarm-Cron-Secret: $SWARM_CRON_SECRET" \
  -H "Content-Type: application/json" \
  -d '{}' \
  https://swarm-master-u73408.vm.elestio.app/api/cron/paper-run

# Custom tickers + explicit analysis-only
curl -sS -X POST \
  -H "X-Swarm-Cron-Secret: $SWARM_CRON_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"tickers":["NVDA","AAPL","MSFT"],"mode":"swing","execute_trades":false}' \
  https://swarm-master-u73408.vm.elestio.app/api/cron/paper-run

# Poll status
curl -sS -H "X-Swarm-Cron-Secret: $SWARM_CRON_SECRET" \
  https://swarm-master-u73408.vm.elestio.app/api/cron/paper-run/<run_id>
```

### A2 — Portfolio monitor + EOD

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/cron/portfolio-monitor` | Check stops; optional day flatten |
| `GET` | `/api/cron/monitor-status` | Last summary from `/app/data/automation/` |

**Body:** `{ "dry_run"?: bool, "flatten_day"?: bool }`

**Dry-run resolution:**

- Default **`dry_run=true`**
- Hot (place paper sells) only when **`SWARM_MONITOR_DRY_RUN=false`** **AND** body **`dry_run=false`**
- Otherwise always dry-run (compute would-sell actions, place no orders)
- Live trading refused (FAIL_CLOSED)

```bash
# Safe dry-run (default)
curl -sS -X POST \
  -H "X-Swarm-Cron-Secret: $SWARM_CRON_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"dry_run":true}' \
  https://swarm-master-u73408.vm.elestio.app/api/cron/portfolio-monitor

# Day flatten dry-run (would-sell list only)
curl -sS -X POST \
  -H "X-Swarm-Cron-Secret: $SWARM_CRON_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"dry_run":true,"flatten_day":true}' \
  https://swarm-master-u73408.vm.elestio.app/api/cron/portfolio-monitor

# Status files summary
curl -sS -H "X-Swarm-Cron-Secret: $SWARM_CRON_SECRET" \
  https://swarm-master-u73408.vm.elestio.app/api/cron/monitor-status
```

### UI (no secret)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/automation/status` | Ops card — last paper-run id/status, monitor dry-run flag, last actions |

## Dry-run week exit criteria (A2)

Before setting `SWARM_MONITOR_DRY_RUN=false` in Elestio:

1. **5 consecutive weekday dry-runs** without unexpected would-sell errors (HTTP 5xx, auth failures, or malformed action payloads).
2. **James / Reviewer ack** to set `SWARM_MONITOR_DRY_RUN=false`.
3. Keep body `dry_run=false` only on intentional hot cron invocations after (1)+(2).

Until then, leave env at `true` and call with `{"dry_run":true}` (or omit `dry_run`).

## Status files

Written under `/app/data/automation/` (compose volume `swarm_data`):

- `last_paper_run.json`
- `last_monitor.json`
- `ops_status.json`

No secrets in these files.
