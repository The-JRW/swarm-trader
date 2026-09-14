# Strategies UI — paper analysis without the CLI

Easy path for running a **paper** multi-agent analysis from the web UI.

Live UI (example): https://swarm-master-u73408.vm.elestio.app

## What it does

1. Opens a **Strategies** tab (home strip, top bar, or left sidebar).
2. Lets you pick **mode** (`swing` / `day` / `auto`), multi-select **strategies**, and enter **tickers**.
3. Starts a **bounded paper analysis** via `POST /runs/paper` (also under `/api/...`).
4. Polls `GET /runs/{id}` for status and a simple decision summary.

No real orders are placed from this path. `ALPACA_TRADING_MODE` stays **`paper`** by default. SIP market data is unchanged.

## Prerequisites (server env)

Set on the **backend** (Elestio env / `.env`), not in the browser:

| Variable | Purpose |
|----------|---------|
| `ALPACA_API_KEY` / `ALPACA_API_SECRET` | Required — paper run is **FAIL_CLOSED** without them |
| `ALPACA_TRADING_MODE=paper` | Default; Strategies UI refuses `live` |
| `ALPACA_DATA_FEED=sip` | Unchanged SIP data path |
| `OPENROUTER_API_KEY` (or other LLM) | Agents need an LLM |

The UI shows a **using server keys** badge when Alpaca keys are present server-side. Do **not** paste secrets into the UI.

## How to try it

1. Open the UI (no login required on current Elestio deploy).
2. Click **Open Strategies** on the welcome strip, or **Strategies** in the top bar / left sidebar.
3. Confirm mode (default from `trading_mode.json` / env).
4. Keep the **core** strategy set (or tweak).
5. Enter tickers, e.g. `NVDA, AAPL, MSFT`.
6. Click **Run paper analysis**.
7. Wait for status → `complete` and review the decision table.

Flow graph remains available for advanced setups; Strategies is the easy path.

## API reference

Mounted both at the root and under `/api` (nginx `/api/` proxy strips to root):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/strategies` | List strategies (`id`, `name`, `description`, `category`, `enabled_default`) + `server_keys` |
| `GET` | `/trading/mode` | Current swing\|day\|auto from `trading_mode.json` / env |
| `POST` | `/trading/mode` | Set mode (`{ "mode": "swing" }`) — does not flip Alpaca live/paper |
| `POST` | `/runs/paper` | Start paper run `{ tickers, strategy_ids, mode, sync? }` → `{ run_id }` |
| `GET` | `/runs/{id}` | Status / result summary |
| `GET` | `/portfolio/glance` | Optional paper portfolio glance for the home strip |

### FAIL_CLOSED

If Alpaca keys are missing, `POST /runs/paper` returns **503** with a clear message. Runs never log secret values.

### Paper-only

If `ALPACA_TRADING_MODE=live`, paper runs return **403**. Use Elestio env to keep paper until you intentionally go live.

## Implementation notes

- Backend wraps `src.main.run_hedge_fund` / existing analyst graph + risk + portfolio manager.
- Risk Manager and Portfolio Manager are always part of the workflow when analysts run.
- Core default analysts match `run_hedge_fund.py`: Buffett, Burry, Wood, Apex, AutoResearch, fundamentals, technicals.
- `Dockerfile.frontend` continues to use `npx vite build` (no `tsc` gate).

## Local smoke

```bash
# Backend
poetry run uvicorn app.backend.main:app --reload --port 8000

# Frontend
cd app/frontend && npm run dev

curl -s localhost:8000/strategies | jq '.server_keys, .strategies[0]'
curl -s localhost:8000/trading/mode | jq .
```
