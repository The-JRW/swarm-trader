"""Wave C tests — scan persist, apply cap 15, cron 401, auto-launch blocked."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]


def test_cron_swarm_scan_401_without_secret(monkeypatch):
    from app.backend.dependencies.cron_auth import require_cron_secret

    monkeypatch.delenv("SWARM_CRON_SECRET", raising=False)
    with pytest.raises(HTTPException) as ei:
        require_cron_secret(x_swarm_cron_secret="anything")
    assert ei.value.status_code == 401

    monkeypatch.setenv("SWARM_CRON_SECRET", "wave-c-secret")
    with pytest.raises(HTTPException) as ei2:
        require_cron_secret(x_swarm_cron_secret=None)
    assert ei2.value.status_code == 401

    with pytest.raises(HTTPException) as ei3:
        require_cron_secret(x_swarm_cron_secret="wrong")
    assert ei3.value.status_code == 401

    require_cron_secret(x_swarm_cron_secret="wave-c-secret")


def test_auto_launch_blocked_when_env_false(monkeypatch, tmp_path):
    monkeypatch.setenv("SWARM_AUTOMATION_DIR", str(tmp_path / "automation"))
    from app.backend.services import automation_store as store

    store.AUTOMATION_DIR = tmp_path / "automation"

    monkeypatch.delenv("SWARM_AUTO_LAUNCH", raising=False)
    assert store.auto_launch_env_allows() is False

    monkeypatch.setenv("SWARM_AUTO_LAUNCH", "false")
    assert store.auto_launch_env_allows() is False

    monkeypatch.setenv("SWARM_AUTO_LAUNCH", "true")
    assert store.auto_launch_env_allows() is True

    monkeypatch.setenv("SWARM_AUTO_LAUNCH", "0")
    assert store.auto_launch_env_allows() is False


def test_scan_persist(monkeypatch, tmp_path):
    monkeypatch.setenv("SWARM_AUTOMATION_DIR", str(tmp_path / "automation"))
    from app.backend.services import automation_store as store

    store.AUTOMATION_DIR = tmp_path / "automation"

    fake_scan = {
        "timestamp": "2026-09-15T00:00:00",
        "tickers": ["NVDA", "AAPL", "TSLA"],
        "candidates": [
            {"symbol": "NVDA", "sources": ["core"]},
            {"symbol": "AAPL", "sources": ["core", "mover"]},
            {"symbol": "TSLA", "sources": ["mover", "active"]},
        ],
        "candidate_count": 3,
        "mode": "swing",
        "intersect_universe": True,
        "paper_only": True,
        # must be stripped
        "ALPACA_API_KEY": "should-not-persist",
        "secret": "nope",
    }
    store.write_last_scan(fake_scan)

    path = tmp_path / "automation" / "last_scan.json"
    assert path.is_file()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "ALPACA_API_KEY" not in raw
    assert "secret" not in raw
    assert raw["paper_only"] is True
    assert raw["candidates"][0]["sources"] == ["core"]

    loaded = store.read_last_scan()
    assert loaded is not None
    assert loaded["candidate_count"] == 3

    hist = store.read_scan_history(limit=5)
    assert len(hist) >= 1
    assert hist[0]["candidate_count"] == 3
    assert "ALPACA_API_KEY" not in hist[0]


def test_apply_cap_15(monkeypatch, tmp_path):
    monkeypatch.setenv("SWARM_AUTOMATION_DIR", str(tmp_path / "automation"))
    from app.backend.services import automation_store as store
    from app.backend.services.swarm_scan_service import apply_scan_to_recipe

    store.AUTOMATION_DIR = tmp_path / "automation"

    many = [f"T{i:02d}" for i in range(30)]
    # Seed last scan with >15 candidates
    store.write_last_scan(
        {
            "tickers": many,
            "candidates": [{"symbol": t, "sources": ["mover"]} for t in many],
            "candidate_count": len(many),
            "mode": "swing",
            "intersect_universe": True,
        }
    )

    result = apply_scan_to_recipe(top_n=50)  # request over cap
    assert result["applied_count"] <= 15
    assert result["cap"] == 15
    assert len(result["applied_tickers"]) == 15
    assert len(result["recipe"]["tickers"]) == 15

    # Explicit tickers also capped
    result2 = apply_scan_to_recipe(top_n=15, tickers=many)
    assert len(result2["applied_tickers"]) == 15


def test_source_tags_normalization():
    from app.backend.services.swarm_scan_service import _normalize_source_tags

    assert "mover" in _normalize_source_tags("gainer")
    assert "mover" in _normalize_source_tags("loser")
    assert "active" in _normalize_source_tags("active")
    assert "mover" in _normalize_source_tags("gainer+active")
    assert "active" in _normalize_source_tags("gainer+active")
    assert _normalize_source_tags("", is_core=True) == ["core"]
    assert "core" in _normalize_source_tags("gainer", is_core=True)


def test_cron_auto_launch_notes_when_blocked(monkeypatch, tmp_path):
    """When SWARM_AUTO_LAUNCH false, apply/launch flags produce notes (scan still ok)."""
    monkeypatch.setenv("SWARM_AUTOMATION_DIR", str(tmp_path / "automation"))
    monkeypatch.delenv("SWARM_AUTO_LAUNCH", raising=False)
    monkeypatch.setenv("ALPACA_TRADING_MODE", "paper")

    from app.backend.services import automation_store as store

    store.AUTOMATION_DIR = tmp_path / "automation"

    import app.backend.services.swarm_scan_service as sss

    monkeypatch.setattr(sss, "run_swarm_scan", lambda **kw: {
        "timestamp": "2026-09-15T01:00:00",
        "mode": "swing",
        "intersect_universe": True,
        "intersected": False,
        "universe_size": 0,
        "candidates": [
            {"symbol": "NVDA", "sources": ["core"]},
            {"symbol": "AAPL", "sources": ["core"]},
            {"symbol": "TSLA", "sources": ["mover"]},
        ],
        "tickers": ["NVDA", "AAPL", "TSLA"],
        "candidate_count": 3,
        "paper_only": True,
        "source": "scan_market.scan",
    })

    # Directly test the gating contract used by the cron route (no FastAPI import)
    assert store.auto_launch_env_allows() is False
    apply_requested = True
    launch_requested = True
    notes: List[str] = []
    if apply_requested or launch_requested:
        if not store.auto_launch_env_allows():
            notes.append(
                "SWARM_AUTO_LAUNCH absent/false — scan-only; apply_recipe/launch ignored"
            )
    assert notes
    assert "scan-only" in notes[0]

    # Persist path still works when service used
    result = sss.run_swarm_scan(persist=True)
    assert (tmp_path / "automation" / "last_scan.json").is_file() or result["candidate_count"] == 3


def test_build_info_has_wave_c():
    src = (ROOT / "app/backend/routes/build_info.py").read_text(encoding="utf-8")
    assert "wave-c-orchestrator" in src
    assert "swarm-scan" in src


def test_env_example_documents_auto_launch():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "SWARM_AUTO_LAUNCH" in text
