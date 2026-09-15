"""Wave G (G2–G6) tests — latency-max paper HIT, still NOT colocated µs HFT.

G2: fast HIT analyst path (opt-in-only LLM-heavy pair). G3: quote-freshness
rejection in the F2 cost gate + the optional read-only quote WS's pure/
unit-testable surface (parsing, cache, single-connection discipline — never
a real socket). G4: decision→submit→ack→fill latency observatory. G5:
hit-pulse execute dual gate is unchanged. G6: docs + build-info flags.
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


@pytest.fixture(autouse=True)
def _reset_quote_ws_singleton():
    from app.backend.services import hit_quote_ws_service as svc

    svc.reset_for_tests()
    yield
    svc.reset_for_tests()


# ── G2 — fast HIT path ──────────────────────────────────────────────────────


def test_resolve_hit_analyst_ids_fast_default_excludes_slow_pair():
    from app.backend.services.hit_service import (
        HIT_PRESET_ANALYST_IDS,
        HIT_SLOW_LLM_ANALYST_IDS,
        resolve_hit_analyst_ids,
    )

    ids = resolve_hit_analyst_ids()
    assert ids == list(HIT_PRESET_ANALYST_IDS)
    for slow_id in HIT_SLOW_LLM_ANALYST_IDS:
        assert slow_id not in ids

    # Explicit fast=True is identical to the default.
    assert resolve_hit_analyst_ids(fast=True) == ids


def test_resolve_hit_analyst_ids_fast_false_appends_slow_pair_after_fast_preset():
    from app.backend.services.hit_service import (
        HIT_PRESET_ANALYST_IDS,
        HIT_SLOW_LLM_ANALYST_IDS,
        resolve_hit_analyst_ids,
    )

    ids = resolve_hit_analyst_ids(fast=False)
    n = len(HIT_PRESET_ANALYST_IDS)
    assert ids[:n] == list(HIT_PRESET_ANALYST_IDS)
    assert ids[n:] == list(HIT_SLOW_LLM_ANALYST_IDS)


def test_fast_and_slow_analyst_llm_usage_is_documented_honestly():
    """Source-level honesty check backing the hit_service module docstring's
    per-analyst LLM claims — never assert something false about which
    analysts make an LLM call."""
    import inspect

    from src.agents.apex import apex_agent
    from src.agents.autoresearch_agent import autoresearch_agent
    from src.agents.market_regime import market_regime_agent
    from src.agents.news_sentiment import news_sentiment_agent
    from src.agents.sentiment import sentiment_analyst_agent
    from src.agents.technicals import technical_analyst_agent

    def _calls_llm(fn) -> bool:
        # Whole module, not just the top-level function — market_regime_agent
        # and apex_agent delegate their LLM call to a module-level helper.
        return "call_llm(" in inspect.getsource(inspect.getmodule(fn))

    # Fast preset (Wave F, unchanged): technical + autoresearch + sentiment
    # make zero LLM calls; market_regime makes one lightweight one — grouped
    # with the fast set by design intent, not mislabeled as zero-LLM.
    assert _calls_llm(technical_analyst_agent) is False
    assert _calls_llm(autoresearch_agent) is False
    assert _calls_llm(sentiment_analyst_agent) is False
    assert _calls_llm(market_regime_agent) is True

    # G2 slow pair: both make a full LLM call.
    assert _calls_llm(apex_agent) is True
    assert _calls_llm(news_sentiment_agent) is True


def test_run_hit_pulse_threads_fast_flag_into_strategy_ids(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    monkeypatch.setenv("SWARM_RUNS_DIR", str(tmp_path / "runs"))
    from app.backend.services import hit_service, paper_run_service

    monkeypatch.setattr(paper_run_service, "has_alpaca_keys", lambda: True)
    monkeypatch.setattr(paper_run_service, "assert_paper_only", lambda: None)
    monkeypatch.setattr(paper_run_service, "alpaca_trading_mode", lambda: "paper")
    monkeypatch.setattr(paper_run_service, "start_paper_run_async", lambda run_id: None)

    fast_payload = hit_service.run_hit_pulse(tickers=["NVDA"], fast=True)
    assert fast_payload["fast"] is True
    assert "apex" not in fast_payload["strategy_ids"]
    assert "news_sentiment_analyst" not in fast_payload["strategy_ids"]

    slow_payload = hit_service.run_hit_pulse(tickers=["NVDA"], fast=False)
    assert slow_payload["fast"] is False
    assert "apex" in slow_payload["strategy_ids"]
    assert "news_sentiment_analyst" in slow_payload["strategy_ids"]


def test_cron_and_automation_hit_pulse_request_models_default_fast_true():
    from app.backend.routes.automation import HitPulseRequest
    from app.backend.routes.cron import CronHitPulseRequest

    for model in (CronHitPulseRequest, HitPulseRequest):
        field = model.model_fields["fast"]
        assert field.default is True


def test_cron_and_automation_routes_pass_fast_to_run_hit_pulse():
    import inspect

    from app.backend.routes import automation as automation_routes
    from app.backend.routes import cron as cron_routes

    assert "fast=bool(body.fast)" in inspect.getsource(cron_routes.cron_hit_pulse)
    assert "fast=bool(body.fast)" in inspect.getsource(automation_routes.automation_hit_pulse)


# ── G2 Ops-visible amendment (Reviewer CHANGES_REQUIRED follow-up) ─────────
# Backend-only `fast` flag was live but had no Ops/UI copy; these tests back
# the fields the Strategies UI's HitOpsPanel now renders (badge + labeled
# analyst set + read-only run controls), so a Chrome reviewer can see "Fast
# HIT path" without digging into the API.


def test_read_hit_ops_always_includes_fast_path_labels_even_with_no_pulse_yet(
    monkeypatch, tmp_path
):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.hit_ops_service import read_hit_ops
    from app.backend.services.hit_service import (
        HIT_PRESET_ANALYST_IDS,
        HIT_SLOW_LLM_ANALYST_IDS,
    )

    ops = read_hit_ops()
    assert ops["last_pulse"] is None
    assert ops["fast_default"] is True
    assert ops["fast_path_analyst_ids"] == list(HIT_PRESET_ANALYST_IDS)
    assert ops["slow_path_analyst_ids"] == list(HIT_SLOW_LLM_ANALYST_IDS)
    assert "Fast HIT path" in ops["fast_path_note"]
    assert "apex" in ops["fast_path_note"] or "apex" in " ".join(ops["slow_path_analyst_ids"])


def test_record_hit_run_persists_fast_and_analyst_ids_on_last_pulse(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.hit_ops_service import read_hit_ops, record_hit_run

    record_hit_run(
        run_id="run-fast",
        execute_requested=False,
        execute_effective=False,
        trade_results=[],
        cost_gate_rejects=[],
        prices={},
        fast=True,
        analyst_ids=["technical_analyst", "market_regime", "autoresearch", "sentiment_analyst"],
    )
    fast_state = read_hit_ops()
    assert fast_state["last_pulse"]["fast"] is True
    assert fast_state["last_pulse"]["analyst_ids"] == [
        "technical_analyst",
        "market_regime",
        "autoresearch",
        "sentiment_analyst",
    ]

    record_hit_run(
        run_id="run-slow",
        execute_requested=False,
        execute_effective=False,
        trade_results=[],
        cost_gate_rejects=[],
        prices={},
        fast=False,
        analyst_ids=[
            "technical_analyst",
            "market_regime",
            "autoresearch",
            "sentiment_analyst",
            "apex",
            "news_sentiment_analyst",
        ],
    )
    slow_state = read_hit_ops()
    assert slow_state["last_pulse"]["fast"] is False
    assert "apex" in slow_state["last_pulse"]["analyst_ids"]
    assert "news_sentiment_analyst" in slow_state["last_pulse"]["analyst_ids"]


def test_record_hit_run_leaves_fast_and_analyst_ids_none_when_omitted(monkeypatch, tmp_path):
    """Backward compatibility — callers (or older records) that don't pass
    fast/analyst_ids at all must not have either field guessed/fabricated."""
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.hit_ops_service import read_hit_ops, record_hit_run

    record_hit_run(
        run_id="run-legacy",
        execute_requested=False,
        execute_effective=False,
        trade_results=[],
        cost_gate_rejects=[],
        prices={},
    )
    state = read_hit_ops()
    assert state["last_pulse"]["fast"] is None
    assert state["last_pulse"]["analyst_ids"] is None


def test_paper_run_service_derives_fast_from_actual_analyst_set_and_records_it():
    """Source-level check: paper_run_service must derive `fast` from the run's
    *actual* resolved analyst set (never re-guessed from a request flag that
    might not match what `_select_analysts` resolved), and must pass both
    `fast` and `analyst_ids` through to `record_hit_run`."""
    import inspect

    from app.backend.services import paper_run_service

    src = inspect.getsource(paper_run_service.execute_paper_run)
    assert "HIT_SLOW_LLM_ANALYST_IDS" in src
    assert "ran_slow_path" in src
    assert "fast=not ran_slow_path" in src
    assert "analyst_ids=list(analysts)" in src


# ── G3 — quote freshness (cost gate) ────────────────────────────────────────


def test_quote_age_ms_real_and_missing():
    from app.backend.services.cost_gate_service import quote_age_ms

    now = datetime(2024, 1, 1, 12, 0, 5, tzinfo=timezone.utc)
    assert quote_age_ms({"t": "2024-01-01T12:00:00Z"}, now=now) == pytest.approx(5000, abs=1)
    # Sub-microsecond digits are truncated (Python's fromisoformat can't parse
    # them) — this only shifts the result by sub-millisecond amounts.
    assert quote_age_ms({"t": "2024-01-01T12:00:00.123456789Z"}, now=now) == pytest.approx(
        4876.544, abs=1
    )
    assert quote_age_ms(None) is None
    assert quote_age_ms({}) is None
    assert quote_age_ms({"t": "not-a-timestamp"}) is None
    assert quote_age_ms("not-a-dict") is None


def test_evaluate_cost_gate_rejects_stale_quote():
    from app.backend.services.cost_gate_service import RULE_STALE_QUOTE, evaluate_cost_gate

    stale_quote = {"bp": 99.99, "ap": 100.01, "t": "2020-01-01T00:00:00Z"}  # years old
    result = evaluate_cost_gate(
        ticker="NVDA",
        action="buy",
        qty=10,
        price=100.0,
        equity=100_000.0,
        quote=stale_quote,
        max_quote_age_ms=5000,
    )
    assert result.approved is False
    assert result.rule == RULE_STALE_QUOTE
    assert result.quote_age_ms is not None
    assert result.quote_age_ms > 5000
    assert result.max_quote_age_ms == 5000


def test_evaluate_cost_gate_approves_fresh_quote():
    from app.backend.services.cost_gate_service import evaluate_cost_gate

    fresh_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    fresh_quote = {"bp": 99.99, "ap": 100.01, "t": fresh_ts}
    result = evaluate_cost_gate(
        ticker="NVDA",
        action="buy",
        qty=10,
        price=100.0,
        equity=100_000.0,
        quote=fresh_quote,
        max_quote_age_ms=5000,
    )
    assert result.approved is True
    assert result.quote_age_ms is not None
    assert result.quote_age_ms < 5000


def test_evaluate_cost_gate_ticker_class_default_never_marked_stale():
    from app.backend.services.cost_gate_service import evaluate_cost_gate

    result = evaluate_cost_gate(
        ticker="NVDA",
        action="buy",
        qty=10,
        price=100.0,
        equity=100_000.0,
        quote=None,
        max_quote_age_ms=5000,
    )
    assert result.quote_source == "ticker_class_default_assumed"
    assert result.quote_age_ms is None
    assert result.rule != "stale_quote"


def test_evaluate_cost_gate_exit_passes_even_with_a_stale_quote():
    from app.backend.services.cost_gate_service import evaluate_cost_gate

    stale_quote = {"bp": 99.99, "ap": 100.01, "t": "2020-01-01T00:00:00Z"}
    result = evaluate_cost_gate(
        ticker="NVDA",
        action="sell",
        qty=10,
        price=100.0,
        equity=100_000.0,
        quote=stale_quote,
    )
    assert result.approved is True


def test_default_max_quote_age_ms_env(monkeypatch):
    from app.backend.services.cost_gate_service import (
        DEFAULT_MAX_QUOTE_AGE_MS,
        default_max_quote_age_ms,
    )

    monkeypatch.delenv("SWARM_HIT_MAX_QUOTE_AGE_MS", raising=False)
    assert default_max_quote_age_ms() == DEFAULT_MAX_QUOTE_AGE_MS

    monkeypatch.setenv("SWARM_HIT_MAX_QUOTE_AGE_MS", "2500")
    assert default_max_quote_age_ms() == 2500.0


# ── G3 — optional read-only quote WS (pure/unit-testable surface only) ─────


def test_quote_ws_enabled_default_false_and_env_true(monkeypatch):
    from app.backend.services.hit_quote_ws_service import quote_ws_enabled

    monkeypatch.delenv("SWARM_HIT_QUOTE_WS_ENABLED", raising=False)
    assert quote_ws_enabled() is False

    monkeypatch.setenv("SWARM_HIT_QUOTE_WS_ENABLED", "true")
    assert quote_ws_enabled() is True

    monkeypatch.setenv("SWARM_HIT_QUOTE_WS_ENABLED", "false")
    assert quote_ws_enabled() is False


def test_parse_quote_message_extracts_quote_only_for_quote_type():
    from app.backend.services.hit_quote_ws_service import parse_quote_message

    quote_msg = {
        "T": "q",
        "S": "aapl",
        "bp": 150.10,
        "ap": 150.12,
        "bs": 1,
        "as": 2,
        "t": "2024-01-01T14:30:00.123456Z",
    }
    parsed = parse_quote_message(quote_msg)
    assert parsed is not None
    sym, quote = parsed
    assert sym == "AAPL"
    assert quote["bp"] == 150.10
    assert quote["ap"] == 150.12
    assert quote["t"] == "2024-01-01T14:30:00.123456Z"

    # Non-quote / malformed messages never parse.
    assert parse_quote_message({"T": "success", "msg": "authenticated"}) is None
    assert parse_quote_message({"T": "t", "S": "AAPL", "p": 150.1}) is None
    assert parse_quote_message({"T": "q"}) is None  # no symbol
    assert parse_quote_message("not-a-dict") is None
    assert parse_quote_message(None) is None


def test_parse_quote_messages_handles_list_and_json_string():
    from app.backend.services.hit_quote_ws_service import parse_quote_messages

    payload = [
        {"T": "success", "msg": "connected"},
        {"T": "q", "S": "SPY", "bp": 500.0, "ap": 500.05, "t": "2024-01-01T00:00:00Z"},
    ]
    parsed = parse_quote_messages(payload)
    assert len(parsed) == 1
    assert parsed[0][0] == "SPY"

    single = parse_quote_messages(
        json.dumps({"T": "q", "S": "QQQ", "bp": 1.0, "ap": 1.1, "t": "2024-01-01T00:00:00Z"})
    )
    assert len(single) == 1
    assert single[0][0] == "QQQ"

    assert parse_quote_messages("not json") == []
    assert parse_quote_messages(None) == []


def test_quote_cache_roundtrip_and_missing():
    from app.backend.services.hit_quote_ws_service import QuoteCache

    cache = QuoteCache()
    assert cache.get("AAPL") is None

    cache.set("aapl", {"bp": 1.0, "ap": 1.1, "t": "2024-01-01T00:00:00Z"})
    got = cache.get("AAPL")
    assert got is not None
    assert got["bp"] == 1.0
    assert "_cached_at" not in got  # internal bookkeeping never leaks out

    cache.clear()
    assert cache.get("AAPL") is None


def test_quote_cache_hard_evicts_stale_cache_residency():
    from app.backend.services.hit_quote_ws_service import (
        CACHE_HARD_EVICT_SECONDS,
        QuoteCache,
    )

    cache = QuoteCache()
    cache.set("AAPL", {"bp": 1.0, "ap": 1.1, "t": "2024-01-01T00:00:00Z"})
    cached_at = cache._store["AAPL"]["_cached_at"]

    # Just under the window — still served.
    assert cache.get("AAPL", now=cached_at + CACHE_HARD_EVICT_SECONDS - 1) is not None
    # Past the window — hard-evicted, never served.
    assert cache.get("AAPL", now=cached_at + CACHE_HARD_EVICT_SECONDS + 1) is None
    assert cache.get("AAPL") is None  # eviction is permanent, not a one-off miss


def test_quote_ws_start_is_noop_when_disabled(monkeypatch):
    from app.backend.services.hit_quote_ws_service import HitQuoteWebSocketClient

    monkeypatch.delenv("SWARM_HIT_QUOTE_WS_ENABLED", raising=False)
    client = HitQuoteWebSocketClient()
    assert client.start(["AAPL"]) is False
    assert client.is_running() is False


def test_quote_ws_start_is_noop_without_credentials(monkeypatch):
    from app.backend.services.hit_quote_ws_service import HitQuoteWebSocketClient

    monkeypatch.setenv("SWARM_HIT_QUOTE_WS_ENABLED", "true")
    monkeypatch.setattr(
        "src.tools.alpaca_data.alpaca_credentials_configured", lambda: False
    )
    client = HitQuoteWebSocketClient()
    assert client.start(["AAPL"]) is False
    assert client.is_running() is False


def test_quote_ws_single_connection_discipline(monkeypatch):
    """Alpaca allows exactly one stream connection per feed/account — a
    second start() must be refused outright, never queued or duplicated.
    The live-socket loop is monkeypatched out; no real network call."""
    import asyncio

    from app.backend.services.hit_quote_ws_service import HitQuoteWebSocketClient

    monkeypatch.setenv("SWARM_HIT_QUOTE_WS_ENABLED", "true")
    monkeypatch.setattr(
        "src.tools.alpaca_data.alpaca_credentials_configured", lambda: True
    )

    async def fake_run_async(self, tickers):
        await asyncio.sleep(0.3)

    monkeypatch.setattr(HitQuoteWebSocketClient, "_run_async", fake_run_async)

    client = HitQuoteWebSocketClient()
    try:
        assert client.start(["AAPL", "SPY"]) is True
        assert client.is_running() is True
        # Discipline: a second start() while running is refused, not queued.
        assert client.start(["AAPL", "SPY"]) is False
        assert client.is_running() is True  # first connection untouched
    finally:
        client.stop(timeout=2)
    assert client.is_running() is False


def test_get_cached_quote_returns_none_when_ws_never_started():
    from app.backend.services.hit_quote_ws_service import get_cached_quote

    assert get_cached_quote("AAPL") is None


def test_fetch_quotes_and_prices_prefers_ws_cache_over_rest(monkeypatch):
    """G3 — cost_gate_service.fetch_quotes_and_prices checks the WS cache
    first; only falls back to REST on a cache miss."""
    from app.backend.services import cost_gate_service, hit_quote_ws_service

    monkeypatch.setattr(
        "src.tools.alpaca_data.alpaca_credentials_configured", lambda: True
    )
    ws_quote = {"bp": 199.0, "ap": 199.10, "t": "2024-01-01T00:00:00Z"}
    hit_quote_ws_service.get_client().cache.set("NVDA", ws_quote)

    rest_called = {"count": 0}

    def fake_rest_quote(sym, feed=None, timeout=15):
        rest_called["count"] += 1
        return {"bp": 1.0, "ap": 1.1, "t": "2024-01-01T00:00:00Z"}

    monkeypatch.setattr("src.tools.alpaca_data.get_latest_quote", fake_rest_quote)

    prices, quotes = cost_gate_service.fetch_quotes_and_prices(["NVDA"])
    assert quotes["NVDA"] == ws_quote
    assert prices["NVDA"] == pytest.approx((199.0 + 199.10) / 2.0)
    assert rest_called["count"] == 0  # REST never called — WS cache hit


def test_fetch_quotes_and_prices_falls_back_to_rest_on_ws_cache_miss(monkeypatch):
    from app.backend.services import cost_gate_service

    monkeypatch.setattr(
        "src.tools.alpaca_data.alpaca_credentials_configured", lambda: True
    )

    def fake_rest_quote(sym, feed=None, timeout=15):
        return {"bp": 100.0, "ap": 100.10, "t": "2024-01-01T00:00:00Z"}

    monkeypatch.setattr("src.tools.alpaca_data.get_latest_quote", fake_rest_quote)

    prices, quotes = cost_gate_service.fetch_quotes_and_prices(["AAPL"])
    assert quotes["AAPL"]["bp"] == 100.0
    assert prices["AAPL"] == pytest.approx(100.05)


# ── G4 — latency observatory ─────────────────────────────────────────────


def test_post_order_with_timing_captures_client_submit_and_broker_ack(monkeypatch):
    from src import alpaca_integration as ai

    class FakeResp:
        status_code = 200

        def json(self):
            return {"id": "abc", "status": "accepted", "created_at": "2024-01-01T00:00:00Z"}

    monkeypatch.setattr(ai.requests, "post", lambda *a, **k: FakeResp())

    order, timing, resp = ai._post_order_with_timing("http://x/orders", {}, {"symbol": "NVDA"})
    assert order["id"] == "abc"
    assert timing["broker_ack_at"] == "2024-01-01T00:00:00Z"
    assert timing["client_submit_at"] is not None


def test_post_order_with_timing_failure_has_client_submit_but_no_broker_ack(monkeypatch):
    from src import alpaca_integration as ai

    class FakeResp:
        status_code = 422
        text = "bad request"

    monkeypatch.setattr(ai.requests, "post", lambda *a, **k: FakeResp())

    order, timing, resp = ai._post_order_with_timing("http://x/orders", {}, {"symbol": "NVDA"})
    assert order is None
    assert timing["broker_ack_at"] is None
    assert timing["client_submit_at"] is not None


def test_execute_decisions_attaches_decision_at_to_placed_orders(monkeypatch):
    from src import alpaca_integration as ai

    def fake_place(ticker, action, qty, mode=None):
        return {
            "success": True,
            "order_id": "o1",
            "status": "filled",
            "client_submit_at": "2024-01-01T00:00:00.000Z",
            "broker_ack_at": "2024-01-01T00:00:00.010Z",
            "submitted_at": "2024-01-01T00:00:00.010Z",
            "filled_at": "2024-01-01T00:00:00.050Z",
        }

    monkeypatch.setattr(ai, "_place_alpaca_order", fake_place)

    # "sell" bypasses the risk_manager branch entirely (exits always pass) —
    # keeps this test a pure unit test of decision_at wiring, no network.
    decisions = {"NVDA": {"action": "sell", "quantity": 1, "confidence": 0.9}}
    results = ai.execute_decisions(
        decisions,
        positions_raw=[{"symbol": "NVDA", "qty": 1, "current_price": 100.0}],
        account={},
        dry_run=False,
        mode="hit",
        decision_at="2023-12-31T23:59:59.900Z",
    )
    assert len(results) == 1
    assert results[0]["decision_at"] == "2023-12-31T23:59:59.900Z"
    assert results[0]["broker_ack_at"] == "2024-01-01T00:00:00.010Z"


def test_execute_decisions_omits_decision_at_when_not_provided(monkeypatch):
    from src import alpaca_integration as ai

    monkeypatch.setattr(
        ai,
        "_place_alpaca_order",
        lambda ticker, action, qty, mode=None: {"success": True, "order_id": "o1"},
    )
    decisions = {"NVDA": {"action": "sell", "quantity": 1, "confidence": 0.9}}
    results = ai.execute_decisions(
        decisions,
        positions_raw=[{"symbol": "NVDA", "qty": 1, "current_price": 100.0}],
        account={},
        dry_run=False,
        mode="hit",
    )
    assert "decision_at" not in results[0]  # never fabricated when not given


def test_latency_breakdown_full_stages_present():
    from app.backend.services.hit_ops_service import _latency_breakdown

    row = {
        "ticker": "NVDA",
        "order_id": "o1",
        "decision_at": "2026-01-01T14:29:59.500Z",
        "client_submit_at": "2026-01-01T14:29:59.700Z",
        "broker_ack_at": "2026-01-01T14:29:59.750Z",
        "submitted_at": "2026-01-01T14:29:59.750Z",
        "filled_at": "2026-01-01T14:30:00.000Z",
    }
    breakdown = _latency_breakdown(row)
    assert breakdown is not None
    assert breakdown["decision_to_submit_ms"] == 200
    assert breakdown["submit_to_ack_ms"] == 50
    assert breakdown["ack_to_fill_ms"] == 250
    assert breakdown["decision_to_fill_ms"] == 500
    assert breakdown["latency_ms"] == 250  # F5 measure unchanged


def test_latency_breakdown_missing_decision_and_ack_leaves_them_blank():
    from app.backend.services.hit_ops_service import _latency_breakdown

    row = {
        "ticker": "AAPL",
        "order_id": "o2",
        "client_submit_at": "2026-01-01T14:29:59.700Z",
        "filled_at": "2026-01-01T14:30:00.000Z",
        # no decision_at, no broker_ack_at, no submitted_at
    }
    breakdown = _latency_breakdown(row)
    assert breakdown is not None
    assert breakdown["decision_to_submit_ms"] is None
    assert breakdown["submit_to_ack_ms"] is None
    assert breakdown["ack_to_fill_ms"] is None
    assert breakdown["decision_to_fill_ms"] is None
    assert breakdown["latency_ms"] is None  # legacy measure needs submitted_at


def test_latency_breakdown_none_without_filled_at():
    from app.backend.services.hit_ops_service import _latency_breakdown

    assert _latency_breakdown({"ticker": "AAPL", "decision_at": "x", "client_submit_at": "y"}) is None


def test_latency_breakdown_none_with_only_filled_at():
    from app.backend.services.hit_ops_service import _latency_breakdown

    assert _latency_breakdown({"ticker": "AAPL", "filled_at": "2026-01-01T14:30:00.000Z"}) is None


def test_latency_breakdown_backward_compat_with_wave_f_row_shape():
    """Exact Wave F test-fixture row shape (submitted_at/filled_at only)
    must still produce latency_ms == 250, unchanged."""
    from app.backend.services.hit_ops_service import _latency_breakdown

    row = {
        "ticker": "NVDA",
        "qty": 10,
        "success": True,
        "order_id": "o1",
        "submitted_at": "2026-03-09T14:30:00.000Z",
        "filled_at": "2026-03-09T14:30:00.250Z",
    }
    breakdown = _latency_breakdown(row)
    assert breakdown is not None
    assert breakdown["latency_ms"] == 250


def test_record_hit_run_includes_latency_note(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.hit_ops_service import LATENCY_NOTE, record_hit_run

    state = record_hit_run(
        run_id="run-g4",
        execute_requested=True,
        execute_effective=True,
        trade_results=[],
        cost_gate_rejects=[],
        prices={},
    )
    assert state["latency_note"] == LATENCY_NOTE


# ── G5 — hit-pulse stays analysis-default; dual gate unchanged ────────────


def test_dual_gate_truth_table_unchanged_by_wave_g(monkeypatch):
    from app.backend.services.hit_ops_service import (
        hit_execute_env_allows,
        resolve_hit_execute,
    )

    monkeypatch.delenv("SWARM_HIT_EXECUTE", raising=False)
    assert hit_execute_env_allows() is False
    assert resolve_hit_execute(True) is False
    assert resolve_hit_execute(False) is False

    monkeypatch.setenv("SWARM_HIT_EXECUTE", "true")
    assert hit_execute_env_allows() is True
    assert resolve_hit_execute(True) is True
    assert resolve_hit_execute(False) is False

    monkeypatch.setenv("SWARM_HIT_EXECUTE", "false")
    assert resolve_hit_execute(True) is False


def test_fast_flag_never_influences_the_execute_dual_gate(monkeypatch, tmp_path):
    """fast=False (opt into the slow analyst path) must not, by itself,
    enable execute — that is still SWARM_HIT_EXECUTE ∧ execute_trades=true,
    completely independent of the analyst-selection flag."""
    _isolate_automation(monkeypatch, tmp_path)
    monkeypatch.setenv("SWARM_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.delenv("SWARM_HIT_EXECUTE", raising=False)
    from app.backend.services import hit_service, paper_run_service

    monkeypatch.setattr(paper_run_service, "has_alpaca_keys", lambda: True)
    monkeypatch.setattr(paper_run_service, "assert_paper_only", lambda: None)
    monkeypatch.setattr(paper_run_service, "alpaca_trading_mode", lambda: "paper")
    monkeypatch.setattr(paper_run_service, "start_paper_run_async", lambda run_id: None)

    payload = hit_service.run_hit_pulse(
        tickers=["NVDA"], execute_requested=True, fast=False
    )
    assert payload["fast"] is False
    assert payload["execute_trades"] is False  # env absent -> dual gate blocks it


# ── G6 — docs + build-info flags ────────────────────────────────────────────


def test_build_info_has_wave_g_flags():
    src = (ROOT / "app/backend/routes/build_info.py").read_text(encoding="utf-8")
    for flag in (
        "hit-fast-path",
        "hit-quote-freshness-gate",
        "hit-quote-ws-optional",
        "hit-latency-observatory",
        "hit-fast-path-ops-visible",
    ):
        assert flag in src


def test_wave_g_doc_states_not_colocated_hft_and_references_ux15():
    doc = (ROOT / "docs/WAVE_G_LATENCY_MAX.md").read_text(encoding="utf-8")
    assert "strategies-ux-15" in doc
    assert "colocated microsecond HFT" in doc
    assert "cannot honestly" in doc
    assert "SWARM_HIT_MAX_QUOTE_AGE_MS" in doc
    assert "SWARM_HIT_QUOTE_WS_ENABLED" in doc
    assert "single-connection" in doc.lower()


def test_wave_g_doc_documents_g2_ops_visible_amendment_and_ux16():
    """Reviewer CHANGES_REQUIRED follow-up — G2's fast/slow path must be
    documented as Ops-visible (not just an API field), and the doc must
    reference the bumped image tag."""
    doc = (ROOT / "docs/WAVE_G_LATENCY_MAX.md").read_text(encoding="utf-8")
    assert "strategies-ux-16" in doc
    assert "Ops-visible" in doc
    assert "HitOpsPanel" in doc


def test_docker_compose_image_tag_bumped_to_ux16():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "strategies-ux-16" in compose
    assert "strategies-ux-15" not in compose


def test_wave_f_doc_cross_links_wave_g():
    doc = (ROOT / "docs/WAVE_F_HIT.md").read_text(encoding="utf-8")
    assert "WAVE_G_LATENCY_MAX.md" in doc


def test_compose_hit_quote_env_defaults_are_safe():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "SWARM_HIT_MAX_QUOTE_AGE_MS: ${SWARM_HIT_MAX_QUOTE_AGE_MS:-5000}" in compose
    assert "SWARM_HIT_QUOTE_WS_ENABLED: ${SWARM_HIT_QUOTE_WS_ENABLED:-false}" in compose


def test_no_wave_g_module_writes_swarm_monitor_dry_run():
    """Hard out (still true): nothing in Wave G touches SWARM_MONITOR_DRY_RUN."""
    for relpath in (
        "app/backend/services/hit_service.py",
        "app/backend/services/cost_gate_service.py",
        "app/backend/services/hit_quote_ws_service.py",
        "app/backend/services/hit_ops_service.py",
    ):
        src = (ROOT / relpath).read_text(encoding="utf-8")
        assert "SWARM_MONITOR_DRY_RUN" not in src


def test_no_order_or_trade_updates_websocket_added_by_wave_g():
    """G3 adds only a read-only *quote* WS — never an order/trade_updates
    stream, and never a place/cancel-order call anywhere in that module.

    The module's own docstring explains *why* no order stream is added, so
    the word "trade_updates" legitimately appears in prose there — this test
    instead asserts on structure: the module sends exactly one subscribe
    action (quotes only) and never imports ``src.alpaca_integration`` (the
    only place order-placement/cancellation code lives), which makes it
    structurally impossible for this module to place, cancel, or watch an
    order."""
    import ast

    src = (ROOT / "app/backend/services/hit_quote_ws_service.py").read_text(encoding="utf-8")
    assert '"action": "subscribe", "quotes": tickers' in src  # the one and only subscribe action

    tree = ast.parse(src)
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "alpaca_integration" not in imported_names
    assert not any(m and "alpaca_integration" in m for m in imported_modules)

    # No call expression anywhere in the module invokes an order-placement
    # function — only explanatory prose (docstrings/comments) may mention
    # their names, which this AST check does not see.
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    called_attrs = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("place_order", "cancel_order", "_place_alpaca_order", "execute_decisions"):
        assert forbidden not in called_names
        assert forbidden not in called_attrs
