> Wave G interim doc for The-JRW/swarm-trader. Cross-links:
> [WAVE_F_HIT.md](./WAVE_F_HIT.md) · [STRATEGIES_UI.md](./STRATEGIES_UI.md) ·
> [CONTROL_WAVE_B.md](./CONTROL_WAVE_B.md) · [WAVE_C_ORCHESTRATOR.md](./WAVE_C_ORCHESTRATOR.md) ·
> [WAVE_D.md](./WAVE_D.md) · [WAVE_E.md](./WAVE_E.md) · [AUTOMATION_A1_A2.md](./AUTOMATION_A1_A2.md)

# Wave G (G2–G6) — latency-max paper HIT (still NOT colocated µs HFT)

James follow-up (t178u), on the same branch/image tag as the t175u HIT trade-count override:
after lifting the HIT trade-count ceiling (see [WAVE_F_HIT.md](./WAVE_F_HIT.md)'s "James
override" section), **get as close to colocated µs HFT as this stack allows, without false
claims.** Paper-only follow-up to Wave F for **The-JRW/swarm-trader**. Image tag:
`strategies-ux-15`. Feature flags: `hit-fast-path`, `hit-quote-freshness-gate`,
`hit-quote-ws-optional`, `hit-latency-observatory` (see `GET /build-info`).

## Read this first: what "as close as this stack allows" actually means

**This is latency-max paper trading over a broker REST/WebSocket API. It is not, and cannot
honestly be called, colocated microsecond HFT.** Nothing in this wave changes that
fundamental fact — it only removes the *avoidable, non-fundamental* slack this codebase itself
was adding on top of that hard floor:

- **G2 avoids waiting on an LLM call it doesn't need.** The default HIT analyst set was
  already fast; G2 makes the "fast vs. slow" split explicit and opt-in-only for the slow half,
  so a HIT run never pays for an LLM call (apex / news sentiment) unless someone asks for it.
- **G3 avoids trading on a quote that has gone stale since it was fetched**, and — only when
  explicitly enabled — shaves a REST round-trip off getting that quote in the first place via
  a read-only streaming subscription (still just a public retail data feed, not a co-located
  exchange tap).
- **G4 doesn't reduce latency at all** — it *measures* it, honestly, so anyone looking at the
  Ops HIT strip can see exactly how much of a HIT trade's time-to-fill is decision time,
  network/broker-processing time, and fill time, instead of guessing.

What this wave explicitly does **not** do, because this stack cannot honestly do it:

- No co-location, no proximity hosting, no exchange floor presence.
- No FPGA/kernel-bypass NICs, no direct exchange feed handlers, no ITCH/OUCH-class protocols.
- No limit-order-book (LOB) reconstruction, no queue-position modeling, no maker/taker rebate
  capture.
- No claim that a REST/WebSocket round-trip to a retail broker API is "fast" in HFT terms —
  every latency number this wave surfaces is presented in **milliseconds**, next to a
  documented ~50–500ms REST baseline (see [WAVE_F_HIT.md](./WAVE_F_HIT.md)), not compared to
  the microsecond figures real HFT operates at.

Every surface this wave adds — docs, UI copy, API responses — says "latency-max paper" or
similar, and never "HFT", "colocated", "microsecond", or "low-latency trading" in a way that
could be read as a capability claim about this system.

## Scope G2–G6

### G2 — fast HIT path

`app/backend/services/hit_service.py`:

- `HIT_PRESET_ANALYST_IDS` (unchanged from Wave F): `technical_analyst`, `market_regime`,
  `autoresearch`, `sentiment_analyst`. Honest LLM breakdown:
  - `technical_analyst`, `autoresearch`: **zero LLM calls** (pure/deterministic).
  - `sentiment_analyst`: **zero LLM calls** (rule-based insider-trade/news scoring).
  - `market_regime`: **one lightweight structured-output LLM call** (SPY/QQQ regime
    classification) — smaller than a full per-ticker trading decision, but still a real LLM
    call. Grouped with the fast set by design intent; documented honestly here rather than
    mislabeled as zero-LLM.
- `HIT_SLOW_LLM_ANALYST_IDS` (new): `apex`, `news_sentiment_analyst` — each makes **one full
  LLM call per ticker** (technical/tape reasoning and news summarization, respectively). Never
  included by default.
- `resolve_hit_analyst_ids(fast: bool = True)`: `fast=True` (default, matches every prior HIT
  pulse unchanged) returns the fast preset only. `fast=False` (explicit opt-in only) appends
  the slow pair.

`run_hit_pulse(..., fast: bool = True)` and both HTTP entry points
(`POST /cron/hit-pulse`, `POST /api/automation/hit/pulse`) now accept a `fast` request field
(default `true`) that is threaded straight into `resolve_hit_analyst_ids`.

**Why this is the correct place to intervene, and not "reorder graph nodes":**
`src/main.py create_workflow` fans every selected analyst node out from a single `start_node`
in parallel and fans back in at `risk_management_agent` → `portfolio_manager` — there is no
per-node execution-order dependency to exploit; every selected analyst's node runs
concurrently and the graph waits for **all** of them before the PM decides. So "fast HIT path"
cannot mean "run technical_analyst's *node* before apex's *node*" (LangGraph does not expose a
useful ordering knob there for parallel fan-out/fan-in). It has to mean — and does mean here —
"don't put an LLM-heavy analyst in the run's analyst set unless asked", which is the only
lever that actually changes how long a HIT run has to wait before the PM can decide.

### G3 — quote freshness

`app/backend/services/cost_gate_service.py`:

- `quote_age_ms(quote)` — age, in ms, of a live quote from its own Alpaca `t` timestamp.
  Returns `None` (never fabricated) when there is no live quote or its timestamp cannot be
  parsed — a ticker-class default assumption (Wave F) is never "stale" in this sense, because
  it was never claimed to be live in the first place.
- `evaluate_cost_gate(..., max_quote_age_ms=None)` — new **third** rejection path,
  `rule="stale_quote"`: a live quote whose age exceeds `SWARM_HIT_MAX_QUOTE_AGE_MS` (default
  `5000`ms) blocks the entry, because a stale quote cannot honestly back the F2 cost estimate.
  Exits/holds are unaffected (same as the two existing F2 checks). `CostGateResult` now
  reports `quote_age_ms` / `max_quote_age_ms` for transparency (both `None` when not
  applicable — a ticker-class-default trade never reports an age).
- Default budget (`5000`ms) is deliberately generous relative to the ~50–500ms REST baseline
  documented in Wave F — it exists to catch a genuinely stale/cached response (e.g. a closed
  market or a slow retry), not to reject ordinary fetch-then-decide-then-gate latency.

**Optional read-only quote WebSocket** — `app/backend/services/hit_quote_ws_service.py`:

- Off by default (`SWARM_HIT_QUOTE_WS_ENABLED=false`). When enabled, maintains **one**
  connection to Alpaca's market-data quote stream (`wss://stream.data.alpaca.markets/v2/{feed}`)
  to shave the REST round-trip off getting a quote before the freshness check above runs on
  it — a real (if modest) latency win over one-shot REST polling, not a claim of tick-level or
  co-located data.
- **Single-connection discipline is enforced, not advisory.** `HitQuoteWebSocketClient.start()`
  refuses to start a second connection while one is already running and returns `False` — the
  same constraint [WAVE_F_HIT.md](./WAVE_F_HIT.md)'s F5 cites for never opening a
  `trade_updates` order-stream connection: Alpaca allows exactly one connection per feed per
  account, and a second one drops the first.
- **Still read-only, still quotes-only, still no order stream.** This module never places,
  cancels, or watches an order — it only caches the latest quote per ticker in memory. Order
  state (submitted/filled) is still read via REST exactly as in Wave F.
- **Unconditional REST fallback.** `cost_gate_service.fetch_quotes_and_prices` checks this
  cache first (`_ws_cached_quote`); on any miss — disabled, not started, disconnected, no
  cached entry for that ticker, hard-evicted after 30s of cache residency — it falls back to a
  one-shot REST quote fetch exactly as Wave F always did. The WS is a latency optimization,
  never a hard dependency; every code path this system relies on continues to work with the
  WS permanently disabled (the default).
- The reconnect-with-backoff live-socket loop itself (`HitQuoteWebSocketClient._run_async`) is
  exercised manually/in staging with real Alpaca credentials, not by the automated unit suite
  — opening a real external WebSocket connection is out of scope for CI. What **is**
  unit-tested (see `tests/test_wave_g_latency_max.py`): message parsing
  (`parse_quote_message`/`parse_quote_messages`), the in-memory cache
  (`QuoteCache.set`/`get`/eviction), the enabled-flag default, and — most importantly — the
  single-connection discipline itself (a second `start()` call while "running" is refused).

### G4 — latency observatory

Every paper order placed via `src/alpaca_integration.py` now carries, when available:

| Stage | Field | Source | Never fabricated because |
|---|---|---|---|
| Decision | `decision_at` | This codebase's own clock, captured in `paper_run_service.execute_paper_run` right after the F2/G3 cost gate finishes and right before `_execute_paper_decisions` is called | It is exactly when *this run's* executable decision set was finalized — a real client-side event, attached to every order that batch places |
| Submit | `client_submit_at` | This codebase's own clock, captured in `alpaca_integration._post_order_with_timing` immediately before the Alpaca order `POST` | Real client-side clock read, one per order |
| Ack | `broker_ack_at` | Alpaca's own `created_at` (falls back to `submitted_at`) from the order-creation response | Broker-reported, not measured/estimated by this codebase |
| Fill | `filled_at` | Alpaca's own fill timestamp (Wave F's existing best-effort follow-up `GET /orders/{id}` when the initial response has none yet) | Broker-reported |

