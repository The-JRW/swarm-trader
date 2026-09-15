"""Wave F (F1–F6) tests — HIT: High-frequency Intraday Turnover.

HIT = paper-only, NOT true HFT. These tests assert the risk caps vs `day`,
the F2 cost gate blocking/approving synthetic trades, the F3 cron secret
gate + dual-gate execute resolution, the F5 ops strip's honest accounting,
the F6 weekday streak mechanics (mirroring A2/E1), and the paper-only /
image-tag hard outs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]


def _isolate_automation(monkeypatch, tmp_path):
    monkeypatch.setenv("SWARM_AUTOMATION_DIR", str(tmp_path / "automation"))
    from app.backend.services import automation_store as store

    store.AUTOMATION_DIR = tmp_path / "automation"
    return store


def _dt(y, m, d, hh=12):
    return datetime(y, m, d, hh, 0, 0, tzinfo=timezone.utc)


# ── F1 — `hit` trading mode ─────────────────────────────────────────────────


def test_hit_mode_exists_and_is_tighter_and_more_active_than_day():
    from src.config import MODES, get_mode_config

    assert "hit" in MODES
    day = get_mode_config("day")["risk"]
    hit = get_mode_config("hit")["risk"]

    assert hit["max_position_pct"] < day["max_position_pct"]
    assert hit["max_trades_per_day"] > day["max_trades_per_day"]
    assert hit["max_open_positions"] > day["max_open_positions"]
    assert hit["stop_loss_pct"] < day["stop_loss_pct"]
    assert hit["min_cash_pct"] > day["min_cash_pct"]
    assert hit["flatten_eod"] is True
    # Earlier flatten than day (15:45)
    assert hit["flatten_by"] < day["flatten_by"]


def test_hit_mode_blocks_leveraged_etfs_by_default():
    """Reviewer amendment #4 — no TQQQ/SOXL (or any leveraged ETF) in default HIT universe."""
    from src.config import get_mode_config
    from risk_manager import LEVERAGED_ETFS

    hit = get_mode_config("hit")
    assert hit["risk"]["allow_leveraged_etfs"] is False

    universe_tickers = {
        t for bucket in hit["universe"].values() for t in bucket.get("tickers", [])
    }
    assert universe_tickers.isdisjoint(LEVERAGED_ETFS)
    assert "TQQQ" not in universe_tickers
    assert "SOXL" not in universe_tickers
    # Liquid mega+SPY/QQQ only
    assert "SPY" in universe_tickers
    assert "QQQ" in universe_tickers


def test_hit_risk_manager_blocks_leveraged_etf_entry():
    """risk_manager itself refuses a leveraged ETF buy in hit mode (no LLM override)."""
    from risk_manager import validate_trade

    portfolio_state = {
        "equity": 100_000.0,
        "cash": 50_000.0,
        "cash_pct": 0.5,
        "daily_pnl_pct": 0.0,
        "weekly_pnl_pct": 0.0,
        "positions": {},
        "sector_alloc": {},
        "trade_count_today": 0,
        "open_position_count": 0,
    }
    result = validate_trade(
        "TQQQ", "buy", 10, 50.0, portfolio_state=portfolio_state, mode="hit"
    )
    assert result.approved is False
    assert result.rule == "no_leveraged_etfs"


def test_hit_risk_policy_endpoint_reports_the_tighter_caps():
    from app.backend.services.risk_policy_service import get_risk_policy

    policy = get_risk_policy("hit")
    assert policy["mode"] == "hit"
    assert policy["blocklists"]["leveraged_etfs_allowed"] is False
    assert policy["flatten"]["flatten_eod"] is True
    assert policy["flatten"]["flatten_by"] == "15:30"


