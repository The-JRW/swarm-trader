"""Wave D tests — risk policy glance, sector-aware apply, recipe hints, paper-only outs."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _isolate_automation(monkeypatch, tmp_path):
    monkeypatch.setenv("SWARM_AUTOMATION_DIR", str(tmp_path / "automation"))
    from app.backend.services import automation_store as store

    store.AUTOMATION_DIR = tmp_path / "automation"
    return store


# ── D2 — risk policy glance ────────────────────────────────────────────────


def test_risk_policy_mirrors_config_swing():
    from src.config import get_mode_config
    from app.backend.services.risk_policy_service import get_risk_policy

    policy = get_risk_policy("swing")
    risk = get_mode_config("swing")["risk"]

    assert policy["mode"] == "swing"
    assert policy["read_only"] is True
    assert policy["paper_only"] is True
    assert policy["caps"]["max_position_pct"] == round(risk["max_position_pct"] * 100, 2)
    assert policy["caps"]["max_sector_pct"] == round(risk["max_sector_pct"] * 100, 2)
    assert policy["caps"]["max_open_positions"] == risk["max_open_positions"]
    assert policy["flatten"]["flatten_eod"] is False

    sectors = {s["key"]: s for s in policy["sectors"]}
    assert sectors["core_tech"]["max_sector_pct"] == 30.0
    assert sectors["tactical"]["max_sector_pct"] == 15.0
    assert "no LLM" in policy["note"].lower() or "llm" in policy["note"].lower()


def test_risk_policy_day_flattens_and_never_widens():
    from src.config import get_mode_config
    from app.backend.services.risk_policy_service import get_risk_policy

    policy = get_risk_policy("day")
    risk = get_mode_config("day")["risk"]

    assert policy["flatten"]["flatten_eod"] is True
    assert policy["flatten"]["flatten_by"] == risk["flatten_by"]

    breakers = {b["rule"]: b for b in policy["circuit_breakers"]}
    assert breakers["daily_loss_limit"]["limit_pct"] == round(risk["daily_loss_limit"] * 100, 2)
    assert breakers["weekly_loss_limit"]["limit_pct"] == round(risk["weekly_loss_limit"] * 100, 2)

    # Display-only view must not report a cap looser than config
    assert policy["caps"]["max_position_pct"] <= round(risk["max_position_pct"] * 100, 2)


def test_risk_policy_auto_falls_back_to_a_real_mode():
    from app.backend.services.risk_policy_service import get_risk_policy

    policy = get_risk_policy("auto")
    assert policy["mode"] in ("swing", "day")
    assert policy["caps"]["max_sector_pct"] is not None


# ── D3 — sector-aware scan → recipe apply ─────────────────────────────────


def test_sector_aware_apply_reports_skip_reasons(monkeypatch, tmp_path):
    store = _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.swarm_scan_service import apply_scan_to_recipe

    core_tech = ["NVDA", "AVGO", "TSM", "MSFT", "AAPL", "GOOGL", "META", "AMZN"]
    store.write_last_scan(
        {
            "tickers": core_tech,
            "candidates": [{"symbol": t, "sources": ["mover"]} for t in core_tech],
            "candidate_count": len(core_tech),
            "mode": "swing",
        }
    )

    result = apply_scan_to_recipe(top_n=15, mode="swing")

    # core_tech caps at 30% of 15 slots → 4 picks, the rest are skipped with a reason
    assert result["sector_aware"] is True
    assert result["applied_count"] == 4
    assert result["sector_caps_trimmed"] is True
    assert result["skipped_count"] == len(core_tech) - 4
    assert all(s["reason"] for s in result["skipped"])
    assert {s["kind"] for s in result["skipped"]} == {"sector_cap"}
    assert all("sector cap" in s["reason"].lower() for s in result["skipped"])
    assert result["notes"] and "sector cap" in result["notes"][0].lower()

    core_tech_row = next(s for s in result["sectors"] if s["sector"] == "core_tech")
    assert core_tech_row["picked"] == 4
    assert core_tech_row["slot_cap"] == 4
    assert core_tech_row["max_sector_pct"] == 30.0


def test_sector_aware_apply_diversifies_across_sectors(monkeypatch, tmp_path):
    store = _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.swarm_scan_service import apply_scan_to_recipe

    pool = ["NVDA", "AVGO", "TSM", "MSFT", "AAPL", "PLTR", "JPM", "SPY"]
    store.write_last_scan(
        {
            "tickers": pool,
            "candidates": [{"symbol": t, "sources": ["mover"]} for t in pool],
            "candidate_count": len(pool),
            "mode": "swing",
        }
    )

    result = apply_scan_to_recipe(top_n=5, mode="swing")
    applied = result["applied_tickers"]

    # Diversification first: one name from each represented sector before filling
    assert "NVDA" in applied
    assert "PLTR" in applied
    assert "JPM" in applied
    assert "SPY" in applied
    sectors_picked = {s["sector"] for s in result["sectors"] if s["picked"] > 0}
    assert sectors_picked == {"core_tech", "growth", "value_dividend", "hedge"}


def test_sector_aware_apply_prefers_underweight_sectors(monkeypatch, tmp_path):
    store = _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.swarm_scan_service import apply_scan_to_recipe

    # Live recipe is all core_tech → core_tech is overweight for the next apply
    store.write_cron_recipe(
        {"tickers": ["NVDA", "AVGO", "TSM", "MSFT"], "preset": "core", "mode": "swing"}
    )
    pool = ["AAPL", "PLTR"]
    store.write_last_scan(
        {
            "tickers": pool,
            "candidates": [{"symbol": t, "sources": ["mover"]} for t in pool],
            "candidate_count": len(pool),
            "mode": "swing",
        }
    )

    result = apply_scan_to_recipe(top_n=1, mode="swing")
    assert result["applied_tickers"] == ["PLTR"]


def test_apply_never_leaves_recipe_empty(monkeypatch, tmp_path):
    store = _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.swarm_scan_service import apply_scan_to_recipe

    off_universe = ["ZZZA", "ZZZB", "ZZZC"]
    store.write_last_scan(
        {
            "tickers": off_universe,
            "candidates": [{"symbol": t, "sources": ["mover"]} for t in off_universe],
            "candidate_count": len(off_universe),
            "mode": "swing",
        }
    )

    result = apply_scan_to_recipe(top_n=15, mode="swing")
    assert result["applied_count"] == 3
    assert result["recipe"]["tickers"] == off_universe
    assert store.read_cron_recipe()["tickers"]

    # Sector-aware off also keeps a non-empty recipe
    plain = apply_scan_to_recipe(top_n=15, sector_aware=False, mode="swing")
    assert plain["sector_aware"] is False
    assert plain["applied_count"] == 3
    assert plain["recipe"]["tickers"]


def test_apply_still_caps_at_15_with_sector_awareness(monkeypatch, tmp_path):
    store = _isolate_automation(monkeypatch, tmp_path)
    from app.backend.services.swarm_scan_service import apply_scan_to_recipe

    many = [f"T{i:02d}" for i in range(30)]
    store.write_last_scan(
        {
            "tickers": many,
            "candidates": [{"symbol": t, "sources": ["mover"]} for t in many],
            "candidate_count": len(many),
            "mode": "swing",
        }
    )

    result = apply_scan_to_recipe(top_n=50, mode="swing")
    assert result["cap"] == 15
    assert result["applied_count"] == 15
    assert len(result["recipe"]["tickers"]) == 15
    assert {s["kind"] for s in result["skipped"]} == {"slot_cap"}


def test_sector_slot_cap_never_zero_and_never_widens():
    from app.backend.services.swarm_scan_service import _sector_slot_cap

    assert _sector_slot_cap(0.30, 15) == 4
    assert _sector_slot_cap(0.15, 15) == 2
    assert _sector_slot_cap(0.15, 3) == 1  # floor(0.45) → clamped to 1, never 0
    assert _sector_slot_cap(2.0, 10) == 10  # never exceeds available slots


# ── D5 — conviction → next recipe hints ───────────────────────────────────


def test_recipe_hints_are_display_only_and_ranked():
    from app.backend.services.conviction_digest import build_recipe_hints

    digest = {
        "consensus": [{"ticker": "NVDA", "direction": "buy", "agree": 4, "total": 5}],
        "contested": [{"ticker": "AMD", "bullish": 2, "bearish": 2, "neutral": 1}],
        "risk_rejected": [{"ticker": "SMCI", "reason": "remaining_position_limit=0"}],
        "source": "analyst_signals",
    }

    hints = build_recipe_hints(digest, current_tickers=["NVDA", "SPY"])

    assert hints["display_only"] is True
    assert hints["auto_write"] is False
    assert hints["requires_explicit_apply"] is True
    # contested first, risk-rejected never suggested
    assert hints["suggested_tickers"] == ["AMD", "NVDA"]
    assert "SMCI" not in hints["suggested_tickers"]
    assert hints["excluded"][0]["ticker"] == "SMCI"
    assert hints["hints"][0]["kind"] == "contested"
    assert hints["hints"][1]["in_current_recipe"] is True


def test_recipe_hints_empty_digest_is_safe():
    from app.backend.services.conviction_digest import build_recipe_hints

    for digest in (None, {}, {"consensus": [], "contested": []}):
        hints = build_recipe_hints(digest)
        assert hints["suggested_tickers"] == []
        assert hints["auto_write"] is False


def test_recipe_hints_capped_at_15():
    from app.backend.services.conviction_digest import build_recipe_hints

    digest = {
        "contested": [{"ticker": f"C{i:02d}", "bullish": 1, "bearish": 1} for i in range(20)],
        "consensus": [{"ticker": "NVDA", "direction": "buy", "agree": 3, "total": 3}],
    }
    hints = build_recipe_hints(digest, limit=99)
    assert len(hints["suggested_tickers"]) == 15


# ── Ship checks / hard outs ───────────────────────────────────────────────


def test_build_info_has_wave_d_flags():
    src = (ROOT / "app/backend/routes/build_info.py").read_text(encoding="utf-8")
    for flag in (
        "wave-d-strategies-ia",
        "run-book-tabs",
        "risk-policy-glance",
        "sector-aware-apply",
        "conviction-recipe-hints",
    ):
        assert flag in src


def test_compose_image_tag_is_strategies_ux_12():
    """Wave G G2 Ops-visible amendment bumped the shipping tag to
    strategies-ux-16 — see test_wave_g_latency_max.py."""
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "strategies-ux-16" in compose
    assert "strategies-ux-11" not in compose


def test_paper_only_hard_outs_unchanged():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "SWARM_AUTO_LAUNCH: ${SWARM_AUTO_LAUNCH:-false}" in compose
    assert "SWARM_MONITOR_DRY_RUN: ${SWARM_MONITOR_DRY_RUN:-true}" in compose
    assert "SWARM_CRON_EXECUTE_TRADES: ${SWARM_CRON_EXECUTE_TRADES:-false}" in compose
    assert "ALPACA_TRADING_MODE: ${ALPACA_TRADING_MODE:-paper}" in compose


def test_wave_d_docs_document_scan_only_cadence():
    doc = (ROOT / "docs/WAVE_D.md").read_text(encoding="utf-8")
    assert "SWARM_AUTO_LAUNCH" in doc
    assert "scan-only" in doc.lower()
    assert "midday" in doc.lower()
    assert "scheduler" in doc.lower()
    # D6 — Neon upserts stay on the Coder/Keeper path
    assert "neon" in doc.lower()
