> Wave E interim doc for The-JRW/swarm-trader. Cross-links:
> [STRATEGIES_UI.md](./STRATEGIES_UI.md) · [CONTROL_WAVE_B.md](./CONTROL_WAVE_B.md) ·
> [WAVE_C_ORCHESTRATOR.md](./WAVE_C_ORCHESTRATOR.md) · [WAVE_D.md](./WAVE_D.md) ·
> [AUTOMATION_A1_A2.md](./AUTOMATION_A1_A2.md)

# Wave E (E1–E6) — dry-run checklist, real perf snapshots, session digests, mode auto-resolver, redeploy assist, AutoResearch review queue

Paper-only follow-ups to Waves A–D for **The-JRW/swarm-trader**. Image tag: `strategies-ux-13`.
Feature flags: `dry-run-streak-checklist`, `perf-snapshot-details`, `session-digest-center`,
`mode-auto-resolver`, `empty-book-redeploy-assist`, `autoresearch-review-queue` (see
`GET /build-info`).

**Reviewer binding: paper-only throughout.** This wave does not set
`SWARM_MONITOR_DRY_RUN=false`, does not set `SWARM_AUTO_LAUNCH=true`, does not enable a hot
cron execute path, does not touch live trading, does not add the A6 Flow worker, and E6 is a
display/UX-only stub that never auto-applies AutoResearch params to production config.

## E1 — A2 dry-run streak / exit checklist

`app/backend/services/dry_run_streak_service.py` persists a **weekday** dry-run streak counter
plus the last would-fire summaries under `/app/data/automation/dry_run_streak.json`.

- Every `POST /api/cron/portfolio-monitor` call with `dry_run=true` records one event (weekday
  only; a same-day repeat is idempotent).