`app/backend/services/hit_ops_service.py`'s `_latency_breakdown` (replaces Wave F's
`_fill_latency`, keeping its exact `latency_ms` measure — Alpaca `submitted_at` → `filled_at`
— for backward compatibility) computes, **only from timestamps that are actually present**:

- `decision_to_submit_ms`, `submit_to_ack_ms`, `ack_to_fill_ms`, `decision_to_fill_ms`
- Any segment whose endpoint timestamp is missing is `None` — never estimated, interpolated,
  or backfilled. A row with no `filled_at` at all is not included in the recent-latencies list
  (this is fundamentally about completed fills).

Surfaced at `GET /api/automation/hit/ops` (`recent_fill_latencies`, now with the fuller
breakdown alongside the original `latency_ms`) and in the `HitOpsPanel` UI card, which shows
the end-to-end `decision_to_fill_ms` next to the original submit→fill figure when both are
available, and a plain "—" otherwise.

**This module measures latency; it does not reduce it.** Nothing about recording these
timestamps changes order routing, timing, or priority — see G2/G3 above for the two things
that actually can (and do, modestly) reduce time-to-decision/time-to-quote.

### G5 — hit-pulse stays analysis-default; dual gate unchanged

No change to `hit_ops_service.hit_execute_env_allows` / `resolve_hit_execute`, and no change
to `execute_trades` defaulting to `false` on both `POST /cron/hit-pulse` and
`POST /api/automation/hit/pulse`. The new `fast` field is independent of the execute dual gate
— setting `fast=false` changes *which analysts run*, never whether a trade can execute; that
still requires the request to set `execute_trades=true` **and** `SWARM_HIT_EXECUTE` to be
truthy, exactly as Wave F documented. `tests/test_wave_g_latency_max.py` includes a regression
test asserting the dual gate's truth table is byte-for-byte unchanged from Wave F's.