def test_account_routing_prefers_day_account_for_hit_mode(monkeypatch):
    import src.accounts as accounts_mod

    monkeypatch.setattr(
        accounts_mod,
        "_ACCOUNTS",
        {
            "swing": accounts_mod.AlpacaAccount(
                name="Swing", account_id="s", api_key="k", api_secret="s"
            ),
            "day": accounts_mod.AlpacaAccount(
                name="DayTrading", account_id="d", api_key="k2", api_secret="s2"
            ),
        },
    )
    acct = accounts_mod.get_account_for_mode("hit")
    assert acct.name == "DayTrading"

    # Falls back to swing when no day account is configured
    monkeypatch.setattr(
        accounts_mod,
        "_ACCOUNTS",
        {
            "swing": accounts_mod.AlpacaAccount(
                name="Swing", account_id="s", api_key="k", api_secret="s"
            )
        },
    )
    acct2 = accounts_mod.get_account_for_mode("hit")
    assert acct2.name == "Swing"


# ── F2 — Cost / microstructure gate (mandatory on HIT execute) ────────────


def test_cost_gate_blocks_synthetic_high_cost_trade():
    """Acceptance criterion: cost gate blocks at least one synthetic high-cost trade."""
    from app.backend.services.cost_gate_service import evaluate_cost_gate

    wide_quote = {"bp": 99.0, "ap": 101.0}  # ~200bps spread — clearly too wide for HIT
    result = evaluate_cost_gate(
        ticker="XYZ",
        action="buy",
        qty=100,
        price=100.0,
        equity=100_000.0,
        turnover_today=0.0,
        quote=wide_quote,
        cost_budget_bps=15.0,
    )
    assert result.approved is False
    assert result.rule == "cost_gate"
    assert result.round_trip_cost_bps >= 15.0
    assert "BLOCKED" in result.reason


def test_cost_gate_approves_tight_spread_trade_within_budget():
    from app.backend.services.cost_gate_service import evaluate_cost_gate

    tight_quote = {"bp": 99.99, "ap": 100.01}  # ~2bps spread
    result = evaluate_cost_gate(
        ticker="SPY",
        action="buy",
        qty=10,
        price=100.0,
        equity=100_000.0,
        turnover_today=0.0,
        quote=tight_quote,
        cost_budget_bps=15.0,
        turnover_budget_pct=2.0,
    )
    assert result.approved is True
    assert result.rule is None


def test_cost_gate_blocks_on_turnover_budget_breach():
    from app.backend.services.cost_gate_service import evaluate_cost_gate

    tight_quote = {"bp": 99.99, "ap": 100.01}
    result = evaluate_cost_gate(
        ticker="SPY",
        action="buy",
        qty=10_000,  # $1,000,000 notional
        price=100.0,
        equity=100_000.0,
        turnover_today=900_000.0,  # already near the $2,000,000 turnover budget
        quote=tight_quote,
        cost_budget_bps=15.0,
        turnover_budget_pct=2.0,  # 200% of $100k equity = $200k... use larger budget below
    )
    # With a 2.0 (200%) budget on $100k equity, budget is $200k; turnover_today alone
    # ($900k) already exceeds it, so this must block on turnover, not (only) cost.
    assert result.approved is False
    assert result.rule == "cost_gate"
    assert "turnover" in result.reason.lower()


def test_cost_gate_never_blocks_exits_or_holds():
    from app.backend.services.cost_gate_service import evaluate_cost_gate

    wide_quote = {"bp": 50.0, "ap": 150.0}  # absurdly wide — would block an entry
    for action in ("sell", "cover", "hold"):
        result = evaluate_cost_gate(
            ticker="XYZ",
            action=action,
            qty=10,
            price=100.0,
            equity=100_000.0,
            quote=wide_quote,
        )
        assert result.approved is True
        assert result.rule is None


