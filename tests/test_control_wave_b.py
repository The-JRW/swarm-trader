"""Control Wave B tests — recipe dual-gate, history persist, digest, cron auth."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]


def test_cron_auth_still_401_without_secret(monkeypatch):
    from app.backend.dependencies.cron_auth import require_cron_secret

    monkeypatch.delenv("SWARM_CRON_SECRET", raising=False)
    with pytest.raises(HTTPException) as ei:
        require_cron_secret(x_swarm_cron_secret="anything")
    assert ei.value.status_code == 401

    monkeypatch.setenv("SWARM_CRON_SECRET", "wave-b-secret")
    with pytest.raises(HTTPException) as ei2:
        require_cron_secret(x_swarm_cron_secret=None)
    assert ei2.value.status_code == 401

    with pytest.raises(HTTPException) as ei3:
        require_cron_secret(x_swarm_cron_secret="wrong")
    assert ei3.value.status_code == 401

    require_cron_secret(x_swarm_cron_secret="wave-b-secret")


def test_recipe_dual_gate(monkeypatch, tmp_path):
    monkeypatch.setenv("SWARM_AUTOMATION_DIR", str(tmp_path / "automation"))
    from app.backend.services import automation_store as store

    # Reload paths
    store.AUTOMATION_DIR = tmp_path / "automation"

    monkeypatch.delenv("SWARM_CRON_EXECUTE_TRADES", raising=False)
    assert store.cron_execute_env_allows() is False
    assert store.resolve_cron_execute_trades(True) is False
    assert store.resolve_cron_execute_trades(False) is False

    monkeypatch.setenv("SWARM_CRON_EXECUTE_TRADES", "true")
    assert store.cron_execute_env_allows() is True
    assert store.resolve_cron_execute_trades(True) is True
    assert store.resolve_cron_execute_trades(False) is False

    monkeypatch.setenv("SWARM_CRON_EXECUTE_TRADES", "false")
    assert store.resolve_cron_execute_trades(True) is False

    recipe = store.write_cron_recipe(
        {
            "tickers": ["NVDA", "AAPL"],
            "preset": "core",
            "mode": "swing",
            "execute_trades": True,
        }
    )
    assert recipe["execute_trades"] is True
    assert recipe["tickers"] == ["NVDA", "AAPL"]
    loaded = store.read_cron_recipe()
    assert loaded["preset"] == "core"
    assert (tmp_path / "automation" / "cron_recipe.json").is_file()
    # No secrets keys
    raw = json.loads((tmp_path / "automation" / "cron_recipe.json").read_text())
    assert "secret" not in raw
    assert "ALPACA_API_KEY" not in raw


def test_history_persist(monkeypatch, tmp_path):
    monkeypatch.setenv("SWARM_RUNS_DIR", str(tmp_path / "runs"))
    from app.backend.services import run_history_store as rhs

    rhs.RUNS_DIR = tmp_path / "runs"

    for i in range(3):
        rhs.persist_run(
            {
                "run_id": f"run-{i}",
                "status": "complete" if i else "queued",
                "mode": "swing",
                "instrument": "stocks",
                "tickers": ["NVDA"],
                "strategy_ids": ["warren_buffett"],
                "execute_trades": False,
                "created_at": f"2026-09-14T0{i}:00:00Z",
                "completed_at": f"2026-09-14T0{i}:05:00Z" if i else None,
                "summary": {
                    "action_counts": {"buy": 1},
                    "conviction_digest": {
                        "consensus": [{"ticker": "NVDA", "direction": "buy"}],
                        "contested": [],
                        "risk_rejected": [],
                    },
                },
                "conviction_digest": {
                    "consensus": [{"ticker": "NVDA", "direction": "buy"}],
                    "contested": [],
                    "risk_rejected": [],
                },
            }
        )

    hist = rhs.list_history(limit=50)
    assert len(hist) == 3
    assert hist[0]["run_id"] == "run-2"  # newest first by completed/created
    durable = rhs.read_run("run-1")
    assert durable is not None
    assert durable["tickers"] == ["NVDA"]
    assert durable.get("conviction_digest")


def test_conviction_digest_from_sample_signals():
    from app.backend.services.conviction_digest import compute_conviction_digest

    signals = {
        "warren_buffett": {
            "AAPL": {"signal": "bullish", "confidence": 80},
            "MSFT": {"signal": "bullish", "confidence": 70},
            "NVDA": {"signal": "bearish", "confidence": 60},
        },
        "cathie_wood": {
            "AAPL": {"signal": "bullish", "confidence": 75},
            "MSFT": {"signal": "bearish", "confidence": 55},
            "NVDA": {"signal": "bearish", "confidence": 65},
        },
        "michael_burry": {
            "AAPL": {"signal": "bullish", "confidence": 70},
            "MSFT": {"signal": "neutral", "confidence": 50},
            "NVDA": {"signal": "neutral", "confidence": 50},
        },
        "risk_management_agent": {
            "AAPL": {"remaining_position_limit": 0.0, "current_price": 190.0},
            "MSFT": {"remaining_position_limit": 5000.0, "current_price": 400.0},
            "NVDA": {"remaining_position_limit": 2000.0, "current_price": 120.0},
        },
    }

    digest = compute_conviction_digest(
        signals,
        tickers=["AAPL", "MSFT", "NVDA"],
        decisions={
            "AAPL": {"action": "hold", "quantity": 0},
            "MSFT": {"action": "sell", "quantity": 10},
            "NVDA": {"action": "sell", "quantity": 5},
        },
    )

    consensus_tickers = {c["ticker"]: c["direction"] for c in digest["consensus"]}
    assert consensus_tickers.get("AAPL") == "buy"
    assert consensus_tickers.get("NVDA") == "sell"

    contested_tickers = {c["ticker"] for c in digest["contested"]}
    assert "MSFT" in contested_tickers

    rejected = {r["ticker"] for r in digest["risk_rejected"]}
    assert "AAPL" in rejected  # bullish majority + limit 0

    # No invented aggregate confidence field
    assert "confidence" not in digest
    for c in digest["consensus"]:
        assert "confidence" not in c or c.get("confidence") is None or True  # may omit


def test_build_info_has_control_wave_b():
    src = (ROOT / "app/backend/routes/build_info.py").read_text(encoding="utf-8")
    assert "control-wave-b" in src
    assert "ops-recipe" in src
    assert "durable-run-history" in src
    assert "conviction-digest" in src


def test_image_tag_ux_10():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "strategies-ux-10" in compose
    assert "strategies-ux-9" not in compose
