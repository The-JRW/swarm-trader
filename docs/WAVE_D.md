> Wave D interim doc for The-JRW/swarm-trader. Cross-links:
> [STRATEGIES_UI.md](./STRATEGIES_UI.md) · [CONTROL_WAVE_B.md](./CONTROL_WAVE_B.md) · [WAVE_C_ORCHESTRATOR.md](./WAVE_C_ORCHESTRATOR.md)
>
> **Wave E update:** the dry-run streak checklist, real performance snapshot details, a session
> digest center, a mode auto-resolver (with a persisted reason), an empty-book redeploy banner,
> and an AutoResearch review queue stub land in [WAVE_E.md](./WAVE_E.md) — see that doc for the
> current `strategies-ux-13` build.

# Wave D (D1–D6) — Run/Book IA, risk glance, sector-aware apply, hints

Paper-only Strategies restructure + risk/diversification surfacing for **The-JRW/swarm-trader**.
Image tag: `strategies-ux-12`. Feature flags: `wave-d-strategies-ia`, `run-book-tabs`,
`risk-policy-glance`, `sector-aware-apply`, `conviction-recipe-hints` (see `GET /build-info`).

Reviewer binding: paper-only throughout. This wave does **not** flip
`SWARM_AUTO_LAUNCH`, does **not** set `SWARM_MONITOR_DRY_RUN=false`, does **not** enable
`SWARM_CRON_EXECUTE_TRADES`, and does **not** touch live trading.

## D1 — Strategies Run vs Book IA

Strategies is now two panes behind one tab bar; **Run** is the hero and opens by default.

| Pane | Contains |
|------|----------|
| **Run** (primary) | Trading mode, instrument, presets + analysts, tickers + sticky run CTA, **Ops** (cron recipe, swarm scan → apply → launch), risk policy glance, run results, next-recipe hints |
| **Book** | Paper portfolio (positions, close 25/50/75/100%, recent orders), durable run history, last cron paper-run, last monitor actions, last conviction digest |

- Ops **scan / recipe / launch** stays on the primary Run surface (binding).
- The sticky run status bar is global — it stays visible from either pane.
- Flow graph chrome is labelled **Advanced** (left sidebar header + Strategies copy);
  Strategies remains the easy path.

## D2 — Risk policy glance (read-only)

`GET /api/automation/risk-policy?mode=swing|day|auto` returns the hard caps that
`risk_manager.validate_trade` already enforces, read straight from `src.config.MODES`:

- position + sector caps (`max_position_pct`, `max_sector_pct`, per-bucket sector caps)
- circuit breakers (daily, weekly, no-buy-when-down)
- stops (`stop_loss_pct`, `trailing_stop_pct`), `min_cash_pct`, trade/position counts
- flatten rules (`flatten_eod`, `flatten_by`) and blocklists (leveraged ETFs, moonshots)

**Display only.** The endpoint is `GET`-only, returns `read_only: true`, and there is no
write path, no LLM override, and no way to widen a cap from the UI. Percentages are
rendered from config values — the panel cannot report a looser cap than the enforcer uses.

## D3 — Sector-aware scan → recipe apply

`POST /api/automation/swarm-scan/apply` now diversifies before it fills.

```json
{ "top_n": 15, "sector_aware": true, "mode": "swing" }
```

1. Candidates are mapped to mode-universe sectors (`core_tech`, `growth`, `value_dividend`,
   `tactical`, `hedge`, or `other` for off-universe names).
2. Each sector gets a slot cap derived from its config `max_sector_pct`
   (`floor(pct × slots)`, clamped to ≥1 and ≤ slots). Example at 15 slots in swing:
   `core_tech 4`, `growth 3`, `value_dividend 3`, `tactical 2`, `hedge 2`.
3. Picks round-robin across sectors, **underweight first** — sectors under-represented in
   the current recipe pick before ones already loaded up. Then it fills remaining slots.
4. Hard cap stays **≤15** tickers.
5. `other` (unclassified) is not slot-capped, mirroring `risk_manager` rule 10 which skips
   the `other` bucket. Round-robin still spreads those picks.

Response adds `sectors[]` (picked / slot_cap / max_sector_pct / in_current_recipe),
`skipped[]` with **skip reasons** (`kind: "sector_cap" | "slot_cap"`), `sector_caps_trimmed`,
and `notes[]`. The UI shows the skip reasons whenever sector caps trim tickers.

**Never a silent empty CORE/recipe:** if sector-aware selection yields no picks, apply falls
back to plain scan order and records the fallback in `notes`; an empty write is refused with
a 400 instead of persisting an empty ticker list.