def test_estimate_half_spread_bps_uses_live_quote_then_documented_default():
    from app.backend.services.cost_gate_service import estimate_half_spread_bps

    bps, source = estimate_half_spread_bps("NVDA", {"bp": 100.0, "ap": 100.10})
    assert source == "live_quote"
    assert bps == pytest.approx(5.0, rel=0.01)  # 10bps spread / 2

    bps2, source2 = estimate_half_spread_bps("NVDA", None)
    assert source2 == "ticker_class_default_assumed"
    assert bps2 > 0

    bps3, source3 = estimate_half_spread_bps("SPY", None)
    assert source3 == "ticker_class_default_assumed"
    assert bps3 < bps2  # ETFs assumed tighter than single names


def test_apply_cost_gate_to_decisions_downgrades_blocked_entries_only():
    from app.backend.services.cost_gate_service import apply_cost_gate_to_decisions

    decisions = {
        "GOOD": {"action": "buy", "quantity": 10, "reasoning": "keep me"},
        "BAD": {"action": "buy", "quantity": 10, "reasoning": "block me"},
        "HOLD_TICKER": {"action": "hold", "quantity": 0},
    }
    prices = {"GOOD": 100.0, "BAD": 100.0}
    quotes = {
        "GOOD": {"bp": 99.99, "ap": 100.01},
        "BAD": {"bp": 90.0, "ap": 110.0},
    }
    filtered, rejects = apply_cost_gate_to_decisions(
        decisions, prices=prices, equity=1_000_000.0, quotes=quotes, cost_budget_bps=15.0
    )

    assert filtered["GOOD"]["action"] == "buy"
    assert filtered["BAD"]["action"] == "hold"
    assert filtered["BAD"]["quantity"] == 0
    assert filtered["HOLD_TICKER"]["action"] == "hold"
    assert len(rejects) == 1
    assert rejects[0]["ticker"] == "BAD"
    assert rejects[0]["rule"] == "cost_gate"
    # Original decisions dict (with reasoning) untouched — only used for display
    assert decisions["BAD"]["action"] == "buy"


def test_gate_hit_decisions_for_execute_is_noop_for_non_hit_modes():
    from app.backend.services.cost_gate_service import gate_hit_decisions_for_execute

    decisions = {"NVDA": {"action": "buy", "quantity": 10}}
    filtered, rejects, prices = gate_hit_decisions_for_execute(decisions, "day")
    assert filtered == decisions
    assert rejects == []
    assert prices == {}


# ── F3 — HIT pulse cron (secret gate + analysis-only default + dual gate) ──


def test_cron_hit_pulse_route_is_secret_gated():
    """`/cron/hit-pulse` sits behind the same `require_cron_secret` dependency
    as every other cron route — 401 without a valid secret."""
    import inspect

    from app.backend.dependencies.cron_auth import require_cron_secret
    from app.backend.routes import cron as cron_routes

    router = cron_routes.router
    assert any(d.dependency is require_cron_secret for d in router.dependencies)

    src = inspect.getsource(cron_routes)
    assert '"/cron/hit-pulse"' in src


def test_require_cron_secret_401_without_valid_secret_for_hit_pulse(monkeypatch):
    from app.backend.dependencies.cron_auth import require_cron_secret

    monkeypatch.delenv("SWARM_CRON_SECRET", raising=False)
    with pytest.raises(HTTPException) as ei:
        require_cron_secret(x_swarm_cron_secret="anything")
    assert ei.value.status_code == 401

    monkeypatch.setenv("SWARM_CRON_SECRET", "hit-secret")
    with pytest.raises(HTTPException) as ei2:
        require_cron_secret(x_swarm_cron_secret="wrong")
    assert ei2.value.status_code == 401

    require_cron_secret(x_swarm_cron_secret="hit-secret")  # does not raise


