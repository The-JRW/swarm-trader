> Wave F interim doc for The-JRW/swarm-trader. Cross-links:
> [STRATEGIES_UI.md](./STRATEGIES_UI.md) · [CONTROL_WAVE_B.md](./CONTROL_WAVE_B.md) ·
> [WAVE_C_ORCHESTRATOR.md](./WAVE_C_ORCHESTRATOR.md) · [WAVE_D.md](./WAVE_D.md) ·
> [WAVE_E.md](./WAVE_E.md) · [AUTOMATION_A1_A2.md](./AUTOMATION_A1_A2.md) ·
> [WAVE_G_LATENCY_MAX.md](./WAVE_G_LATENCY_MAX.md)
>
> **Wave G follow-up (t178u):** [WAVE_G_LATENCY_MAX.md](./WAVE_G_LATENCY_MAX.md) pushes this
> stack as close to colocated µs HFT as a paper/broker-REST system honestly can — which is
> **not very close** — via a fast analyst path, quote-freshness rejection (+ optional
> read-only quote WS), and a decision→submit→ack→fill latency observatory. Read that doc's
> honesty section alongside this one; nothing below about HIT ≠ true HFT changes.

# Wave F (F1–F6) — HIT: High-frequency Intraday Turnover

Paper-only follow-up to Waves A–E for **The-JRW/swarm-trader**. Image tag: `strategies-ux-15`.
Feature flags: `hit-mode`, `hit-cost-gate`, `hit-pulse-cron`, `hit-ops-strip`,
`hit-dry-run-streak` (see `GET /build-info`). Wave G adds `hit-fast-path`,
`hit-quote-freshness-gate`, `hit-quote-ws-optional`, `hit-latency-observatory` — see
[WAVE_G_LATENCY_MAX.md](./WAVE_G_LATENCY_MAX.md).

## HIT ≠ true HFT — read this first

**HIT stands for High-frequency *Intraday Turnover*, not High-Frequency Trading.** This wave
was scoped from research (see below) that concluded true HFT — microsecond-to-millisecond
edges built on co-location, queue priority, and maker/taker rebates — is not something an
Alpaca paper REST + LLM-agent swarm can honestly claim. Retail API round-trips run
50–500ms; that is only useful when an edge persists **more than ~10x** that latency, which
points at **minutes-to-hours** holds (VWAP bands, short momentum, cost-aware mean reversion),
not tick-level scalping. Several published "high-frequency momentum/contrarian" studies also
look profitable only *before* realistic costs — bid-ask bounce is easy to mistake for mean
reversion. HIT is built around that honesty: a higher-turnover, tighter-risk sibling of `day`
mode with a **mandatory pre-execute cost gate**, not a latency-arb engine.

**Every surface introduced by this wave — UI copy, docs, API responses — says "HIT" or
"High-frequency Intraday Turnover" and never claims true HFT, sub-millisecond execution,
co-location, or queue priority.**

**Reviewer binding: paper-only throughout, with binding amendments applied.** This wave does
not set `SWARM_MONITOR_DRY_RUN=false`, does not set `SWARM_AUTO_LAUNCH=true`, does not enable
a hot HIT execute path by default, does not touch live trading, and does not raise any risk
cap beyond what is documented below. Specifically, per Reviewer `APPROVE_WAVE_F`:

1. HIT ≠ true HFT — never claim µs/co-location edges in UI or docs (see above).
2. The F2 cost gate is **mandatory** on any HIT execute attempt (no bypass, fail-closed on error).
3. `/cron/hit-pulse` is analysis-only by default; execute only with `SWARM_HIT_EXECUTE` **∧**
   an explicit per-request/recipe ask (dual gate, same pattern as B1/C4). Cadence is
   Scheduler/cron-owned — documented here, never hardcoded into the route.
4. `hit` mode ships with `allow_leveraged_etfs: false` — no TQQQ/SOXL (or any leveraged ETF)
   in the default HIT universe.