## D4 — Routine cadence (docs only, scan-only)

Weekday cadence below is **Scheduler / external-owned** (Elestio cron, Grok routines, or an
external scheduler). This wave documents it; it does not add an in-app scheduler and does not
change any env value.

| Slot | Weekday time (ET) | Call | Body |
|------|-------------------|------|------|
| Session open | ~09:45 Mon–Fri | `POST /api/cron/swarm-scan` | `{"apply_recipe": false, "launch": false, "intersect_universe": true}` |
| Midday | ~12:30 Mon–Fri | `POST /api/cron/swarm-scan` | same (scan-only) |

```bash
curl -sS -X POST -H "X-Swarm-Cron-Secret: $SWARM_CRON_SECRET" \
  -H 'Content-Type: application/json' \
  -d '{"apply_recipe":false,"launch":false,"intersect_universe":true}' \
  https://<host>/api/cron/swarm-scan
```

Rules for this cadence:

- **`SWARM_AUTO_LAUNCH` stays `false`** (absent/false in compose defaults). With it false, cron
  is **scan-only**: `apply_recipe` / `launch` flags are ignored and reported in `notes`.
- Do **not** flip env as part of this wave. Arming Grok routines is a separate Coder task.
- Execute stays dual-gated (`SWARM_CRON_EXECUTE_TRADES` ∧ recipe/request `execute_trades`) and
  `SWARM_MONITOR_DRY_RUN` stays `true`.
- Applying a scan to the recipe and launching analysis remain **human-triggered** from the
  Strategies Run pane.

## D5 — Conviction → next recipe hints

`GET /api/automation/recipe-hints` reads the last persisted conviction digest and returns
display-only suggestions for the next Apply:

- **contested** tickers rank first (the swarm disagreed — another paper pass is informative)
- then **consensus** tickers, with agree/total in the reason
- **risk-rejected** tickers are never suggested; they are listed under `excluded`
- capped at 15, flags `display_only: true`, `auto_write: false`, `requires_explicit_apply: true`

The Run pane shows these after a paper run with an explicit **Apply hints to recipe** button.
Nothing writes `cron_recipe.json` until that button is pressed — no auto-write.

## D6 — Out of scope

- **Neon upserts** (scan/run/digest persistence to Neon Postgres) stay on the
  **Coder / Keeper** path and are intentionally not implemented in app code here.
  Scan, recipe, digest, and run history remain single-replica JSON under
  `SWARM_AUTOMATION_DIR` (default `/app/data/automation`).
- No Flow autobuild, no A2 `MONITOR_DRY_RUN=false`, no cron execute hot path.

## API summary (added this wave)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/automation/risk-policy` | D2 read-only hard risk caps |
| `GET` | `/api/automation/recipe-hints` | D5 display-only next-recipe suggestions |
| `POST` | `/api/automation/swarm-scan/apply` | D3 sector-aware apply (`sector_aware`, `mode`) |

## Env (unchanged by Wave D)

| Env | Default | Notes |
|-----|---------|-------|
| `SWARM_AUTO_LAUNCH` | unset/false | **stays false** — cron is scan-only |
| `SWARM_CRON_EXECUTE_TRADES` | false | Dual gate with recipe/request |
| `SWARM_MONITOR_DRY_RUN` | `true` | Not flipped by any Wave D path |
| `ALPACA_TRADING_MODE` | `paper` | Paper-only; Strategies refuses `live` |
| `SWARM_AUTOMATION_DIR` | `/app/data/automation` | Single-replica JSON store |

## Smoke

```bash
# Risk glance (read-only)
curl -sS 'https://<host>/api/automation/risk-policy?mode=swing' | jq '.caps, .flatten'

# Sector-aware apply with skip reasons
curl -sS -X POST -H 'Content-Type: application/json' \
  -d '{"top_n":15,"sector_aware":true}' \
  https://<host>/api/automation/swarm-scan/apply | jq '.applied_tickers, .skipped, .notes'

# Next-recipe hints (display only)
curl -sS https://<host>/api/automation/recipe-hints | jq '.suggested_tickers, .auto_write'

# Build stamp
curl -sS https://<host>/api/build-info | jq '.image_tag, .features'
```

## Tests

`tests/test_wave_d.py` covers the risk glance mirroring config, sector-aware apply skip
reasons and diversification, underweight-first ordering, the ≤15 cap, non-empty recipe
guarantees, hint ranking/display-only flags, the `strategies-ux-12` tag, and the paper-only
compose defaults.

```bash
poetry run pytest tests/test_wave_d.py -q
```