- An unexpected error (exception, not a normal would-fire stop action) resets the streak to 0 —
  matching the exit criteria in [AUTOMATION_A1_A2.md](./AUTOMATION_A1_A2.md#dry-run-week-exit-criteria-a2).
- A gap (a missed weekday) restarts the streak at 1 rather than continuing it.
- `ack` records a James/Reviewer sign-off note for the record only.

**No UI control here (or anywhere) flips `SWARM_MONITOR_DRY_RUN`.** Streak + summaries + ack are
records only; setting the env var hot still requires a human to change the Elestio environment
directly.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/automation/dry-run-streak` | Streak count, target (5), last summaries, ack state |
| `POST` | `/api/automation/dry-run-streak/ack` | Record a James/Reviewer ack (`{by, note}`) |
| `POST` | `/api/automation/dry-run-streak/clear-ack` | Clear a previously recorded ack |

Ops UI (Book pane): a 5-dot checklist, last would-fire summaries, and an ack form. No control
that flips the env var exists anywhere in this UI.

## E2 — Perf strip α + snapshot Details

The perf strip (`PerformanceDashboard`) already showed α vs SPY **only** when
`GET /api/portfolio/performance` has real snapshot/benchmark data (Wave B4) — this wave wires a
real **Details** drawer on top of it instead of the previous disabled placeholder button.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/portfolio/performance/snapshots?limit=30` | Recent real snapshots (E2) |

Every row is a pass-through of a real `performance_snapshot_service` write (equity/cash from
Alpaca, SPY/QQQ from yfinance when available) — **never a fabricated zero**. Missing days are
simply absent, not filled in. The drawer table shows date, equity, day P/L, SPY day change, and
α vs SPY (blank when the day lacks real benchmark data).

## E3 — Session digest center

After **any** paper run (Strategies UI or cron — both flow through
`paper_run_service.execute_paper_run`), a durable digest is built from **real run fields only**:
`action_counts`, decision count, the existing conviction digest (B3, already computed from real
`analyst_signals`), and `trade_results` filled/blocked counts. **No invented scores.**

Persisted at `/app/data/automation/session_digests.jsonl` (last 20), mirroring the
`scan_history.jsonl` pattern from Wave C.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/automation/session-digests?limit=10` | Recent digests, newest first |

Surfaced in the Book pane's **Session digest center**, which deep-links back into run history
(`onViewRun` — the same mechanism `BookRecords` already uses) via `run_id`.

## E4 — Mode auto-resolver lite

Previously, `mode=auto` silently fell back to `swing` in every consumer (paper runs, the
portfolio monitor, performance snapshots) with no recorded reason. `src/mode_resolver.py` now
implements the **documented** `auto_rules` from `trading_mode.json` as a pure, unit-testable
function:

- **day** when: an operator-flagged event day (`trading_mode.json` `"event_day": true` —
  earnings/FOMC/CPI, lite/manual for now), VIX > 25, or SPY morning gap > 1%
- **swing** when: VIX < 20, or as the default safer baseline when signals are inside the
  neutral band or unavailable

`app/backend/services/mode_resolver_service.py` gathers best-effort VIX/SPY-gap signals via
yfinance (never invents a number — missing data stays `None` and the rule falls through to an
honest "insufficient data" reason), and persists the resolution + reason to
`/app/data/automation/mode_resolution.json`.

**Human override always wins.** The resolver checks `trading_mode.json`'s active `override`
first and, if present, reports `active: "override"` without computing anything. An explicit
`mode: "swing"|"day"` (not `"auto"`) is reported as `active: "explicit"`. Only `mode: "auto"`
with no override triggers a fresh VIX/gap/calendar computation (`active: "auto"`).

Wired into:

- `paper_run_service.execute_paper_run` — when the run's mode is `auto`, resolves via this
  service instead of the old hardcoded `mode = "swing"`, and stores the resolution + reason on
  the run's `summary.mode_auto_resolution` (surfaced in Strategies results and the E3 digest).
- `GET /trading/mode` — returns the last persisted resolution as `auto_resolution` (cheap cache
  read, no network call on every page load).
- `POST /trading/mode` — recomputes immediately (`force=True`) after a human changes mode or
  override, so the UI shows a fresh reason rather than a stale one.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/automation/mode-resolution` | Last persisted resolution (cheap) |
| `POST` | `/api/automation/mode-resolution/refresh` | Force a fresh VIX/gap/calendar computation |

Strategies' Trading mode card shows the resolved mode, the real reason, the raw signals used
(VIX / gap % / event day), and a **Refresh reason** button. Human override still wins exactly as
before (Wave B5) — nothing here changes that precedence.

**Not implemented (lite scope):** "portfolio has >3 positions approaching stop loss" from the
documented rules needs live position data and is deferred; the event-day calendar is a manual
`trading_mode.json` flag rather than a wired earnings/FOMC/CPI feed.

## E5 — Empty-book redeploy assist

`app/backend/services/redeploy_assist_service.py` computes a **display-only** suggestion when
the paper book has zero positions and cash sits above a sensible threshold
(`SWARM_EMPTY_BOOK_CASH_THRESHOLD`, default **$1,000**):

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/automation/redeploy-suggestion` | `{suggest, positions_count, cash, threshold, message}` |

The Run pane shows a banner suggesting the existing **Scan → Apply → Launch analysis** path
(the same buttons already on the Ops card) when `suggest` is true. The banner's only action is
**Scan market** — it never applies a recipe or launches a run by itself, and **execute remains
dual-gated off by default** exactly as everywhere else
(`SWARM_CRON_EXECUTE_TRADES` ∧ recipe/request `execute_trades`).

## E6 — AutoResearch review queue (stub)

`app/backend/services/autoresearch_review_service.py` reads the **existing** offline evolution
loop's own artifacts —`autoresearch/experiments/log.jsonl` (per-experiment fitness/hypothesis/
metrics/`kept`) and `autoresearch/experiments/runs.jsonl` (per-run baseline/best fitness,
`keep_count`) — and exposes them as an in-app review queue.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/automation/autoresearch/queue?limit=20` | Recent experiments + last 5 runs |
| `GET` | `/api/automation/autoresearch/runs?limit=10` | Recent evolution run summaries |
| `POST` | `/api/automation/autoresearch/review` | Record `approved`/`rejected`/`pending` (display only) |

**Approve/reject is display/UX only.** The recorded decision is a note
(`/app/data/automation/autoresearch_review.json`, `applied: false` always) attached to an
`experiment_id` for the record. It:

- **Never** writes `autoresearch/strategy.py` (the file `evolve.py` itself already edits
  offline when it keeps an experiment — this queue does not change or gate that behavior).
- **Never** touches `trading_mode.json`, `cron_recipe.json`, or any other production config.
- **Never** triggers `evolve.py` or a backtest from the app.

Surfaced in the Book pane, adjacent to the other Ops/automation records
(`AutoResearchReviewPanel`).

## Hard outs (unchanged)

- No A2 hot path: `SWARM_MONITOR_DRY_RUN` is never set to `false` by any code in this wave.
- No `SWARM_AUTO_LAUNCH=true` — cron `swarm-scan` stays scan-only unless an operator flips the
  env directly.
- No cron execute hot path — the dual gate (`SWARM_CRON_EXECUTE_TRADES` ∧ recipe/request
  `execute_trades`) is untouched.
- No live trading — every new endpoint reuses the same `assert_paper_only()` /
  `alpaca_trading_mode() == "live"` refusals as existing routes where it fetches Alpaca data.
- No A6 Flow worker — out of scope, not started.
- No E6 auto-apply — see above; approve/reject is a note, not a config write.

## Env (new; all optional, safe defaults)

| Env | Default | Notes |
|-----|---------|-------|
| `SWARM_EMPTY_BOOK_CASH_THRESHOLD` | `1000` | E5 — cash threshold for the redeploy banner |

No other env var is added or changed by this wave. `SWARM_MONITOR_DRY_RUN`,
`SWARM_AUTO_LAUNCH`, `SWARM_CRON_EXECUTE_TRADES`, and `ALPACA_TRADING_MODE` keep their Wave A–D
defaults (see `CONTROL_WAVE_B.md`, `WAVE_C_ORCHESTRATOR.md`, `WAVE_D.md`).

## Smoke

```bash
# E1 — dry-run streak
curl -sS https://<host>/api/automation/dry-run-streak | jq '.consecutive_weekday_count, .target, .ack'

# E2 — recent snapshots
curl -sS 'https://<host>/api/portfolio/performance/snapshots?limit=10' | jq '.snapshots'

# E3 — session digests
curl -sS 'https://<host>/api/automation/session-digests?limit=5' | jq '.digests'

# E4 — mode auto-resolution (cached) + forced refresh
curl -sS https://<host>/api/automation/mode-resolution | jq '.resolved_mode, .reason'
curl -sS -X POST https://<host>/api/automation/mode-resolution/refresh | jq '.resolved_mode, .reason'

# E5 — redeploy suggestion
curl -sS https://<host>/api/automation/redeploy-suggestion | jq '.suggest, .message'

# E6 — AutoResearch review queue
curl -sS 'https://<host>/api/automation/autoresearch/queue?limit=10' | jq '.experiments[0]'
curl -sS -X POST -H 'Content-Type: application/json' \
  -d '{"experiment_id":"<id>","decision":"approved"}' \
  https://<host>/api/automation/autoresearch/review

# Build stamp
curl -sS https://<host>/api/build-info | jq '.image_tag, .features'
```

## Tests

`tests/test_wave_e.py` covers: the weekday streak counter (increment / reset-on-error / reset-on-
gap / weekend skip / idempotent same-day), α-vs-SPY gating (never a fake zero, present only with
real snapshot data), the session digest builder (real fields only, no invented scores), the mode
auto-resolver's rule precedence and its "human override always wins" behavior, the redeploy
suggestion's pure threshold logic, the AutoResearch review queue reading real `log.jsonl`/
`runs.jsonl` rows and recording a display-only decision without touching `strategy.py`, the
`strategies-ux-13` build-info flags, and the paper-only compose defaults.

```bash
poetry run pytest tests/test_wave_e.py -q
```
