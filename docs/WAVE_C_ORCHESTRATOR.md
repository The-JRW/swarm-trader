# Wave C — Auto Swarm Orchestrator (C1–C5)

Paper-only auto scan → recipe → analysis orchestration for **The-JRW/swarm-trader**.  
Image tag: `strategies-ux-11`. Feature flag: `wave-c-orchestrator` (+ `swarm-scan*`).

**Deferred:** C6 Flow stub.

Reviewer binding: paper-only; do **not** set `SWARM_MONITOR_DRY_RUN=false` via this path; do **not** flip live trading.

## Amendments

1. **Mode-universe intersect default ON** for swing (and day OK); toggle allowed on scan request.
2. **Apply-to-recipe cap ≤15** tickers; candidates carry source tags (`mover` / `active` / `core`).
3. **Cron cadence is Scheduler-owned later** — this wave adds endpoints only (no high-frequency in-app spam cron).
4. **`SWARM_AUTO_LAUNCH`** only allows scan→apply recipe and/or launch **analysis**. Execute still requires existing dual gate `SWARM_CRON_EXECUTE_TRADES` ∧ recipe/request `execute_trades`. Never flips `MONITOR_DRY_RUN` or live via scan path.
5. Defaults: paper-only; cron **scan-only**; `SWARM_AUTO_LAUNCH` absent/false; **no secrets** in scan JSON.

## C1 — Swarm scan service

- Service: `app/backend/services/swarm_scan_service.py` wraps `scan_market.scan()`.
- Persists to `/app/data/automation/last_scan.json` (via `automation_store`).
- Optional intersect with mode universe from `get_mode_config` (**default ON**).
- Returns candidates with `sources: ["mover"|"active"|"core", ...]`.

### Public API (no cron secret)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/automation/swarm-scan` | Run scan + persist |
| `GET` | `/api/automation/swarm-scan` | Last scan + recent history |

Body (POST):

```json
{
  "mode": "swing",
  "intersect_universe": true,
  "max_tickers": 25,
  "include_core": true
}
```

## C2 — Apply to recipe

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/automation/swarm-scan/apply` | Top N (≤15) → `cron_recipe` tickers |

Ops UI: **Apply to recipe** button.

## C3 — Suggest & launch

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/automation/swarm-scan/launch` | Paper analysis from recipe/CORE analysts |

- Default **analysis-only** (`execute_trades=false`).
- Optional paper execute only with UI confirm + still dual-gated by env.
- Prefer `POST /api/runs/paper` equivalent via internal `launch_analysis_from_recipe`.

## C4 — Cron

| Method | Path | Auth |
|--------|------|------|
| `POST` | `/api/cron/swarm-scan` | `X-Swarm-Cron-Secret` |

Body flags:

```json
{
  "apply_recipe": false,
  "launch": false,
  "intersect_universe": true,
  "mode": "swing",
  "top_n": 15
}
```

- Always runs a scan and persists.
- `apply_recipe` / `launch` honored **only if** `SWARM_AUTO_LAUNCH` is truthy; otherwise **scan-only**.
- Launch = paper **analysis** (execute still dual-gated separately; cron auto path forces analysis-only).

## C5 — Audit

- History: `/app/data/automation/scan_history.jsonl` (last K≈20).
- Ops UI shows recent scans; `GET /api/automation/status` includes `last_scan` + `recent_scans`.

## Env

| Env | Default | Notes |
|-----|---------|--------|
| `SWARM_CRON_SECRET` | (required for cron) | Header auth |
| `SWARM_AUTO_LAUNCH` | unset/false | Enables cron apply/launch |
| `SWARM_CRON_EXECUTE_TRADES` | unset/false | Dual gate with recipe/request |
| `SWARM_MONITOR_DRY_RUN` | `true` | **Do not** flip via scan path |
| `SWARM_AUTOMATION_DIR` | `/app/data/automation` | Optional |

## Curl examples

```bash
# Manual scan (no secret)
curl -sS -X POST -H 'Content-Type: application/json' \
  -d '{"mode":"swing","intersect_universe":true}' \
  https://<host>/api/automation/swarm-scan

# Apply top 10 to recipe
curl -sS -X POST -H 'Content-Type: application/json' \
  -d '{"top_n":10}' \
  https://<host>/api/automation/swarm-scan/apply

# Launch analysis-only
curl -sS -X POST -H 'Content-Type: application/json' \
  -d '{"execute_trades":false}' \
  https://<host>/api/automation/swarm-scan/launch

# Cron scan-only (default when SWARM_AUTO_LAUNCH unset)
curl -sS -X POST -H "X-Swarm-Cron-Secret: $SWARM_CRON_SECRET" \
  -H 'Content-Type: application/json' \
  -d '{"apply_recipe":true,"launch":true}' \
  https://<host>/api/cron/swarm-scan
```

## Single-replica assumption

Scan files live on the backend volume (`swarm_data`) — not shared across multi-replica deploys. Prefer one backend replica for Strategies + cron.
