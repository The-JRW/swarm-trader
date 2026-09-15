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

> **Reviewer `CHANGES_REQUIRED` follow-up (G2 only, image tag bumped to `strategies-ux-16`,
> new flag `hit-fast-path-ops-visible`):** G2's `fast` flag was live and correctly wired
> end-to-end on the backend, but Chrome found **no Ops/UI copy anywhere** for the fast HIT
> path / "skip heavy LLM" — a backend-only flag isn't reviewable from the UI. See
> ["G2 Ops-visible amendment"](#g2-ops-visible-amendment-reviewer-changes_required-strategies-ux-16)
> below for exactly what changed. No execute dual gate, cost gate, trade cap, or HFT claim was
> touched by this follow-up — it is UI/Ops-copy only, same as everything else in G2.
>
> **James t180u add-on (same PR/tag, `strategies-ux-16`, new flag `hit-hundreds-scale`):** HIT
> analysis/flow must cover **hundreds** of tickers, not the previous ~10-15. See
> ["James t180u — HIT scale"](#james-t180u--hit-scale-hundreds-of-tickers-not-10-15) below.
> This raises *how many tickers* a HIT run may consider — it does not touch the execute dual
> gate, the F2/G3 cost gate, any risk/trade cap, or the "not true HFT / not colocated" claims
> anywhere in this doc.

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

#### G2 Ops-visible amendment (Reviewer `CHANGES_REQUIRED`, `strategies-ux-16`)

**Problem:** G2's `fast` flag was correctly wired end-to-end on the backend
(`resolve_hit_analyst_ids` → `run_hit_pulse` → both HTTP entry points), but there was **no
Ops/UI copy anywhere** for the fast HIT path or "skip heavy LLM" — a Chrome reviewer could not
see it without reading the API response directly. Backend-only was insufficient.

**Fix (minimal, paper-only — UI/Ops-copy only, no gate/cap/claim changes):**

- `app/backend/services/hit_ops_service.py`: `record_hit_run(..., fast=None,
  analyst_ids=None)` now copies both onto the persisted `last_pulse` (`None`/omitted when a
  caller doesn't pass them — never guessed). `read_hit_ops()` always includes
  `fast_default` (`true`), `fast_path_analyst_ids` (mirrors `HIT_PRESET_ANALYST_IDS`),
  `slow_path_analyst_ids` (mirrors `HIT_SLOW_LLM_ANALYST_IDS`), and a `fast_path_note` — so
  the Ops HIT strip can render "Fast HIT path" copy even before any pulse has run today.
- `app/backend/services/paper_run_service.py`: `execute_paper_run`'s `mode == "hit"` branch
  derives `fast` from the run's **actual** resolved analyst set (`ran_slow_path = any(a in
  HIT_SLOW_LLM_ANALYST_IDS for a in analysts)`) — never re-guessed from a request flag that
  might not match what `_select_analysts` resolved — and passes `fast`/`analyst_ids` through
  to `record_hit_run`.
- `app/frontend/src/components/strategies/hit-ops-panel.tsx` (`HitOpsPanel`, the card James
  uses in Ops/Book): a header badge — ⚡ **"Fast HIT path"** (default) or 🐢 **"Slow path
  (opt-in)"** — reflecting the last pulse's actual path (falls back to the server default when
  no pulse has run yet); a labeled "Fast HIT path — analyst set" block spelling out
  `technical_analyst + market_regime + autoresearch + sentiment_analyst` for the fast path, or
  additionally `apex + news_sentiment_analyst` when the slow path ran; and a read-only
  **Fast (default) / Slow (opt-in)** selector plus a **"Run HIT pulse now (analysis-only)"**
  button so James can trigger either path directly from Ops/Book. That button always calls
  `POST /api/automation/hit/pulse` with `execute_trades: false` — it can select the analyst
  path, but it can never flip `SWARM_HIT_EXECUTE` or set `execute_trades: true`.
- `app/backend/routes/build_info.py`: new feature flag `hit-fast-path-ops-visible`.
- Image tag bumped `strategies-ux-15` → `strategies-ux-16` (`docker-compose.yml`).

**Explicitly unchanged by this amendment:** the F2/G3 cost gate, the execute dual gate
(`SWARM_HIT_EXECUTE` ∧ explicit request), every `hit` risk cap (including the t175u
`max_trades_per_day` override), and every "not true HFT / not colocated" claim in this doc and
`docs/WAVE_F_HIT.md` — this amendment adds visibility, not new capability.

#### James t180u — HIT scale (hundreds of tickers, not ~10-15)

**Ask:** HIT analysis and flow must cover **hundreds** of stocks, not the previous ~10-15
ceiling — while keeping the F2/G3 cost gate, stops, and `allow_leveraged_etfs=False`
completely untouched, and never claiming co-located HFT.

**What changed (all ceilings/breadth, no risk-rail changes):**

- `scan_market.py`: new `HIT_MAX_TICKERS` (default 300, env
  `SWARM_HIT_SCAN_MAX_TICKERS`) alongside the unchanged `DEFAULT_MAX_TICKERS` (25, still the
  CLI/day-swing default). `scan()` scales its raw Alpaca movers/most-actives pulls with
  `max_tickers` (capped at 100 — an Alpaca-side screener limit, not one this codebase
  invented), and `get_snapshots()` now auto-chunks into batches of 50 instead of silently
  truncating to the first 50 symbols — both are prerequisites for a large `max_tickers` to
  actually survive filtering, not just be requested. **Alpaca's screener may still return
  fewer names than requested on any given call** — this only raises the ceiling we
  request/allow, never a guarantee of count.
- `automation_store.py`: new `HIT_APPLY_RECIPE_MAX` (≥200, default 300, env
  `SWARM_HIT_APPLY_RECIPE_MAX`) and `apply_recipe_max_for(mode, preset)` — returns the hit
  ceiling when either is `"hit"`, else the original `APPLY_RECIPE_MAX` (15). The recipe
  ticker-cap (`_normalize_tickers`/`_normalize_recipe`), the Ops-status scan preview
  (`_scan_ops_summary`), the scan-history preview (`_append_scan_history`), and the persisted
  last-scan storage cap (`write_last_scan`) are all now mode/preset-aware through this one
  helper — swing/day behavior is byte-for-byte unchanged.
- `swarm_scan_service.py`: `apply_scan_to_recipe`'s `top_n=None` (new default) now resolves to
  the *full* mode-aware cap instead of a hardcoded 15; an explicit smaller `top_n` is still
  honored exactly as before. `run_swarm_scan`'s `max_tickers=None` (new default) resolves to
  `scan_market.HIT_MAX_TICKERS` for hit, `DEFAULT_MAX_TICKERS` otherwise. Passing an explicit
  `mode="hit"` to `apply_scan_to_recipe` also stamps the saved recipe's own `mode` to `"hit"` —
  otherwise `write_cron_recipe`'s own normalization would silently re-clamp a hundreds-scale
  ticker list back down to 20 on the very next read, since that clamp reads the *persisted*
  recipe's mode/preset, not a transient function argument.
- `hit_service.py`: `run_hit_pulse`'s ceiling raised from a hardcoded `15` to `HIT_MAX_TICKERS`
  (default 300, env `SWARM_HIT_MAX_TICKERS`); the *default* request size when `top_n` is
  omitted stays `DEFAULT_HIT_TICKER_CAP` (10) — unchanged, so an unspecified/cron pulse is
  exactly as fast as before. Hundreds only happen when a caller (scan-discovered tickers, an
  explicit list, or an explicit large `top_n`) actually asks for them.
- **Auto-fast safety rail** (`HIT_AUTO_FAST_TICKER_THRESHOLD`, 30): even an *explicit*
  `fast=False` (slow-path opt-in) request is overridden back to `fast=True` when the resolved
  ticker count exceeds 30 — hundreds of tickers must never wait on the LLM-heavy
  `apex`/`news_sentiment_analyst` pair, which would turn "latency-max paper trading" into an
  LLM-call meltdown. Small/medium explicit slow-path requests (≤30 tickers) are honored
  exactly as G2 originally specified. The pulse response reports `fast` (effective),
  `fast_requested` (the raw ask), and `auto_fast_override` (whether the rail fired) —
  never silently swapping the analyst set without saying so.
- `src/config.py`: `MODES["hit"]["universe"]` widened from 11 tickers (9 mega-cap + SPY/QQQ)
  to 115 — new sector buckets (semis/hardware, software/cloud, financials, healthcare,
  consumer/retail, industrials, energy, communications/media, growth/momentum) built entirely
  from well-known, already-liquid, already-listed large-cap US common stocks (never
  invented/illiquid tickers) so this static fallback is safe to use on its own.
  `allow_leveraged_etfs` stays `False` — no TQQQ/SOXL/leveraged product anywhere in the
  widened universe (verified by `tests/test_wave_g_hit_scale.py` against
  `risk_manager.LEVERAGED_ETFS`/`MOONSHOTS`). This widened list is the **fallback** for when
  no scan result or explicit ticker list is available; the **primary** way a HIT run reaches
  "hundreds" is the market scanner or an explicit ticker list, exactly as documented above.
- `app/backend/models/schemas.py` (`PaperRunRequest`), `app/backend/routes/automation.py`
  (`CronRecipeBody`, `SwarmScanRequest`, `ApplyScanRequest`, `HitPulseRequest`), and
  `app/backend/routes/cron.py` (`CronPaperRunRequest`, `CronSwarmScanRequest`,
  `CronHitPulseRequest`) — every hardcoded `15`/`20`-ticker request-body ceiling that would
  have blocked a hundreds-scale ask is now either raised to the hit ceiling directly, or
  gated by a `model_validator` that reads the sibling `mode`/`preset` field: `mode`/`preset`
  `"hit"` unlocks up to the hit ceiling; every other mode/preset keeps the original,
  unchanged 15/20-ticker cap (a mis-typed huge list for swing/day still fails fast).
- **Ops-visible universe/ticker counts** (ties into the G2 Ops-visible amendment above):
  `GET /api/automation/hit/ops` now always includes `hit_universe_size` (the widened static
  universe's real size) and `hit_max_tickers` (the request ceiling); `last_pulse` gains
  `ticker_count`. `HitOpsPanel` renders a `HIT universe: N names` badge and shows the last
  pulse's actual ticker count next to its fast/slow badge — so a Reviewer/James can see
  "hundreds" without counting a JSON array by hand. `GET /api/automation/status` gains
  `apply_cap_effective` (the current recipe's own resolved cap) and `hit_apply_cap`.

**Explicitly unchanged:** the F2/G3 cost gate (still mandatory on every HIT execute attempt),
the execute dual gate (`SWARM_HIT_EXECUTE` ∧ explicit request, byte-for-byte), every `hit`
risk cap (`max_position_pct`, `stop_loss_pct`, `max_sector_pct`, `max_open_positions`,
`min_cash_pct`, `flatten_eod`/`flatten_by`, and the t175u `max_trades_per_day` override),
`allow_leveraged_etfs: False`, and every "not true HFT / not colocated" claim in this doc and
`docs/WAVE_F_HIT.md`. This add-on raises *how many tickers* a HIT run may consider — nothing
about latency claims, execution venue, or risk-per-trade/day.

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
| `SWARM_HIT_MAX_TICKERS` | `300` | James t180u — ceiling `hit_service.run_hit_pulse`'s `top_n` may request/allow (was hardcoded 15) |
| `SWARM_HIT_SCAN_MAX_TICKERS` | `300` | James t180u — ceiling `scan_market.scan()`'s `max_tickers` may request/allow for a HIT-scale scan |
| `SWARM_HIT_APPLY_RECIPE_MAX` | `300` (floor `200`) | James t180u — ceiling the cron recipe / `apply_scan_to_recipe` may hold when mode/preset is hit (was 15/20) |

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

# G2 Ops-visible amendment — fast/slow analyst labels + last pulse's path,
# always present even before a pulse runs (surfaced in HitOpsPanel)
curl -sS https://<host>/api/automation/hit/ops | \
  jq '.fast_default, .fast_path_analyst_ids, .slow_path_analyst_ids, .last_pulse.fast, .last_pulse.analyst_ids'

# G3 — cost-gate response now reports quote_age_ms / max_quote_age_ms on rejects
curl -sS https://<host>/api/automation/hit/ops | jq '.recent_cost_gate_rejects'

# G4 — decision→submit→ack→fill breakdown on the Ops HIT strip
curl -sS https://<host>/api/automation/hit/ops | jq '.recent_fill_latencies, .latency_note'

# James t180u — HIT-scale pulse: 250 tickers, still analysis-only
curl -sS -X POST -H "Content-Type: application/json" -d '{"top_n": 250}' \
  https://<host>/api/automation/hit/pulse | jq '.ticker_count, .fast, .auto_fast_override'

# James t180u — Ops-visible universe/ticker counts (HitOpsPanel's "HIT
# universe: N names" badge reads these two fields)
curl -sS https://<host>/api/automation/hit/ops | jq '.hit_universe_size, .hit_max_tickers'

# James t180u — hit-scale scan + apply (hundreds, not 15)
curl -sS -X POST -H "Content-Type: application/json" -d '{"mode": "hit"}' \
  https://<host>/api/automation/swarm-scan | jq '.candidate_count'
curl -sS -X POST -H "Content-Type: application/json" -d '{"mode": "hit"}' \
  https://<host>/api/automation/swarm-scan/apply | jq '.cap, .applied_count'

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
execute dual gate's truth table is unchanged; the `strategies-ux-15` build-info flags
(`hit-fast-path`, `hit-quote-freshness-gate`, `hit-quote-ws-optional`,
`hit-latency-observatory`); and — G2 Ops-visible amendment — that `read_hit_ops()` always
includes the fast/slow analyst labels even with no pulse yet today, that `record_hit_run`
persists `fast`/`analyst_ids` on `last_pulse` (and leaves both `None` when a caller omits
them — never guessed), that `paper_run_service` derives `fast` from the run's actual resolved
analyst set (source-level check), that `strategies-ux-16` + `hit-fast-path-ops-visible` are
present, and that `docker-compose.yml` no longer references the prior tag.

`tests/test_wave_g_hit_scale.py` (James t180u) covers: `scan_market.HIT_MAX_TICKERS` ≥ 250
and `DEFAULT_MAX_TICKERS` unchanged (25); `scan()`'s raw movers/most-actives pull scaling with
`max_tickers` and `get_snapshots()`'s chunking (no truncation to 50); `automation_store`'s
`HIT_APPLY_RECIPE_MAX` ≥ 200 and `apply_recipe_max_for` returning the hit ceiling only for
mode/preset `"hit"`; that a hit-mode/preset recipe write persists hundreds of tickers while a
swing/day write still clamps to 20 (unchanged); `apply_scan_to_recipe`'s mode-aware default
cap (hundreds for hit, 15 unchanged for swing/day) and that `mode="hit"` stamps the saved
recipe; `run_swarm_scan`'s `max_tickers=None` resolving to `HIT_MAX_TICKERS` for hit vs.
`DEFAULT_MAX_TICKERS` otherwise; `hit_service.run_hit_pulse`'s raised ceiling (up to
`HIT_MAX_TICKERS`, default request size unchanged at 10), the `ticker_count` field, and the
auto-fast override (an explicit `fast=False` with >30 tickers is overridden back to
`fast=True`, reported via `auto_fast_override`, while ≤30-ticker slow-path requests are
honored unchanged); the widened `MODES["hit"]` universe (115 tickers, no leveraged-ETF or
moonshot overlap, `allow_leveraged_etfs` still `False`); the request-model ceilings/validators
in `schemas.PaperRunRequest`, `routes/automation.py`, and `routes/cron.py` (hit unlocks
hundreds; every other mode/preset keeps the original 15/20-ticker cap); the new
`hit-hundreds-scale` build-info flag; and the Ops-visible `hit_universe_size`/`hit_max_tickers`
fields on `GET /api/automation/hit/ops`.

```bash
poetry run pytest tests/test_wave_g_latency_max.py tests/test_wave_g_hit_scale.py -q
```
