"""Wave E tests — dry-run streak, α gating, session digest, mode auto-resolver,
redeploy assist, AutoResearch review queue, paper-only hard outs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _isolate_automation(monkeypatch, tmp_path):
    monkeypatch.setenv("SWARM_AUTOMATION_DIR", str(tmp_path / "automation"))
    from app.backend.services import automation_store as store

    store.AUTOMATION_DIR = tmp_path / "automation"
    return store


def _dt(y, m, d, hh=12):
    return datetime(y, m, d, hh, 0, 0, tzinfo=timezone.utc)


# ── E1 — A2 dry-run streak / exit checklist ────────────────────────────────


def test_streak_increments_across_consecutive_weekdays(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.dry_run_streak_service import record_weekday_dry_run_event

    # Mon 2026-03-09 .. Fri 2026-03-13
    days = [_dt(2026, 3, 9 + i) for i in range(5)]
    state = None
    for d in days:
        state = record_weekday_dry_run_event(dry_run=True, had_error=False, when=d)

    assert state["consecutive_weekday_count"] == 5
    assert state["streak_met"] is True
    assert state["target"] == 5
    assert state["last_result"] == "ok"


def test_streak_resets_on_unexpected_error(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.dry_run_streak_service import record_weekday_dry_run_event

    record_weekday_dry_run_event(dry_run=True, had_error=False, when=_dt(2026, 3, 9))
    record_weekday_dry_run_event(dry_run=True, had_error=False, when=_dt(2026, 3, 10))
    state = record_weekday_dry_run_event(dry_run=True, had_error=True, when=_dt(2026, 3, 11))

    assert state["consecutive_weekday_count"] == 0
    assert state["last_result"] == "error"
    assert state["streak_met"] is False


def test_would_fire_action_is_not_an_error(monkeypatch, tmp_path):
    """A normal would-fire stop action must NOT reset the streak — it's the point of a dry run."""
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.dry_run_streak_service import record_weekday_dry_run_event

    monitor_result = {
        "timestamp": "2026-03-09T14:30:00Z",
        "dry_run": True,
        "trading_mode": "swing",
        "positions_checked": 3,
        "actions": [{"symbol": "NVDA", "stop_type": "hard_stop", "reason": "-7% hard stop"}],
        "warnings": [],
    }
    state = record_weekday_dry_run_event(
        dry_run=True, had_error=False, monitor_result=monitor_result, when=_dt(2026, 3, 9)
    )
    assert state["consecutive_weekday_count"] == 1
    assert state["last_result"] == "ok"
    assert state["summaries"][0]["would_fire_count"] == 1
    assert state["summaries"][0]["would_fire"][0]["symbol"] == "NVDA"


