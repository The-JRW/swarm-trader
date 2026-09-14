"""Unit tests for A1/A2 cron auth + dry-run defaults (no network)."""

import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_resolve_monitor_dry_run_defaults(monkeypatch):
    # Avoid importing alpaca/paper_run via package path side effects:
    # load only the pure helpers by exec'ing selected source is heavy;
    # import service module (pulls paper_run_service which is light enough).
    from app.backend.services.portfolio_monitor_service import resolve_monitor_dry_run

    monkeypatch.delenv("SWARM_MONITOR_DRY_RUN", raising=False)
    assert resolve_monitor_dry_run(None) is True
    assert resolve_monitor_dry_run(True) is True
    assert resolve_monitor_dry_run(False) is True  # env still defaults to dry-run

    monkeypatch.setenv("SWARM_MONITOR_DRY_RUN", "false")
    assert resolve_monitor_dry_run(None) is True
    assert resolve_monitor_dry_run(True) is True
    assert resolve_monitor_dry_run(False) is False  # hot only when both allow


def test_cron_secret_fail_closed(monkeypatch):
    from app.backend.dependencies.cron_auth import require_cron_secret

    monkeypatch.delenv("SWARM_CRON_SECRET", raising=False)
    with pytest.raises(HTTPException) as ei:
        require_cron_secret(x_swarm_cron_secret="anything")
    assert ei.value.status_code == 401
    assert "FAIL_CLOSED" in ei.value.detail

    monkeypatch.setenv("SWARM_CRON_SECRET", "s3cret-value")
    with pytest.raises(HTTPException) as ei2:
        require_cron_secret(x_swarm_cron_secret=None)
    assert ei2.value.status_code == 401

    with pytest.raises(HTTPException) as ei3:
        require_cron_secret(x_swarm_cron_secret="wrong")
    assert ei3.value.status_code == 401

    require_cron_secret(x_swarm_cron_secret="s3cret-value")


def test_build_info_git_sha(monkeypatch):
    mod = _load("build_info_standalone", "app/backend/routes/build_info.py")

    monkeypatch.setenv("GIT_SHA", "")
    assert mod._resolve_git_sha() == "unknown"
    monkeypatch.setenv("GIT_SHA", "unknown")
    assert mod._resolve_git_sha() == "unknown"
    monkeypatch.setenv("GIT_SHA", "abc123def")
    assert mod._resolve_git_sha() == "abc123def"


def test_default_liquid_tickers_constant():
    # Constant documented in cron route — keep in sync without importing FastAPI app graph
    src = (ROOT / "app/backend/routes/cron.py").read_text(encoding="utf-8")
    assert 'DEFAULT_LIQUID_TICKERS = ["NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "SPY"]' in src
    assert "single-worker in-memory" in src
    assert "SWARM_CRON_SECRET" not in src or "require_cron_secret" in src