def test_hit_execute_dual_gate(monkeypatch):
    from app.backend.services.hit_ops_service import (
        hit_execute_env_allows,
        resolve_hit_execute,
    )

    monkeypatch.delenv("SWARM_HIT_EXECUTE", raising=False)
    assert hit_execute_env_allows() is False
    assert resolve_hit_execute(True) is False  # analysis-only by default
    assert resolve_hit_execute(False) is False

    monkeypatch.setenv("SWARM_HIT_EXECUTE", "true")
    assert hit_execute_env_allows() is True
    assert resolve_hit_execute(True) is True
    assert resolve_hit_execute(False) is False  # request must ALSO ask for it

    monkeypatch.setenv("SWARM_HIT_EXECUTE", "false")
    assert resolve_hit_execute(True) is False


def test_hit_universe_tickers_cap():
    from app.backend.services.hit_service import hit_universe_tickers

    tickers = hit_universe_tickers(cap=5)
    assert len(tickers) == 5
    assert "SPY" in hit_universe_tickers(cap=15) or "QQQ" in hit_universe_tickers(cap=15)


# ── F4 — HIT preset ordering (deterministic/fast signals first) ───────────


def test_hit_preset_orders_deterministic_signals_before_heavy_llm():
    from app.backend.services.hit_service import HIT_PRESET_ANALYST_IDS

    ids = list(HIT_PRESET_ANALYST_IDS)
    assert ids.index("technical_analyst") < ids.index("autoresearch")
    assert ids.index("market_regime") < ids.index("autoresearch")


def test_cron_and_automation_presets_include_hit():
    from app.backend.routes.cron import _PRESET_ANALYST_IDS as cron_presets
    from app.backend.services.swarm_scan_service import _PRESET_ANALYST_IDS as scan_presets

    assert "hit" in cron_presets
    assert "hit" in scan_presets
    assert "technical_analyst" in cron_presets["hit"]


# ── F5 — Ops HIT strip (trades today, turnover, cost-gate rejects) ────────