def test_streak_restarts_at_one_after_a_gap(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.dry_run_streak_service import record_weekday_dry_run_event

    record_weekday_dry_run_event(dry_run=True, had_error=False, when=_dt(2026, 3, 9))  # Mon → 1
    # Skip Tue/Wed — jump to Thu (a missed weekday is a gap, not consecutive)
    state = record_weekday_dry_run_event(dry_run=True, had_error=False, when=_dt(2026, 3, 12))
    assert state["consecutive_weekday_count"] == 1


def test_weekend_call_is_skipped_not_counted(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.dry_run_streak_service import record_weekday_dry_run_event

    record_weekday_dry_run_event(dry_run=True, had_error=False, when=_dt(2026, 3, 9))  # Mon → 1
    state = record_weekday_dry_run_event(dry_run=True, had_error=False, when=_dt(2026, 3, 14))  # Sat
    assert state["consecutive_weekday_count"] == 1
    assert state["last_result"] == "skipped_weekend"


def test_same_day_repeat_call_is_idempotent(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.dry_run_streak_service import record_weekday_dry_run_event

    record_weekday_dry_run_event(dry_run=True, had_error=False, when=_dt(2026, 3, 9, 9))
    state = record_weekday_dry_run_event(dry_run=True, had_error=False, when=_dt(2026, 3, 9, 15))
    assert state["consecutive_weekday_count"] == 1


def test_hot_call_never_updates_the_dry_run_streak(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.dry_run_streak_service import record_weekday_dry_run_event

    record_weekday_dry_run_event(dry_run=True, had_error=False, when=_dt(2026, 3, 9))
    before = record_weekday_dry_run_event(dry_run=True, had_error=False, when=_dt(2026, 3, 9))
    after = record_weekday_dry_run_event(dry_run=False, had_error=False, when=_dt(2026, 3, 10))
    assert after["consecutive_weekday_count"] == before["consecutive_weekday_count"]


def test_ack_gates_ready_to_flip_alongside_streak(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.dry_run_streak_service import (
        clear_ack,
        read_dry_run_streak,
        record_ack,
        record_weekday_dry_run_event,
    )

    for i in range(5):
        record_weekday_dry_run_event(dry_run=True, had_error=False, when=_dt(2026, 3, 9 + i))

    state = read_dry_run_streak()
    assert state["streak_met"] is True
    assert state["ready_to_flip"] is False  # no ack yet

    state = record_ack("James", "Looks clean")
    assert state["ack"]["acknowledged"] is True
    assert state["ready_to_flip"] is True

    state = clear_ack()
    assert state["ack"]["acknowledged"] is False
    assert state["ready_to_flip"] is False


def test_dry_run_streak_service_never_touches_env():
    """Source-level guarantee: this module cannot flip SWARM_MONITOR_DRY_RUN.

    The env var name is only ever mentioned in documentation/comments here —
    there is no ``import os`` (so no ``os.environ`` write is even possible).
    """
    src = (ROOT / "app/backend/services/dry_run_streak_service.py").read_text(encoding="utf-8")
    assert "import os" not in src
    assert "os.environ" not in src


# ── E2 — Perf strip α + snapshot Details ───────────────────────────────────


def test_snapshot_list_never_fakes_alpha(monkeypatch, tmp_path):
    import app.backend.services.performance_snapshot_service as svc

    monkeypatch.setattr(svc, "SNAPSHOTS_DIR", tmp_path)

    (tmp_path / "2026-03-09.json").write_text(
        json.dumps(
            {
                "date": "2026-03-09",
                "timestamp": "2026-03-09T21:00:00Z",
                "equity": 101000.0,
                "cash": 20000.0,
                "position_count": 3,
                "daily_pnl": 500.0,
                "daily_pnl_pct": 0.5,
                "spy_price": None,
                "spy_daily_pct": None,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "2026-03-10.json").write_text(
        json.dumps(
            {
                "date": "2026-03-10",
                "timestamp": "2026-03-10T21:00:00Z",
                "equity": 101500.0,
                "cash": 19500.0,
                "position_count": 3,
                "daily_pnl": 500.0,
                "daily_pnl_pct": 0.49,
                "spy_price": 550.0,
                "spy_daily_pct": 0.30,
                "alpha_vs_spy_daily": 0.19,
            }
        ),
        encoding="utf-8",
    )

    rows = svc.list_recent_snapshots(limit=30)
    assert len(rows) == 2
    # Newest first
    assert rows[0]["date"] == "2026-03-10"
    assert rows[1]["date"] == "2026-03-09"

    # Never a fake zero — missing benchmark data stays None
    assert rows[1]["spy_daily_pct"] is None
    assert rows[1]["alpha_vs_spy_daily"] is None
    # Real data passes through untouched
    assert rows[0]["alpha_vs_spy_daily"] == 0.19


def test_compute_alpha_vs_spy_still_none_without_real_data(monkeypatch, tmp_path):
    import app.backend.services.performance_snapshot_service as svc

    monkeypatch.setattr(svc, "SNAPSHOTS_DIR", tmp_path)
    (tmp_path / "2026-03-09.json").write_text(
        json.dumps({"date": "2026-03-09", "equity": 100000.0, "daily_pnl_pct": 0.5}),
        encoding="utf-8",
    )
    assert svc.compute_alpha_vs_spy(svc.load_snapshots()) is None


# ── E3 — Session digest center ──────────────────────────────────────────────


def test_session_digest_uses_real_fields_only_no_invented_scores():
    from app.backend.services.session_digest_service import build_session_digest

    record = {"mode": "swing", "instrument": "stocks", "tickers": ["NVDA", "AAPL"]}
    summary = {
        "mode": "swing",
        "instrument": "stocks",
        "ticker_count": 2,
        "analyst_count": 4,
        "action_counts": {"buy": 1, "hold": 1},
        "decisions": [{"ticker": "NVDA", "action": "buy"}, {"ticker": "AAPL", "action": "hold"}],
        "conviction_digest": {
            "consensus": [{"ticker": "NVDA", "direction": "buy"}],
            "contested": [],
            "risk_rejected": [{"ticker": "AAPL", "reason": "remaining_position_limit=0"}],
        },
        "executed_trades": True,
        "execute_blocked_reason": None,
        "trade_results": [
            {"ticker": "NVDA", "success": True},
            {"ticker": "AAPL", "success": False, "reason": "insufficient buying power"},
        ],
    }

    digest = build_session_digest("run-123", record, summary)

    assert digest["run_id"] == "run-123"
    assert digest["action_counts"] == {"buy": 1, "hold": 1}
    assert digest["decision_count"] == 2
    assert digest["conviction"] == {
        "consensus_count": 1,
        "contested_count": 0,
        "risk_rejected_count": 1,
    }
    assert digest["trade_results"] == {"filled": 1, "blocked": 1, "other": 0, "total": 2}
    assert digest["source"] == "real_run_fields"
    # No invented aggregate confidence/score field anywhere in the digest
    assert "confidence" not in digest
    assert "score" not in digest


def test_session_digest_persists_and_reads_back(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.session_digest_service import read_session_digests, write_session_digest

    for i in range(3):
        write_session_digest(
            run_id=f"run-{i}",
            record={"mode": "swing", "tickers": ["NVDA"]},
            summary={"action_counts": {"buy": 1}, "decisions": [], "trade_results": []},
        )

    rows = read_session_digests(limit=10)
    assert len(rows) == 3
    assert rows[0]["run_id"] == "run-2"  # newest first


# ── E4 — Mode auto-resolver lite ─────────────────────────────────────────────


def test_auto_mode_rule_precedence_matches_documented_rules():
    from src.mode_resolver import resolve_auto_mode_rules

    assert resolve_auto_mode_rules(vix=30, event_day=False)["resolved_mode"] == "day"
    assert resolve_auto_mode_rules(vix=30)["matched_rule"] == "vix_high"

    assert resolve_auto_mode_rules(vix=10, gap_pct=1.5)["resolved_mode"] == "day"
    assert resolve_auto_mode_rules(vix=10, gap_pct=1.5)["matched_rule"] == "gap"

    assert resolve_auto_mode_rules(event_day=True, vix=10)["resolved_mode"] == "day"
    assert resolve_auto_mode_rules(event_day=True, vix=10)["matched_rule"] == "event_day"

    assert resolve_auto_mode_rules(vix=15)["resolved_mode"] == "swing"
    assert resolve_auto_mode_rules(vix=15)["matched_rule"] == "vix_low"

    no_data = resolve_auto_mode_rules()
    assert no_data["resolved_mode"] == "swing"
    assert no_data["matched_rule"] == "no_data"

    # Neutral band (VIX between 20 and 25, no gap, no event) → safe default
    neutral = resolve_auto_mode_rules(vix=22, gap_pct=0.1)
    assert neutral["resolved_mode"] == "swing"
    assert neutral["matched_rule"] == "default"


def test_human_override_wins_without_computing_signals(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    import app.backend.services.mode_resolver_service as resolver

    monkeypatch.setattr(
        resolver,
        "_read_trading_mode_file",
        lambda: {"mode": "auto", "override": "day", "override_until": None},
    )

    def _boom():
        raise AssertionError("gather_signals must not be called when a human override is active")

    monkeypatch.setattr(resolver, "gather_signals", _boom)

    result = resolver.compute_and_persist_mode_resolution(force=True)
    assert result["active"] == "override"
    assert result["resolved_mode"] == "day"
    assert "override" in result["reason"].lower()


def test_explicit_mode_is_reported_without_computing_signals(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    import app.backend.services.mode_resolver_service as resolver

    monkeypatch.setattr(
        resolver, "_read_trading_mode_file", lambda: {"mode": "swing", "override": None}
    )
    monkeypatch.setattr(
        resolver, "gather_signals", lambda: (_ for _ in ()).throw(AssertionError("should not run"))
    )

    result = resolver.compute_and_persist_mode_resolution(force=True)
    assert result["active"] == "explicit"
    assert result["resolved_mode"] == "swing"


def test_auto_mode_uses_gathered_signals_and_persists_reason(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    import app.backend.services.mode_resolver_service as resolver

    monkeypatch.setattr(
        resolver, "_read_trading_mode_file", lambda: {"mode": "auto", "override": None}
    )
    monkeypatch.setattr(
        resolver, "gather_signals", lambda: {"vix": 30.0, "gap_pct": None, "event_day": False}
    )

    result = resolver.compute_and_persist_mode_resolution(force=True)
    assert result["active"] == "auto"
    assert result["resolved_mode"] == "day"
    assert "VIX" in result["reason"]

    cached = resolver.read_last_mode_resolution()
    assert cached["resolved_mode"] == "day"


# ── E5 — Empty-book redeploy assist ─────────────────────────────────────────


def test_redeploy_suggestion_only_when_empty_and_cash_above_threshold():
    from app.backend.services.redeploy_assist_service import compute_suggestion

    empty_rich = compute_suggestion(0, 5000.0, threshold=1000.0)
    assert empty_rich["suggest"] is True
    assert "Scan" in (empty_rich["message"] or "")
    assert empty_rich["execute_dual_gated"] is True

    has_positions = compute_suggestion(2, 5000.0, threshold=1000.0)
    assert has_positions["suggest"] is False

    below_threshold = compute_suggestion(0, 500.0, threshold=1000.0)
    assert below_threshold["suggest"] is False

    no_cash_data = compute_suggestion(0, None, threshold=1000.0)
    assert no_cash_data["suggest"] is False


def test_redeploy_threshold_env_override(monkeypatch):
    from app.backend.services.redeploy_assist_service import compute_suggestion

    monkeypatch.setenv("SWARM_EMPTY_BOOK_CASH_THRESHOLD", "50")
    result = compute_suggestion(0, 100.0)
    assert result["threshold"] == 50.0
    assert result["suggest"] is True


# ── E6 — AutoResearch review queue (stub) ───────────────────────────────────


def test_reads_real_experiment_log_and_sanitizes_diff():
    from app.backend.services.autoresearch_review_service import read_recent_experiments

    rows = read_recent_experiments(limit=5)
    assert len(rows) > 0
    for row in rows:
        assert "diff" not in row  # raw diff never returned — only diff_preview
        assert set(row.keys()) >= {
            "experiment_id",
            "timestamp",
            "hypothesis",
            "fitness_score",
            "kept",
            "metrics",
        }


def test_experiments_are_newest_first(monkeypatch, tmp_path):
    import app.backend.services.autoresearch_review_service as svc

    monkeypatch.setattr(svc, "_experiments_dir", lambda: tmp_path)
    rows = [
        {"experiment_id": "a", "timestamp": "2026-01-01T00:00:00Z", "hypothesis": "first", "kept": False, "metrics": {}},
        {"experiment_id": "b", "timestamp": "2026-01-03T00:00:00Z", "hypothesis": "third", "kept": True, "metrics": {"fitness": 5.0}},
        {"experiment_id": "c", "timestamp": "2026-01-02T00:00:00Z", "hypothesis": "second", "kept": False, "metrics": {}},
    ]
    (tmp_path / svc.EXPERIMENTS_LOG_FILE).write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )

    out = svc.read_recent_experiments(limit=10)
    assert [r["experiment_id"] for r in out] == ["b", "c", "a"]
    assert out[0]["fitness_score"] == 5.0


def test_review_decision_is_display_only_and_never_touches_strategy_py(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.autoresearch_review_service import (
        get_review_queue,
        record_review_decision,
    )

    strategy_path = ROOT / "autoresearch" / "strategy.py"
    before = strategy_path.read_text(encoding="utf-8") if strategy_path.exists() else None

    result = record_review_decision("some-experiment-id", "approved", by="Reviewer", note="looks fine")
    assert result["review"]["decision"] == "approved"
    assert result["review"]["applied"] is False

    after = strategy_path.read_text(encoding="utf-8") if strategy_path.exists() else None
    assert before == after  # never touched

    queue = get_review_queue(limit=5)
    assert queue["paper_only"] is True
    assert queue["read_only_source"] is True

    # Clearing works too
    cleared = record_review_decision("some-experiment-id", "pending")
    assert cleared["review"] is None


def test_invalid_decision_is_rejected():
    from app.backend.services.autoresearch_review_service import record_review_decision

    with pytest.raises(ValueError):
        record_review_decision("exp", "auto-apply")


def test_autoresearch_review_service_has_exactly_one_write_path():
    """Source-level guarantee: only ``_write_review_state`` ever calls write_text —
    there is no second write path that could reach strategy.py or other config."""
    src = (ROOT / "app/backend/services/autoresearch_review_service.py").read_text(encoding="utf-8")
    assert src.count("write_text(") == 1
    assert "subprocess" not in src  # cannot shell out to evolve.py


# ── Ship checks / hard outs ───────────────────────────────────────────────


def test_build_info_has_wave_e_flags():
    src = (ROOT / "app/backend/routes/build_info.py").read_text(encoding="utf-8")
    for flag in (
        "dry-run-streak-checklist",
        "perf-snapshot-details",
        "session-digest-center",
        "mode-auto-resolver",
        "empty-book-redeploy-assist",
        "autoresearch-review-queue",
    ):
        assert flag in src


def test_compose_image_tag_is_strategies_ux_13():
    """Wave F bumped the shipping tag to strategies-ux-14 — see test_wave_f_hit.py."""
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "strategies-ux-14" in compose
    assert "strategies-ux-12" not in compose


def test_paper_only_hard_outs_unchanged():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "SWARM_AUTO_LAUNCH: ${SWARM_AUTO_LAUNCH:-false}" in compose
    assert "SWARM_MONITOR_DRY_RUN: ${SWARM_MONITOR_DRY_RUN:-true}" in compose
    assert "SWARM_CRON_EXECUTE_TRADES: ${SWARM_CRON_EXECUTE_TRADES:-false}" in compose
    assert "ALPACA_TRADING_MODE: ${ALPACA_TRADING_MODE:-paper}" in compose


def test_wave_e_docs_document_hard_outs_and_e6_stub():
    doc = (ROOT / "docs/WAVE_E.md").read_text(encoding="utf-8")
    assert "SWARM_AUTO_LAUNCH" in doc
    assert "SWARM_MONITOR_DRY_RUN" in doc
    assert "display/UX-only" in doc or "display/ux-only" in doc.lower()
    assert "never" in doc.lower() and "strategy.py" in doc
    assert "strategies-ux-13" in doc


def test_no_flow_worker_or_auto_apply_references_in_new_services():
    """A6 Flow worker + E6 auto-apply are explicit hard outs for this wave."""
    for fname in (
        "dry_run_streak_service.py",
        "mode_resolver_service.py",
        "session_digest_service.py",
        "redeploy_assist_service.py",
        "autoresearch_review_service.py",
    ):
        src = (ROOT / "app/backend/services" / fname).read_text(encoding="utf-8")
        assert "flow_worker" not in src.lower()
        assert "auto_apply" not in src.lower().replace(" ", "").replace("-", "_")
