# Elestio / production deployment

Short guide for running **The-JRW/swarm-trader** on Elestio (`swarm-master`) with the production Docker Compose stack.

## Stack

- **Backend**: FastAPI (`app.backend.main:app`) on port **8000**
- **Frontend**: Vite build served by nginx on port **3000** (container port 80)
- **Ollama**: not required; use OpenRouter (or other cloud LLM keys)

## Quick start

```bash
cp .env.example .env
# Edit .env — set keys below
docker compose -f docker/docker-compose.prod.yml --env-file .env up -d --build
```

- UI: `http://<host>:3000`
- API: `http://<host>:8000`
- OpenAPI docs: `http://<host>:8000/docs`

Set `VITE_API_URL` to the **browser-reachable** backend URL before build (e.g. `https://your-api.elestio.app` or `http://<host>:8000`). Rebuild frontend after changing it.

Set `CORS_ORIGINS` to your UI origin(s), comma-separated.

## Required / recommended env vars

| Variable | Required | Notes |
|----------|----------|--------|
| `OPENROUTER_API_KEY` | Recommended | Default cloud LLM provider |
| `DEFAULT_LLM_PROVIDER` | Recommended | Default: `OpenRouter` |
| `DEFAULT_LLM_MODEL` | Recommended | Default: `openai/gpt-4o-mini` |
| `TIINGO_API_KEY` | Recommended | Primary price source when set; else yfinance |
| `ALPACA_API_KEY` | For trading | Swing / primary account |
| `ALPACA_API_SECRET` | For trading | Swing / primary account |
| `ALPACA_TRADING_MODE` | Safety | `paper` (default) or `live` |
| `ALPACA_BASE_URL` | Optional | Overrides mode; paper vs live REST base |
| `ALPACA_DAY_API_KEY` / `ALPACA_DAY_API_SECRET` | Optional | Separate day-trading account |
| `VITE_API_URL` | Prod UI | Backend URL baked into the frontend build |
| `CORS_ORIGINS` | Prod API | Allowed frontend origins |

## Alpaca paper vs live — warning

**Default is paper trading** (`ALPACA_TRADING_MODE=paper` → `https://paper-api.alpaca.markets/v2`).

Setting `ALPACA_TRADING_MODE=live` (or pointing `ALPACA_BASE_URL` at `https://api.alpaca.markets/v2`) enables **real orders with real money**. Only switch after verifying keys, risk limits, and paper behavior.

## Market data

1. If `TIINGO_API_KEY` is set → prices from Tiingo (daily, IEX fallback)
2. Else → yfinance (+ SEC EDGAR for fundamentals / filings)

Free fallbacks are never removed.

## LLM

With `OPENROUTER_API_KEY` and the defaults above, agents use OpenRouter (`openai/gpt-4o-mini` unless overridden). Ollama remains optional for local models and is not started by `docker-compose.prod.yml`.

## Elestio notes

- Point the service compose file at `docker/docker-compose.prod.yml`
- Inject secrets via Elestio env UI (do not commit `.env`)
- Expose **3000** (UI) and optionally **8000** (API) on the service
- After changing `VITE_API_URL`, rebuild: `docker compose -f docker/docker-compose.prod.yml build frontend --no-cache`