5. F6 is streak + ack **records only** — there is no UI control anywhere that flips
   `SWARM_HIT_EXECUTE` (mirrors A2/E1's `SWARM_MONITOR_DRY_RUN` precedent exactly).
6. Explicit hard outs: co-location / LOB latency arb, live trading, flipping
   `SWARM_MONITOR_DRY_RUN` to `false`, `SWARM_AUTO_LAUNCH=true`, or raising any risk cap beyond
   what F1 documents. Paper-only.

> **Update (James override, t175u):** the above reflects the original `APPROVE_WAVE_F`
> sign-off. James has since overridden amendment #6's trade-count portion for **paper HIT
> only** — see "James override — trade-count ceiling (t175u)" under F1 below. All other
> amendments (1–5, and the rest of #6: no live trading, no `SWARM_MONITOR_DRY_RUN=false`,
> no `SWARM_AUTO_LAUNCH=true`, no leveraged ETFs, mandatory cost gate) remain fully in force.

## Scope F1–F6

### F1 — `hit` trading mode (sibling of `day`)

`src/config.py` `MODES["hit"]` — liquid-only universe (mega-cap + SPY/QQQ only; **no**
TQQQ/SOXL or any other leveraged ETF by default):

| Risk field | `day` | `hit` | Direction |
|---|---|---|---|
| `max_position_pct` | 0.15 | **0.07** | smaller per-name |
| `max_trades_per_day` | 20 | **5000** ¹ | practically unlimited turnover (was 50) |
| `max_open_positions` | 8 | **13** | more, smaller positions |
| `stop_loss_pct` | 0.012 | **0.009** | tighter stop |
| `flatten_by` | 15:45 | **15:30** | earlier flatten |
| `min_cash_pct` | 0.10 | **0.15** | higher cash buffer |
| `allow_leveraged_etfs` | true | **false** | Reviewer amendment — no TQQQ/SOXL |

¹ **James override (t175u), supersedes the Reviewer's original 50/day cap — see below.**

Universe: `mega_cap` (NVDA, AVGO, TSM, AMD, MSFT, AAPL, META, GOOGL, AMZN — same liquid names
as `day`) + `index_anchors` (SPY, QQQ only). No `momentum` or `etf_direction` (leveraged)
buckets — that is what makes `allow_leveraged_etfs: false` binding: the buckets that would
carry TQQQ/SOXL simply are not in the HIT universe.

`hit` is wired everywhere `swing`/`day` already were: `resolve_mode()` / `get_mode_config()`
(generic, no change needed), the Trading-mode picker + human-override + recipe mode (Strategies
UI), `GET /api/automation/risk-policy?mode=hit` (D2 risk-policy panel), the cron/automation
mode validators, `gather_data.py --mode hit` (reuses the `day` intraday-technicals path: 5-min
bars, VWAP, RSI, `feed=iex`; daily bars still prefer SIP per the existing feed defaults),
`risk_manager.py --mode hit`, and `portfolio_monitor.py --mode hit`. `hit` has no dedicated
Alpaca account — `src/accounts.get_account_for_mode("hit")` routes to the `day` account
(intraday, flattens EOD) with a `swing` fallback, exactly like `day`'s own fallback.

Paper-only; refuses live exactly like every other mode (`assert_paper_only()` /
`alpaca_trading_mode() == "live"` checks are unchanged and apply to `hit` identically).

#### James override — trade-count ceiling (t175u)

The Wave F Reviewer's original `APPROVE_WAVE_F` sign-off capped `hit` at **50 trades/day**
(amendment #6: "no risk cap raised beyond what F1 documents"). James (repo owner) has since
overridden that specific cap: **"fuck HIT cap, there is no cap"** — for **paper HIT only**.
`MODES["hit"]["risk"]["max_trades_per_day"]` is now `5000` (practically unlimited for a
single trading day; `risk_manager.validate_trade`'s Rule 6 check is `>=` this value, so it
is not a hard `0`/no-op, just no longer a meaningful ceiling for paper churn). The
informational `safety_rails.max_trades_per_run` hint in `gather_data.py`'s HIT payload was
raised to match (`5000`) so agent-facing context doesn't advertise a stale 50-trade cap.

**Everything else from the Reviewer's amendments is unchanged and still enforced in code:**
`stop_loss_pct`, `trailing_stop_pct`, `daily_loss_limit`, `weekly_loss_limit`,
`no_buy_if_down_pct`, `max_position_pct`, `max_sector_pct`/per-bucket sector caps,
`max_open_positions`, `min_cash_pct`, `flatten_eod`/`flatten_by`, `allow_leveraged_etfs: false`
(no TQQQ/SOXL), the mandatory F2 cost gate, and paper-only (`assert_paper_only()`). Raising
*how many* trades can happen is not the same as raising *how much* can be risked per trade or
per day — those caps are exactly where James asked to keep them (many small trades under the
existing `max_position_pct`, not fewer/larger reckless ones). HIT is still **not** true HFT —
see "HIT ≠ true HFT" above; this override changes a paper trade-count ceiling, nothing about
latency, co-location, or execution venue claims.

### F2 — Cost / microstructure gate (pre-execute, mandatory on HIT)

`app/backend/services/cost_gate_service.py` — a coarse, documented heuristic gate, **not** a
limit-order-book model. Two checks, either of which blocks a proposed **entry** (buy/short
only; exits/holds always pass through untouched):

1. **Estimated round-trip cost** (2x half-spread) **≥** `SWARM_HIT_COST_GATE_BPS` (default 15bps).
   Half-spread comes from a live Alpaca quote (`src/tools/alpaca_data.get_latest_quote`) when
   available; otherwise a ticker-class default (2.5bps single names, 1.0bps SPY/QQQ) — always
   labeled `ticker_class_default_assumed`, never presented as measured data.
2. This trade would push **same-day gross turnover** over `SWARM_HIT_TURNOVER_BUDGET_PCT`
   (default 200% of equity/day).

Blocked entries are downgraded to `action="hold", quantity=0` before execution and tagged
`rule="cost_gate"` in `trade_results` (visible in the Strategies run view, the Ops HIT strip,
and the F6 streak summaries). **Reviewer amendment #2: this gate is mandatory, not optional,
on any HIT execute** — `paper_run_service.execute_paper_run` applies it automatically whenever
`mode == "hit"` and execute is effectively on, for every entry point (Strategies UI Run,
`/api/automation/hit/pulse`, and `/cron/hit-pulse` all funnel through the same paper-run path).
**Fail-closed on gate error**: if the gate itself raises (e.g. a network error fetching quotes),
every new entry that run is blocked rather than silently passed through — exits still work.

### F3 — HIT pulse cron (`POST /cron/hit-pulse`)

Secured exactly like every other `/cron/*` route (`X-Swarm-Cron-Secret` via
`require_cron_secret` — missing/wrong secret → 401 FAIL_CLOSED, never echoes the secret).
Default: **scan-lite + analysis-only** (no execute). `execute_trades` in the request body is
honored only when **both** the request sets it `true` **and** `SWARM_HIT_EXECUTE` is truthy
(dual gate, same pattern as B1's `SWARM_CRON_EXECUTE_TRADES` and C4's `SWARM_AUTO_LAUNCH`).
Reuses `paper_run_service.create_run_record` + `start_paper_run_async` — no parallel execution
path, no bypass of `risk_manager.validate_trade` or the F2 cost gate.

A UI-facing twin, `POST /api/automation/hit/pulse`, exists for manual/Strategies-UI-triggered
pulses (no cron secret required — same as the rest of `/api/automation/*`); it shares the same
`run_hit_pulse()` service function and the same dual-gated execute semantics.

**Cadence is Scheduler-owned** — this route does not self-schedule. An operator wires an
external cron/Scheduler to call it (e.g. every ~15 minutes during RTH); the secret and the
cadence both live outside this codebase, matching A1/A2's documented pattern.

### F4 — HIT strategy preset + agents

Preset `hit` (alongside `core`/`value`/`growth`/`quant`) in the cron recipe, `/cron/paper-run`,
`/cron/hit-pulse`, and the Strategies UI preset picker: `technical_analyst` + `market_regime` +
`autoresearch` + `sentiment_analyst`. The **ordering is intentional** — deterministic/fast
signal classes (technical, market-regime) are listed ahead of heavier LLM-driven research
(autoresearch, sentiment) wherever the codebase already has that distinction, matching HIT's
short (minutes-hours) holding horizon. This is a preference in preset composition, not a claim
of sub-second decisioning — every HIT run still goes through the same
`paper_run_service.execute_paper_run` → `run_hedge_fund` → conviction-digest → risk_manager
pipeline as every other mode. No bypass of `risk_manager` (no LLM override of hard risk rules).

**Wave G / G2 formalizes and extends this** with a `fast` flag (default `true`, matching this
preset unchanged) and an explicit, opt-in-only slow path (`apex` + `news_sentiment_analyst`,
one full LLM call per ticker each) — see
[WAVE_G_LATENCY_MAX.md](./WAVE_G_LATENCY_MAX.md#g2--fast-hit-path).

### F5 — Session HIT Ops strip

`app/backend/services/hit_ops_service.py` persists a small daily counter file
(`/app/data/automation/hit_ops.json`, resets at midnight) so the Ops/Book UI can show
same-day HIT activity **without a live WebSocket connection**:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/automation/hit/ops` | Trades today, gross turnover $, cost-gate reject count, last pulse |

Every number is either a direct pass-through of a real trade result or an explicit sum of
them — turnover in particular only counts legs where a real reference price was available
(from the F2 cost-gate quote fetch); legs without one are simply **not counted**, never
estimated as if measured. Fill-latency timestamps (`submitted_at` / `filled_at`) are copied
through only when Alpaca's own order response included them (`src/alpaca_integration.py`'s
`_place_alpaca_order` does one best-effort follow-up `GET /orders/{id}` when the initial
response has no `filled_at` yet) — **blank when missing, never fabricated**. There is no
order/`trade_updates` WebSocket client in this codebase, in this wave or Wave G (see below);
F5 polls a persisted summary instead of holding a live order-stream connection, which also
sidesteps Alpaca's one-connection-per-account limit on `trade_updates` entirely. The Ops HIT
strip card (`HitOpsPanel`) never crashes when there is no pulse yet — every field renders a
safe blank ("No HIT pulse yet today.") rather than throwing.

**Wave G / G3 adds an *optional*, off-by-default, read-only *market-data* WebSocket** (quotes
only — still never an order/`trade_updates` stream) with single-connection discipline, and
**Wave G / G4 extends fill-latency into a decision→submit→ack→fill breakdown**, surfaced in
this same strip. See [WAVE_G_LATENCY_MAX.md](./WAVE_G_LATENCY_MAX.md#g3--quote-freshness) and
[#g4--latency-observatory](./WAVE_G_LATENCY_MAX.md#g4--latency-observatory).

### F6 — HIT dry-run streak (mirrors A2/E1)

`app/backend/services/hit_dry_run_streak_service.py` persists a **weekday** streak counter
plus the last would-fire/blocked/cost-gate summaries under
`/app/data/automation/hit_dry_run_streak.json` — the same mechanics as A2/E1's dry-run streak,
scoped to HIT paper runs instead of the portfolio monitor:

- Every completed `mode == "hit"` paper run that did **not** hot-execute (`dry_run=True`, the
  default/common case) records one weekday event; a same-day repeat is idempotent.
- An unexpected error (exception in `execute_paper_run`) resets the streak to 0.
- A missed weekday restarts the streak at 1 rather than continuing it.
- `ack` records a James/Reviewer sign-off note **for the record only**.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/automation/hit-dry-run-streak` | Streak count, target (5), last summaries, ack state |
| `POST` | `/api/automation/hit-dry-run-streak/ack` | Record a James/Reviewer ack (`{by, note}`) |
| `POST` | `/api/automation/hit-dry-run-streak/clear-ack` | Clear a previously recorded ack |

**Reviewer amendment #5 — no UI control here (or anywhere) flips `SWARM_HIT_EXECUTE`.** Streak
+ summaries + ack are records only; setting the env var hot still requires a human to change
the Elestio environment directly. `HitDryRunStreakPanel` (Book pane) shows the same 5-dot
checklist + would-fire/blocked/cost-gate summaries + ack form pattern as A2/E1's
`DryRunStreakPanel`, with no execute-toggle anywhere in it.

## Hard outs (unchanged / Reviewer amendment #6)

- No co-location, no FPGA, no maker market-making, no latency arb across venues, no
  tick/LOB-imbalance engine — see "HIT ≠ true HFT" above.
- No live trading — every HIT route/service reuses the same `assert_paper_only()` /
  `alpaca_trading_mode() == "live"` refusals as every other paper route.
- `SWARM_MONITOR_DRY_RUN` is never set to `false` by any code in this wave.
- No `SWARM_AUTO_LAUNCH=true` — unrelated to HIT; unchanged from Wave C/E.
- HIT execute stays dual-gated off by default: `SWARM_HIT_EXECUTE` absent/false means
  `/cron/hit-pulse` and `/api/automation/hit/pulse` are always analysis-only regardless of the
  request body.
- No risk cap raised beyond what F1 documents above, **except** `max_trades_per_day` — see
  "James override — trade-count ceiling (t175u)" above. `max_position_pct`, `stop_loss_pct`,
  `max_sector_pct`, `max_open_positions`, `min_cash_pct`, etc. for `hit` are all still inside
  or tighter than `day`'s existing philosophy, and `allow_leveraged_etfs` is explicitly
  `false`.
- No invented alpha, turnover, or latency numbers anywhere — see F5's "never fabricated" note.

## Env (new; all optional, safe defaults)

| Env | Default | Notes |
|-----|---------|-------|
| `SWARM_HIT_EXECUTE` | `false` | Dual gate for HIT cron/UI execute (mirrors `SWARM_CRON_EXECUTE_TRADES`) |
| `SWARM_HIT_COST_GATE_BPS` | `15` | F2 — round-trip cost budget in bps before a HIT entry is blocked |
| `SWARM_HIT_TURNOVER_BUDGET_PCT` | `200` | F2 — same-day gross turnover budget, percent of equity |

No other env var is added or changed by this wave. `SWARM_MONITOR_DRY_RUN`,
`SWARM_AUTO_LAUNCH`, `SWARM_CRON_EXECUTE_TRADES`, and `ALPACA_TRADING_MODE` keep their
Wave A–E defaults (see `CONTROL_WAVE_B.md`, `WAVE_C_ORCHESTRATOR.md`, `WAVE_E.md`). Wave G
adds two more (`SWARM_HIT_MAX_QUOTE_AGE_MS`, `SWARM_HIT_QUOTE_WS_ENABLED`), both with safe
defaults — see [WAVE_G_LATENCY_MAX.md](./WAVE_G_LATENCY_MAX.md#env-new-all-optional-safe-defaults).

## Smoke

```bash
# F1 — HIT risk policy (display-only hard caps)
curl -sS 'https://<host>/api/automation/risk-policy?mode=hit' | jq '.caps, .blocklists'

# F3 — cron hit-pulse: 401 without secret
curl -sS -X POST https://<host>/api/cron/hit-pulse
# → 401 FAIL_CLOSED

# F3 — analysis-only pulse (default)
curl -sS -X POST \
  -H "X-Swarm-Cron-Secret: $SWARM_CRON_SECRET" \
  -H "Content-Type: application/json" \
  -d '{}' \
  https://<host>/api/cron/hit-pulse

# F5 — Ops HIT strip
curl -sS https://<host>/api/automation/hit/ops | jq '.trades_today, .turnover_today, .cost_gate_rejects_today, .last_pulse'

# F6 — HIT dry-run streak
curl -sS https://<host>/api/automation/hit-dry-run-streak | jq '.consecutive_weekday_count, .target, .ack'

# Build stamp
curl -sS https://<host>/api/build-info | jq '.image_tag, .features'
```

## Tests

`tests/test_wave_f_hit.py` covers: `MODES["hit"]` risk caps vs `day` (smaller max position,
higher max trades, more open positions, tighter stop, earlier flatten, higher min cash, no
leveraged ETFs, no TQQQ/SOXL in the HIT universe); the F2 cost gate blocking a synthetic
high-cost trade (wide spread) and a synthetic turnover-budget breach, while approving a
tight-spread trade and passing exits through untouched; `require_cron_secret` still 401s
`/cron/hit-pulse` without a valid secret; the F3 dual-gate resolution
(`hit_execute_env_allows` / `resolve_hit_execute`); the F5 ops strip's daily reset, honest
turnover accumulation (only priced legs counted), and "never crashes without a pulse yet"
default state; the F6 weekday streak counter (increment / reset-on-error / reset-on-gap /
ack record-only); a source-level guarantee that no HIT service ever references
`SWARM_MONITOR_DRY_RUN` or writes it, and that no service writes `SWARM_HIT_EXECUTE`; the
`strategies-ux-15` build-info flags; the paper-only compose defaults; and (James override,
t175u) that `hit`'s `max_trades_per_day` is now effectively unlimited (`5000`) while every
other `hit` risk rail stays exactly as F1 documents.

```bash
poetry run pytest tests/test_wave_f_hit.py -q
```

Wave G adds `tests/test_wave_g_latency_max.py` — see
[WAVE_G_LATENCY_MAX.md](./WAVE_G_LATENCY_MAX.md#tests).