def test_hit_ops_never_crashes_with_no_pulse_yet(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.hit_ops_service import read_hit_ops

    ops = read_hit_ops()
    assert ops["trades_today"] == 0
    assert ops["turnover_today"] == 0.0
    assert ops["cost_gate_rejects_today"] == 0
    assert ops["last_pulse"] is None
    assert ops["recent_fill_latencies"] == []


def test_hit_ops_records_real_fills_and_cost_gate_rejects_honestly(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.hit_ops_service import read_hit_ops, record_hit_run

    trade_results = [
        {
            "ticker": "NVDA",
            "qty": 10,
            "success": True,
            "order_id": "o1",
            "submitted_at": "2026-03-09T14:30:00.000Z",
            "filled_at": "2026-03-09T14:30:00.250Z",
        },
        {"ticker": "AAPL", "qty": 5, "success": False, "reason": "risk blocked"},
    ]
    cost_gate_rejects = [
        {"ticker": "MSFT", "action": "buy", "qty": 5, "rule": "cost_gate", "reason": "too wide"}
    ]
    prices = {"NVDA": 100.0}

    state = record_hit_run(
        run_id="run-1",
        execute_requested=True,
        execute_effective=True,
        would_fire_count=3,
        trade_results=trade_results,
        cost_gate_rejects=cost_gate_rejects,
        prices=prices,
    )

    assert state["trades_today"] == 1  # only the successful NVDA fill
    assert state["turnover_today"] == pytest.approx(1000.0)  # 10 * $100 — real price only
    assert state["cost_gate_rejects_today"] == 1
    assert state["last_pulse"]["run_id"] == "run-1"
    assert state["last_pulse"]["execute_effective"] is True
    assert len(state["recent_fill_latencies"]) == 1
    assert state["recent_fill_latencies"][0]["latency_ms"] == 250

    # Persisted + readable back
    reread = read_hit_ops()
    assert reread["trades_today"] == 1

    # A second run accumulates rather than resetting mid-day
    record_hit_run(
        run_id="run-2",
        execute_requested=False,
        execute_effective=False,
        would_fire_count=1,
        trade_results=[],
        cost_gate_rejects=[],
        prices={},
    )
    accumulated = read_hit_ops()
    assert accumulated["trades_today"] == 1
    assert accumulated["pulses_today"] == 2
    assert accumulated["last_pulse"]["run_id"] == "run-2"


def test_hit_ops_resets_on_new_calendar_day(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services import hit_ops_service as svc

    svc.record_hit_run(
        run_id="run-1",
        execute_requested=False,
        execute_effective=False,
        trade_results=[{"ticker": "NVDA", "qty": 1, "success": True}],
        prices={"NVDA": 100.0},
    )
    stale = svc._read_json(svc._hit_ops_path())
    assert stale["trades_today"] == 1

    stale["date"] = "2000-01-01"
    svc._atomic_write(svc._hit_ops_path(), stale)

    fresh = svc.read_hit_ops()
    assert fresh["trades_today"] == 0
    assert fresh["date"] != "2000-01-01"


# ── F6 — HIT dry-run streak (mirrors A2/E1) ────────────────────────────────


def test_hit_streak_increments_across_consecutive_weekdays(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.hit_dry_run_streak_service import record_weekday_hit_pulse_event

    days = [_dt(2026, 3, 9 + i) for i in range(5)]
    state = None
    for d in days:
        state = record_weekday_hit_pulse_event(dry_run=True, had_error=False, when=d)

    assert state["consecutive_weekday_count"] == 5
    assert state["streak_met"] is True
    assert state["target"] == 5


def test_hit_streak_resets_on_unexpected_error(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.hit_dry_run_streak_service import record_weekday_hit_pulse_event

    record_weekday_hit_pulse_event(dry_run=True, had_error=False, when=_dt(2026, 3, 9))
    record_weekday_hit_pulse_event(dry_run=True, had_error=False, when=_dt(2026, 3, 10))
    state = record_weekday_hit_pulse_event(dry_run=True, had_error=True, when=_dt(2026, 3, 11))

    assert state["consecutive_weekday_count"] == 0
    assert state["last_result"] == "error"


def test_hit_streak_would_fire_summary_is_not_an_error(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.hit_dry_run_streak_service import record_weekday_hit_pulse_event

    summary = {
        "mode": "hit",
        "action_counts": {"buy": 2, "short": 1, "hold": 5},
        "conviction_digest": {"risk_rejected": [{"ticker": "NVDA", "reason": "limit"}]},
        "executed_trades": False,
    }
    state = record_weekday_hit_pulse_event(
        dry_run=True,
        had_error=False,
        summary=summary,
        cost_gate_reject_count=2,
        when=_dt(2026, 3, 9),
    )
    assert state["consecutive_weekday_count"] == 1
    assert state["last_result"] == "ok"
    entry = state["summaries"][0]
    assert entry["would_fire_count"] == 3  # buy(2) + short(1)
    assert entry["risk_blocked_count"] == 1
    assert entry["cost_gate_reject_count"] == 2


def test_hit_streak_restarts_at_one_after_a_gap(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.hit_dry_run_streak_service import record_weekday_hit_pulse_event

    record_weekday_hit_pulse_event(dry_run=True, had_error=False, when=_dt(2026, 3, 9))
    state = record_weekday_hit_pulse_event(dry_run=True, had_error=False, when=_dt(2026, 3, 12))
    assert state["consecutive_weekday_count"] == 1


def test_hit_streak_hot_execute_call_never_updates_streak(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.hit_dry_run_streak_service import record_weekday_hit_pulse_event

    record_weekday_hit_pulse_event(dry_run=True, had_error=False, when=_dt(2026, 3, 9))
    before = record_weekday_hit_pulse_event(dry_run=True, had_error=False, when=_dt(2026, 3, 9))
    after = record_weekday_hit_pulse_event(dry_run=False, had_error=False, when=_dt(2026, 3, 10))
    assert after["consecutive_weekday_count"] == before["consecutive_weekday_count"]


def test_hit_streak_ack_is_record_only(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.hit_dry_run_streak_service import (
        clear_ack,
        read_hit_dry_run_streak,
        record_ack,
    )

    state = record_ack("Reviewer", "looks good")
    assert state["ack"]["acknowledged"] is True
    assert state["ack"]["by"] == "Reviewer"

    reread = read_hit_dry_run_streak()
    assert reread["ack"]["acknowledged"] is True

    cleared = clear_ack()
    assert cleared["ack"]["acknowledged"] is False


def test_hit_streak_service_never_writes_hit_execute_env():
    """Reviewer amendment #5 — no UI/service write path to SWARM_HIT_EXECUTE."""
    src = (ROOT / "app/backend/services/hit_dry_run_streak_service.py").read_text(
        encoding="utf-8"
    )
    assert "os.environ[" not in src
    assert "setenv" not in src.lower()
    assert "SWARM_MONITOR_DRY_RUN" not in src  # F6 is HIT-scoped, not A2's monitor flag


def test_no_hit_service_ever_sets_monitor_dry_run_false():
    """Hard out: nothing in this wave touches SWARM_MONITOR_DRY_RUN."""
    for fname in (
        "cost_gate_service.py",
        "hit_service.py",
        "hit_ops_service.py",
        "hit_dry_run_streak_service.py",
    ):
        src = (ROOT / "app/backend/services" / fname).read_text(encoding="utf-8")
        assert "SWARM_MONITOR_DRY_RUN" not in src
        assert "SWARM_AUTO_LAUNCH" not in src


# ── Ship checks / hard outs ──────────────────────────────────────────────


def test_build_info_has_wave_f_flags():
    src = (ROOT / "app/backend/routes/build_info.py").read_text(encoding="utf-8")
    for flag in (
        "hit-mode",
        "hit-cost-gate",
        "hit-pulse-cron",
        "hit-ops-strip",
        "hit-dry-run-streak",
    ):
        assert flag in src


def test_compose_image_tag_is_strategies_ux_14():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "strategies-ux-14" in compose
    assert "strategies-ux-13" not in compose


def test_compose_hit_execute_defaults_are_paper_safe():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "SWARM_HIT_EXECUTE: ${SWARM_HIT_EXECUTE:-false}" in compose


def test_paper_only_hard_outs_unchanged():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "SWARM_AUTO_LAUNCH: ${SWARM_AUTO_LAUNCH:-false}" in compose
    assert "SWARM_MONITOR_DRY_RUN: ${SWARM_MONITOR_DRY_RUN:-true}" in compose
    assert "SWARM_CRON_EXECUTE_TRADES: ${SWARM_CRON_EXECUTE_TRADES:-false}" in compose
    assert "ALPACA_TRADING_MODE: ${ALPACA_TRADING_MODE:-paper}" in compose


def test_wave_f_docs_state_hit_is_not_true_hft():
    doc = (ROOT / "docs/WAVE_F_HIT.md").read_text(encoding="utf-8")
    assert "not true HFT" in doc or "≠ true HFT" in doc
    assert "co-location" in doc.lower() or "co-lo" in doc.lower()
    assert "strategies-ux-14" in doc
    assert "SWARM_HIT_EXECUTE" in doc
    assert "SWARM_MONITOR_DRY_RUN" in doc


def test_no_websocket_client_added_by_this_wave():
    """F5 explicitly polls a persisted summary rather than adding a live
    WebSocket / trade_updates client — no `wss://`, `websockets` import, or
    Alpaca `trade_updates` stream subscription anywhere in the new modules
    (comments *documenting* that choice are fine; actual client code is not)."""
    for fname in ("hit_ops_service.py", "hit_service.py", "cost_gate_service.py"):
        src = (ROOT / "app/backend/services" / fname).read_text(encoding="utf-8")
        assert "wss://" not in src
        assert "import websocket" not in src.lower()
        assert "trade_updates" not in src.lower()