### G6 — this doc + WAVE_F_HIT.md honesty update

This document, plus the "Wave G follow-up" note and per-section cross-links added to
[WAVE_F_HIT.md](./WAVE_F_HIT.md) (header, F4, F5, Env, Tests). WAVE_F_HIT.md's F5 section
previously said "there is no WebSocket/`trade_updates` client in this codebase" — amended to
clarify that remains true for the **order** stream; Wave G's G3 adds an *optional, off by
default, read-only market-data* stream, which is a materially different (and much lower-risk)
thing than an order-update stream.

## Still true (unchanged, Wave F Reviewer amendments + James t175u override)

- Paper-only throughout — `assert_paper_only()` / `alpaca_trading_mode() == "live"` checks are
  untouched; nothing in Wave G adds a live-trading path.
- The F2 cost gate remains **mandatory** on any HIT execute attempt — G3 only adds a third
  rejection reason to the same mandatory gate; it does not make the gate optional or bypassable.
- `allow_leveraged_etfs: false` for `hit` — unchanged; no TQQQ/SOXL in the default universe.
- `SWARM_MONITOR_DRY_RUN` is never read or written by any Wave G module.
- No UI control anywhere flips `SWARM_HIT_EXECUTE` — unchanged from Wave F's F6/Reviewer
  amendment #5; the new `fast` field is a request-scoped analyst-selection flag, not an env
  flip, and has no bearing on execute.
