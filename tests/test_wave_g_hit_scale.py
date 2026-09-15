"""James t180u — HIT analysis/flow must cover hundreds of tickers, not the
previous ~10-15 ceiling. Every ceiling raised here is mode/preset-aware:
hit unlocks hundreds, every other mode/preset keeps the original small cap
unchanged. No test in this file touches the execute dual gate, the F2/G3
cost gate, any risk/trade cap, or the "not true HFT" claims — those stay
exactly as Wave F/G shipped them (see test_wave_f_hit.py /
test_wave_g_latency_max.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _isolate_automation(monkeypatch, tmp_path):
    monkeypatch.setenv("SWARM_AUTOMATION_DIR", str(tmp_path / "automation"))
    from app.backend.services import automation_store as store

    store.AUTOMATION_DIR = tmp_path / "automation"
    return store


class _FakeResponse:
    def __init__(self, payload: Dict[str, Any]):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Dict[str, Any]:
        return self._payload


# ── scan_market.py — HIT-scale ceiling + request scaling ──────────────────


def test_hit_max_tickers_is_hundreds_default_unchanged():
    import scan_market

    assert scan_market.HIT_MAX_TICKERS >= 250
    assert scan_market.DEFAULT_MAX_TICKERS == 25


def test_get_movers_and_most_active_clamp_top_to_screener_cap(monkeypatch):
    import scan_market

    captured: Dict[str, Any] = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"] = url
        captured["top"] = params.get("top")
        return _FakeResponse({"gainers": [], "losers": [], "most_actives": []})

    monkeypatch.setattr(scan_market.requests, "get", fake_get)

    scan_market.get_movers(top=999)
    assert captured["top"] == scan_market._SCREENER_TOP_CAP

    scan_market.get_most_active(top=999)
    assert captured["top"] == scan_market._SCREENER_TOP_CAP

    scan_market.get_movers(top=5)
    assert captured["top"] == 5


def test_get_snapshots_chunks_instead_of_truncating(monkeypatch):
    import scan_market

    calls: List[List[str]] = []

    def fake_get(url, headers=None, params=None, timeout=None):
        symbols = params["symbols"].split(",")
        calls.append(symbols)
        return _FakeResponse({s: {"latestTrade": {"p": 100.0}} for s in symbols})

    monkeypatch.setattr(scan_market.requests, "get", fake_get)

    many = [f"T{i:03d}" for i in range(120)]
    out = scan_market.get_snapshots(many, batch_size=50)

    # 120 symbols / 50 per batch -> 3 calls, none exceeding batch_size
    assert len(calls) == 3
    assert all(len(c) <= 50 for c in calls)
    # Every symbol got a lookup attempt — nothing silently dropped past the
    # first 50 (the pre-t180u behavior only requested the first 50).
    assert len(out) == 120
    assert "T000" in out and "T119" in out


def test_scan_scales_raw_pull_size_with_max_tickers(monkeypatch):
    import scan_market

    captured: Dict[str, int] = {}

    def fake_get_movers(top: int = 20) -> dict:
        captured["movers_top"] = top
        return {"gainers": [], "losers": []}

    def fake_get_most_active(top: int = 50) -> list:
        captured["actives_top"] = top
        return []

    monkeypatch.setattr(scan_market, "get_movers", fake_get_movers)
    monkeypatch.setattr(scan_market, "get_most_active", fake_get_most_active)

    scan_market.scan(max_tickers=300, include_core=False)
    assert captured["movers_top"] == scan_market._SCREENER_TOP_CAP
    assert captured["actives_top"] == scan_market._SCREENER_TOP_CAP

    captured.clear()
    scan_market.scan(max_tickers=10, include_core=False)
    # Small max_tickers still requests at least the original small defaults
    # (20/50) — never scaled *down* below the pre-t180u baseline.
    assert captured["movers_top"] >= 20
    assert captured["actives_top"] >= 50


# ── automation_store.py — mode/preset-aware apply/recipe ceiling ──────────


def test_hit_apply_recipe_max_is_at_least_200():
    from app.backend.services import automation_store as store

    assert store.HIT_APPLY_RECIPE_MAX >= 200
    assert store.APPLY_RECIPE_MAX == 15


def test_apply_recipe_max_for_is_mode_and_preset_aware():
    from app.backend.services.automation_store import (
        APPLY_RECIPE_MAX,
        HIT_APPLY_RECIPE_MAX,
        apply_recipe_max_for,
    )

    assert apply_recipe_max_for("hit", None) == HIT_APPLY_RECIPE_MAX
    assert apply_recipe_max_for(None, "hit") == HIT_APPLY_RECIPE_MAX
    assert apply_recipe_max_for("HIT", None) == HIT_APPLY_RECIPE_MAX  # case-insensitive
    assert apply_recipe_max_for("swing", None) == APPLY_RECIPE_MAX
    assert apply_recipe_max_for("day", "quant") == APPLY_RECIPE_MAX
    assert apply_recipe_max_for(None, None) == APPLY_RECIPE_MAX


def test_write_cron_recipe_persists_hundreds_for_hit_mode(monkeypatch, tmp_path):
    store = _isolate_automation(monkeypatch, tmp_path)

    many = [f"T{i:03d}" for i in range(250)]
    saved = store.write_cron_recipe({"tickers": many, "mode": "hit", "preset": "hit"})
    assert len(saved["tickers"]) == 250

    reread = store.read_cron_recipe()
    assert len(reread["tickers"]) == 250


def test_write_cron_recipe_still_clamps_swing_to_20(monkeypatch, tmp_path):
    store = _isolate_automation(monkeypatch, tmp_path)

    many = [f"T{i:03d}" for i in range(250)]
    saved = store.write_cron_recipe({"tickers": many, "mode": "swing"})
    assert len(saved["tickers"]) == 20


def test_scan_ops_summary_and_history_preview_scale_with_hit_mode(monkeypatch, tmp_path):
    store = _isolate_automation(monkeypatch, tmp_path)

    many = [f"T{i:03d}" for i in range(250)]
    store.write_last_scan(
        {
            "tickers": many,
            "candidates": [{"symbol": t, "sources": ["mover"]} for t in many],
            "candidate_count": len(many),
            "mode": "hit",
        }
    )
    ops = store.read_ops_status()
    last_scan_summary = ops.get("last_scan") or {}
    # candidate_count is never truncated regardless of mode.
    assert last_scan_summary.get("candidate_count") == 250
    # The preview ticker list is now mode-aware (hundreds for hit).
    assert len(last_scan_summary.get("tickers") or []) > 15

    hist = store.read_scan_history(limit=5)
    assert hist and hist[0]["candidate_count"] == 250
    assert len(hist[0]["tickers"]) > 15


# ── swarm_scan_service.py — mode-aware scan/apply defaults ─────────────────


def test_run_swarm_scan_max_tickers_none_resolves_by_mode(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    import scan_market
    from app.backend.services import swarm_scan_service as sss

    captured: Dict[str, int] = {}

    def fake_scan(*, min_price, min_trades, max_tickers, include_core):
        captured["max_tickers"] = max_tickers
        return {"timestamp": "t", "core_watchlist": [], "discovered": [], "tickers": []}

    monkeypatch.setattr(scan_market, "scan", fake_scan)

    sss.run_swarm_scan(mode="hit", persist=False)
    assert captured["max_tickers"] == scan_market.HIT_MAX_TICKERS

    sss.run_swarm_scan(mode="swing", persist=False)
    assert captured["max_tickers"] == scan_market.DEFAULT_MAX_TICKERS

    # Explicit override still wins regardless of mode.
    sss.run_swarm_scan(mode="hit", max_tickers=7, persist=False)
    assert captured["max_tickers"] == 7


def test_apply_scan_to_recipe_default_top_n_scales_with_hit_mode(monkeypatch, tmp_path):
    store = _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.automation_store import HIT_APPLY_RECIPE_MAX
    from app.backend.services.swarm_scan_service import apply_scan_to_recipe

    many = [f"T{i:03d}" for i in range(250)]
    store.write_last_scan(
        {
            "tickers": many,
            "candidates": [{"symbol": t, "sources": ["mover"]} for t in many],
            "candidate_count": len(many),
            "mode": "hit",
        }
    )

    result = apply_scan_to_recipe(mode="hit")  # top_n omitted -> full hit cap
    assert result["cap"] == HIT_APPLY_RECIPE_MAX
    assert result["applied_count"] == min(len(many), HIT_APPLY_RECIPE_MAX)
    # mode="hit" was explicitly requested -> the saved recipe is stamped hit,
    # so a re-read never silently re-clamps the ticker list back to 20.
    assert result["recipe"]["mode"] == "hit"
    assert len(result["recipe"]["tickers"]) == result["applied_count"]


def test_apply_scan_to_recipe_swing_default_unchanged(monkeypatch, tmp_path):
    store = _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.swarm_scan_service import apply_scan_to_recipe

    many = [f"T{i:03d}" for i in range(30)]
    store.write_last_scan(
        {
            "tickers": many,
            "candidates": [{"symbol": t, "sources": ["mover"]} for t in many],
            "candidate_count": len(many),
            "mode": "swing",
        }
    )

    result = apply_scan_to_recipe(mode="swing")  # top_n omitted
    assert result["cap"] == 15
    assert result["applied_count"] == 15


def test_apply_scan_to_recipe_explicit_top_n_still_honored(monkeypatch, tmp_path):
    store = _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.swarm_scan_service import apply_scan_to_recipe

    many = [f"T{i:03d}" for i in range(250)]
    store.write_last_scan(
        {
            "tickers": many,
            "candidates": [{"symbol": t, "sources": ["mover"]} for t in many],
            "candidate_count": len(many),
            "mode": "hit",
        }
    )

    result = apply_scan_to_recipe(top_n=40, mode="hit")
    assert result["applied_count"] == 40


# ── src/config.py — widened HIT universe, still no leveraged ETFs ─────────


def test_hit_universe_widened_and_leveraged_etf_free():
    from src.config import MODES

    universe = MODES["hit"]["universe"]
    all_tickers: List[str] = []
    for bucket in universe.values():
        all_tickers.extend(bucket["tickers"])

    assert len(all_tickers) >= 100
    assert len(all_tickers) == len(set(all_tickers)), "no duplicate tickers across buckets"
    assert MODES["hit"]["risk"]["allow_leveraged_etfs"] is False

    import risk_manager as rm

    assert set(all_tickers) & rm.LEVERAGED_ETFS == set()
    assert set(all_tickers) & rm.MOONSHOTS == set()
    assert "SPY" in all_tickers and "QQQ" in all_tickers


def test_hit_universe_tickers_can_return_full_widened_list():
    from app.backend.services.hit_service import hit_universe_tickers

    from src.config import MODES

    full_size = sum(len(b["tickers"]) for b in MODES["hit"]["universe"].values())
    assert len(hit_universe_tickers(cap=0)) == full_size
    assert len(hit_universe_tickers(cap=300)) == full_size  # cap larger than universe


# ── hit_service.py — raised ceiling, unchanged default, auto-fast rail ────


def test_hit_max_tickers_ceiling_and_unchanged_default():
    from app.backend.services.hit_service import DEFAULT_HIT_TICKER_CAP, HIT_MAX_TICKERS

    assert HIT_MAX_TICKERS >= 250
    assert DEFAULT_HIT_TICKER_CAP == 10  # unspecified top_n stays exactly as fast as before


def _patch_paper_run_service(monkeypatch):
    from app.backend.services import paper_run_service

    monkeypatch.setattr(paper_run_service, "has_alpaca_keys", lambda: True)
    monkeypatch.setattr(paper_run_service, "assert_paper_only", lambda: None)
    monkeypatch.setattr(paper_run_service, "alpaca_trading_mode", lambda: "paper")
    monkeypatch.setattr(paper_run_service, "start_paper_run_async", lambda run_id: None)


def test_run_hit_pulse_accepts_hundreds_of_explicit_tickers(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    monkeypatch.setenv("SWARM_RUNS_DIR", str(tmp_path / "runs"))
    from app.backend.services import hit_service

    _patch_paper_run_service(monkeypatch)

    many = [f"T{i:03d}" for i in range(250)]
    payload = hit_service.run_hit_pulse(tickers=many, top_n=250, fast=True)
    assert payload["ticker_count"] == 250
    assert len(payload["tickers"]) == 250
    assert payload["fast"] is True
    assert payload["auto_fast_override"] is False


def test_run_hit_pulse_falls_back_to_widened_universe_for_large_top_n(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    monkeypatch.setenv("SWARM_RUNS_DIR", str(tmp_path / "runs"))
    from app.backend.services import hit_service
    from src.config import MODES

    _patch_paper_run_service(monkeypatch)

    universe_size = sum(len(b["tickers"]) for b in MODES["hit"]["universe"].values())
    payload = hit_service.run_hit_pulse(top_n=300)  # no explicit tickers, no recipe
    # Capped by the widened universe's own size — never fabricated beyond it.
    assert payload["ticker_count"] == universe_size
    assert len(payload["tickers"]) == universe_size


def test_run_hit_pulse_auto_fast_override_above_threshold(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    monkeypatch.setenv("SWARM_RUNS_DIR", str(tmp_path / "runs"))
    from app.backend.services import hit_service

    _patch_paper_run_service(monkeypatch)

    many = [f"T{i:03d}" for i in range(50)]  # > HIT_AUTO_FAST_TICKER_THRESHOLD (30)
    payload = hit_service.run_hit_pulse(tickers=many, top_n=50, fast=False)

    assert payload["fast_requested"] is False
    assert payload["auto_fast_override"] is True
    assert payload["fast"] is True  # overridden back to fast despite the explicit ask
    assert "apex" not in payload["strategy_ids"]
    assert "news_sentiment_analyst" not in payload["strategy_ids"]
    assert "auto-overridden" in payload["fast_path_note"]


def test_run_hit_pulse_small_slow_path_request_not_overridden(monkeypatch, tmp_path):
    """Boundary check: a slow-path request at/under the threshold is honored
    exactly as G2 originally specified — the auto-fast rail must not fire
    for ordinary, small explicit slow-path asks."""
    _isolate_automation(monkeypatch, tmp_path)
    monkeypatch.setenv("SWARM_RUNS_DIR", str(tmp_path / "runs"))
    from app.backend.services import hit_service

    _patch_paper_run_service(monkeypatch)

    exactly_thirty = [f"T{i:03d}" for i in range(30)]
    payload = hit_service.run_hit_pulse(tickers=exactly_thirty, top_n=30, fast=False)

    assert payload["auto_fast_override"] is False
    assert payload["fast"] is False
    assert "apex" in payload["strategy_ids"]
    assert "news_sentiment_analyst" in payload["strategy_ids"]


# ── Request-model ceilings — hit unlocks hundreds, everything else unchanged ─


def test_paper_run_request_allows_hundreds_for_hit_mode_only():
    from app.backend.models.schemas import PaperRunRequest

    many = [f"T{i:03d}" for i in range(250)]
    req = PaperRunRequest(tickers=many, mode="hit")
    assert len(req.tickers) == 250

    with pytest.raises(Exception):
        PaperRunRequest(tickers=many, mode="swing")

    with pytest.raises(Exception):
        PaperRunRequest(tickers=many)  # mode omitted -> defaults to the non-hit cap


def test_cron_paper_run_request_allows_hundreds_for_hit_mode_only():
    from app.backend.routes.cron import CronPaperRunRequest

    many = [f"T{i:03d}" for i in range(200)]
    req = CronPaperRunRequest(tickers=many, mode="hit")
    assert len(req.tickers) == 200

    with pytest.raises(Exception):
        CronPaperRunRequest(tickers=many, mode="swing")


def test_cron_recipe_body_allows_hundreds_for_hit_mode_or_preset():
    from app.backend.routes.automation import CronRecipeBody

    many = [f"T{i:03d}" for i in range(200)]
    req = CronRecipeBody(tickers=many, mode="hit")
    assert len(req.tickers) == 200

    req2 = CronRecipeBody(tickers=many, preset="hit")
    assert len(req2.tickers) == 200

    with pytest.raises(Exception):
        CronRecipeBody(tickers=many, mode="swing")

    with pytest.raises(Exception):
        CronRecipeBody(tickers=many)  # mode/preset both omitted -> non-hit cap


def test_cron_hit_pulse_request_top_n_ceiling_raised():
    from app.backend.routes.cron import CronHitPulseRequest
    from app.backend.services.hit_service import HIT_MAX_TICKERS

    req = CronHitPulseRequest(top_n=250)
    assert req.top_n == 250
    assert type(req).model_fields["top_n"].default == 10  # unspecified default unchanged

    with pytest.raises(Exception):
        CronHitPulseRequest(top_n=HIT_MAX_TICKERS + 1)


def test_automation_hit_pulse_request_top_n_ceiling_raised():
    from app.backend.routes.automation import HitPulseRequest
    from app.backend.services.hit_service import HIT_MAX_TICKERS

    req = HitPulseRequest(top_n=250)
    assert req.top_n == 250
    assert type(req).model_fields["top_n"].default == 10

    with pytest.raises(Exception):
        HitPulseRequest(top_n=HIT_MAX_TICKERS + 1)


def test_apply_scan_request_top_n_ceiling_raised():
    from app.backend.routes.automation import ApplyScanRequest
    from app.backend.services.automation_store import HIT_APPLY_RECIPE_MAX

    req = ApplyScanRequest(top_n=250)
    assert req.top_n == 250
    assert type(req).model_fields["top_n"].default is None  # omitted -> full mode-aware cap

    with pytest.raises(Exception):
        ApplyScanRequest(top_n=HIT_APPLY_RECIPE_MAX + 1)


def test_swarm_scan_request_max_tickers_ceiling_raised():
    from app.backend.routes.automation import SwarmScanRequest

    req = SwarmScanRequest(max_tickers=250)
    assert req.max_tickers == 250
    assert type(req).model_fields["max_tickers"].default is None


def test_cron_swarm_scan_request_top_n_ceiling_raised():
    from app.backend.routes.cron import CronSwarmScanRequest
    from app.backend.services.automation_store import HIT_APPLY_RECIPE_MAX

    req = CronSwarmScanRequest(top_n=250)
    assert req.top_n == 250
    assert type(req).model_fields["top_n"].default == 15  # swing/day default unchanged

    with pytest.raises(Exception):
        CronSwarmScanRequest(top_n=HIT_APPLY_RECIPE_MAX + 1)


# ── Ops-visible universe/ticker counts (ties into the G2 Ops-visible amendment) ─


def test_read_hit_ops_includes_universe_size_and_max_tickers(monkeypatch, tmp_path):
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.hit_ops_service import read_hit_ops
    from app.backend.services.hit_service import HIT_MAX_TICKERS
    from src.config import MODES

    ops = read_hit_ops()
    expected_size = sum(len(b["tickers"]) for b in MODES["hit"]["universe"].values())
    assert ops["hit_universe_size"] == expected_size
    assert ops["hit_max_tickers"] == HIT_MAX_TICKERS
    assert "hundreds" in ops["hit_scale_note"].lower()


def test_record_hit_run_persists_ticker_count_free_form(monkeypatch, tmp_path):
    """last_pulse doesn't need a dedicated ticker_count field on the ops-store
    side — the Strategies UI reads ticker_count directly from the
    run_hit_pulse response; this just confirms record_hit_run doesn't choke
    on a large trade_results list (sanity, not a real trading scenario)."""
    _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.hit_ops_service import read_hit_ops, record_hit_run

    trade_results = [{"ticker": f"T{i:03d}", "success": False, "skipped": True} for i in range(50)]
    record_hit_run(
        run_id="run-hit-scale",
        execute_requested=False,
        execute_effective=False,
        trade_results=trade_results,
        cost_gate_rejects=[],
        prices={},
        fast=True,
        analyst_ids=["technical_analyst", "market_regime", "autoresearch", "sentiment_analyst"],
    )
    state = read_hit_ops()
    assert state["last_pulse"]["run_id"] == "run-hit-scale"


def test_build_info_has_hit_hundreds_scale_flag():
    src = (ROOT / "app/backend/routes/build_info.py").read_text(encoding="utf-8")
    assert "hit-hundreds-scale" in src


def test_wave_g_doc_documents_james_t180u_hit_scale():
    doc = (ROOT / "docs/WAVE_G_LATENCY_MAX.md").read_text(encoding="utf-8")
    assert "t180u" in doc
    assert "hundreds" in doc.lower()
    assert "HIT_MAX_TICKERS" in doc
    assert "HIT_APPLY_RECIPE_MAX" in doc


def test_wave_f_doc_cross_links_james_t180u():
    doc = (ROOT / "docs/WAVE_F_HIT.md").read_text(encoding="utf-8")
    assert "t180u" in doc