- `max_trades_per_day` for `hit` stays at James's t175u override value (effectively unlimited
  for paper) — Wave G does not touch it further, and does not raise `max_position_pct` or any
  other position/exposure cap; James's instruction was explicit that many small trades under
  the existing per-name cap are preferred over larger ones.
- HIT ≠ true HFT (Wave F) and this wave ≠ colocated µs HFT (this doc) — both statements hold
  simultaneously and are not in tension; this wave narrows the avoidable gap between "paper
  REST trading" and "as fast as paper REST trading can honestly be", nothing more.

## Env (new; all optional, safe defaults)

| Env | Default | Notes |
|-----|---------|-------|
| `SWARM_HIT_MAX_QUOTE_AGE_MS` | `5000` | G3 — max age (ms) a live quote may be before the cost gate rejects the entry as stale |
| `SWARM_HIT_QUOTE_WS_ENABLED` | `false` | G3 — enables the optional single-connection, read-only quote WebSocket; REST-only (Wave F behavior) when unset/false |

No other env var is added or changed by this wave. `SWARM_HIT_EXECUTE`,
`SWARM_HIT_COST_GATE_BPS`, `SWARM_HIT_TURNOVER_BUDGET_PCT`, `SWARM_MONITOR_DRY_RUN`,
`SWARM_AUTO_LAUNCH`, `SWARM_CRON_EXECUTE_TRADES`, and `ALPACA_TRADING_MODE` keep their
Wave A–F defaults (see [WAVE_F_HIT.md](./WAVE_F_HIT.md)).

## Smoke

```bash
# G2 — fast path is the default; strategy_ids never include apex/news_sentiment_analyst
curl -sS -X POST -H "Content-Type: application/json" -d '{}' \
  https://<host>/api/automation/hit/pulse | jq '.strategy_ids, .fast'

# G2 — explicit opt-in to the slow path
curl -sS -X POST -H "Content-Type: application/json" -d '{"fast": false}' \
  https://<host>/api/automation/hit/pulse | jq '.strategy_ids, .fast'

# G3 — cost-gate response now reports quote_age_ms / max_quote_age_ms on rejects
curl -sS https://<host>/api/automation/hit/ops | jq '.recent_cost_gate_rejects'

# G4 — decision→submit→ack→fill breakdown on the Ops HIT strip
curl -sS https://<host>/api/automation/hit/ops | jq '.recent_fill_latencies, .latency_note'

# Build stamp
curl -sS https://<host>/api/build-info | jq '.image_tag, .features'
```

## Tests

`tests/test_wave_g_latency_max.py` covers: G2's `resolve_hit_analyst_ids` (fast default never
includes the slow pair; `fast=False` appends it after the fast preset) and that `run_hit_pulse`
threads `fast` through to the created run record; G3's `quote_age_ms` (real timestamp → real
age; missing/malformed timestamp → `None`) and `evaluate_cost_gate`'s new `stale_quote`
rejection (stale live quote blocked; fresh quote approved; ticker-class-default trades are
never marked stale); the optional quote-WS module's pure/unit-testable surface — message
parsing (`parse_quote_message`/`parse_quote_messages`) for quote vs. non-quote frames, the
`QuoteCache` round-trip and hard-eviction, the enabled-flag default (`false`), and the
single-connection discipline (`start()` refuses a second connection while one is "running",
verified with the live-socket loop monkeypatched out — no real network call); G4's latency
breakdown (`decision_to_submit_ms`/`submit_to_ack_ms`/`ack_to_fill_ms`/`decision_to_fill_ms`
computed only from present timestamps, `None` otherwise; Wave F's original `latency_ms`
measure unchanged) and `alpaca_integration`'s `_post_order_with_timing` helper (captures
`client_submit_at` always, `broker_ack_at` only on success); G5's regression that the
execute dual gate's truth table is unchanged; and the `strategies-ux-15` build-info flags
(`hit-fast-path`, `hit-quote-freshness-gate`, `hit-quote-ws-optional`,
`hit-latency-observatory`).

```bash
poetry run pytest tests/test_wave_g_latency_max.py -q
```
