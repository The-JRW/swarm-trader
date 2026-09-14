"""Paper analysis runs for the Strategies UI.

Wraps src.main.run_hedge_fund. FAIL_CLOSED when Alpaca keys are missing.
Never logs secret values.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Core analyst set matching run_hedge_fund.py defaults
CORE_STRATEGY_IDS = [
    "warren_buffett",
    "michael_burry",
    "cathie_wood",
    "apex",
    "autoresearch",
    "fundamentals_analyst",
    "technical_analyst",
]

# In-memory run store (single-process; fine for paper UI)
_RUNS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


def has_alpaca_keys() -> bool:
    key = (os.environ.get("ALPACA_API_KEY") or "").strip()
    secret = (os.environ.get("ALPACA_API_SECRET") or "").strip()
    return bool(key and secret)


def alpaca_trading_mode() -> str:
    return (os.environ.get("ALPACA_TRADING_MODE") or "paper").strip().lower() or "paper"


def assert_paper_only() -> None:
    """Refuse live trading from the Strategies UI path."""
    mode = alpaca_trading_mode()
    base = (os.environ.get("ALPACA_BASE_URL") or "").strip().lower()
    live_base = "api.alpaca.markets" in base and "paper-api" not in base
    if mode == "live" or live_base:
        raise PermissionError(
            "Strategies UI paper runs are paper-only. "
            "ALPACA_TRADING_MODE must be 'paper' (refuse live from this path)."
        )


def get_strategies_catalog() -> List[Dict[str, Any]]:
    from src.utils.analysts import ANALYST_CONFIG

    strategies: List[Dict[str, Any]] = []
    for key, config in sorted(ANALYST_CONFIG.items(), key=lambda x: x[1]["order"]):
        strategies.append(
            {
                "id": key,
                "name": config["display_name"],
                "description": config.get("description") or config.get("investing_style", ""),
                "category": "analyst",
                "enabled_default": key in CORE_STRATEGY_IDS,
            }
        )

    strategies.append(
        {
            "id": "risk_manager",
            "name": "Risk Manager",
            "description": "Enforces position sizing and risk limits before portfolio decisions.",
            "category": "risk",
            "enabled_default": True,
        }
    )
    strategies.append(
        {
            "id": "portfolio_manager",
            "name": "Portfolio Manager",
            "description": "Aggregates analyst signals into final trade decisions.",
            "category": "pm",
            "enabled_default": True,
        }
    )
    return strategies


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def create_run_record(
    tickers: List[str],
    strategy_ids: List[str],
    mode: str,
    execute_trades: bool = False,
    instrument: str = "stocks",
) -> str:
    run_id = str(uuid.uuid4())
    inst = (instrument or "stocks").strip().lower()
    if inst not in ("stocks", "options"):
        inst = "stocks"
    record = {
        "run_id": run_id,
        "status": "queued",
        "mode": mode,
        "instrument": inst,
        "tickers": tickers,
        "strategy_ids": strategy_ids,
        "execute_trades": bool(execute_trades),
        "created_at": _now_iso(),
        "started_at": None,
        "completed_at": None,
        "error": None,
        "summary": None,
        "decisions": None,
    }
    with _LOCK:
        _RUNS[run_id] = record
    return run_id


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        rec = _RUNS.get(run_id)
        return dict(rec) if rec else None


def _update_run(run_id: str, **fields: Any) -> None:
    with _LOCK:
        if run_id not in _RUNS:
            return
        _RUNS[run_id].update(fields)


def _select_analysts(strategy_ids: List[str]) -> List[str]:
    from src.utils.analysts import ANALYST_CONFIG

    # risk/pm are always wired by create_workflow — strip them from analyst list
    analysts = [s for s in strategy_ids if s in ANALYST_CONFIG]
    if not analysts:
        analysts = list(CORE_STRATEGY_IDS)
    return analysts


def _build_empty_portfolio(tickers: List[str], cash: float = 100_000.0) -> dict:
    return {
        "cash": cash,
        "margin_requirement": 0.0,
        "margin_used": 0.0,
        "positions": {
            t: {
                "long": 0,
                "short": 0,
                "long_cost_basis": 0.0,
                "short_cost_basis": 0.0,
                "short_margin_used": 0.0,
            }
            for t in tickers
        },
        "realized_gains": {t: {"long": 0.0, "short": 0.0} for t in tickers},
    }


def _try_live_portfolio(tickers: List[str], mode: str) -> dict:
    """Prefer Alpaca paper portfolio when keys work; else empty cash book."""
    try:
        from src.alpaca_integration import (
            convert_to_portfolio,
            get_alpaca_account,
            get_alpaca_positions,
        )

        account = get_alpaca_account(mode if mode in ("swing", "day") else None)
        positions = get_alpaca_positions(mode if mode in ("swing", "day") else None)
        return convert_to_portfolio(positions, account, tickers)
    except Exception as e:
        logger.warning("Paper run: could not load Alpaca portfolio (%s); using empty book", type(e).__name__)
        return _build_empty_portfolio(tickers)



def _sanitize_trade_result(row: Dict[str, Any]) -> Dict[str, Any]:
    """Keep order metadata only — never include secrets or raw headers."""
    if not isinstance(row, dict):
        return {"success": False, "reason": "invalid_result"}
    keep = (
        "ticker",
        "action",
        "qty",
        "quantity",
        "confidence",
        "success",
        "skipped",
        "dry_run",
        "order_id",
        "status",
        "reason",
        "rule",
        "order_type",
        "order_class",
        "stop_price",
        "take_profit_price",
        "limit_price",
        "trail_percent",
        "side",
    )
    out = {k: row[k] for k in keep if k in row}
    # Truncate free-text fields
    if "reason" in out and isinstance(out["reason"], str):
        out["reason"] = out["reason"][:300]
    if "reasoning" in row and isinstance(row.get("reasoning"), str):
        out["reasoning"] = row["reasoning"][:200]
    return out


def _execute_paper_decisions(decisions: dict, mode: str) -> List[Dict[str, Any]]:
    """Place paper orders via alpaca_integration.execute_decisions. Never logs secrets."""
    from src.alpaca_integration import (
        execute_decisions,
        get_alpaca_account,
        get_alpaca_positions,
    )

    account_mode = mode if mode in ("swing", "day") else "swing"
    try:
        account = get_alpaca_account(account_mode)
        positions = get_alpaca_positions(account_mode)
    except Exception as e:
        logger.warning(
            "Paper execute: portfolio fetch failed (%s); retrying swing",
            type(e).__name__,
        )
        from src import accounts as accounts_mod

        accounts_mod._load_accounts()
        account = get_alpaca_account("swing")
        positions = get_alpaca_positions("swing")
        account_mode = "swing"

    raw = execute_decisions(
        decisions,
        positions_raw=positions or [],
        account=account or {},
        dry_run=False,
        mode=account_mode,
    )
    return [_sanitize_trade_result(r) for r in (raw or [])]


def execute_paper_run(run_id: str) -> Dict[str, Any]:
    """Execute a bounded paper analysis. Mutates run store. Never logs secrets."""
    rec = get_run(run_id)
    if not rec:
        raise KeyError(f"Unknown run_id: {run_id}")

    if not has_alpaca_keys():
        msg = (
            "FAIL_CLOSED: ALPACA_API_KEY and ALPACA_API_SECRET are required "
            "for paper analysis runs. Set them in server env (Elestio), not in the UI."
        )
        _update_run(
            run_id,
            status="fail_closed",
            error=msg,
            completed_at=_now_iso(),
        )
        logger.error("Paper run %s FAIL_CLOSED: missing Alpaca keys", run_id)
        return get_run(run_id)  # type: ignore

    try:
        assert_paper_only()
    except PermissionError as e:
        _update_run(run_id, status="fail_closed", error=str(e), completed_at=_now_iso())
        logger.error("Paper run %s FAIL_CLOSED: live mode blocked", run_id)
        return get_run(run_id)  # type: ignore

    _update_run(run_id, status="running", started_at=_now_iso())

    try:
        from src.config import get_mode_config, resolve_mode
        from src.main import run_hedge_fund

        mode = rec.get("mode") or resolve_mode()
        if mode == "auto":
            # Keep analysis path deterministic for UI; agent auto-pick is CLI/cron
            mode = "swing"
        get_mode_config(mode)  # validate

        tickers = rec["tickers"]
        analysts = _select_analysts(rec.get("strategy_ids") or [])
        portfolio = _try_live_portfolio(tickers, mode)

        end_date = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = datetime.utcnow().replace(day=1).strftime("%Y-%m-%d")

        model_name = (
            os.environ.get("DEFAULT_LLM_MODEL")
            or os.environ.get("LLM_MODEL")
            or "openai/gpt-4o-mini"
        )
        model_provider = (
            os.environ.get("DEFAULT_LLM_PROVIDER")
            or os.environ.get("LLM_PROVIDER")
            or "OpenRouter"
        )

        logger.info(
            "Paper run %s starting: mode=%s tickers=%s analysts=%d provider=%s",
            run_id,
            mode,
            tickers,
            len(analysts),
            model_provider,
        )

        result = run_hedge_fund(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            portfolio=portfolio,
            show_reasoning=False,
            selected_analysts=analysts,
            model_name=model_name,
            model_provider=model_provider,
        )

        decisions = result.get("decisions") or {}
        analyst_signals = result.get("analyst_signals") or {}

        # Compact summary — no secrets
        action_counts = {"buy": 0, "sell": 0, "short": 0, "cover": 0, "hold": 0}
        decision_rows = []
        for ticker, decision in decisions.items():
            if not isinstance(decision, dict):
                continue
            action = str(decision.get("action", "hold")).lower()
            if action in action_counts:
                action_counts[action] += 1
            else:
                action_counts[action] = action_counts.get(action, 0) + 1
            agent_inst = (
                decision.get("instrument")
                or decision.get("asset_class")
                or decision.get("assetClass")
            )
            if isinstance(agent_inst, str):
                agent_inst = agent_inst.strip().lower()
                if agent_inst in ("stock", "equity", "equities"):
                    agent_inst = "stocks"
                if agent_inst in ("option",):
                    agent_inst = "options"
                if agent_inst not in ("stocks", "options"):
                    agent_inst = None
            else:
                agent_inst = None
            decision_rows.append(
                {
                    "ticker": ticker,
                    "action": action,
                    "quantity": decision.get("quantity", 0),
                    "confidence": decision.get("confidence"),
                    "reasoning": (decision.get("reasoning") or "")[:800],
                    "agent_instrument": agent_inst,
                    "instrument": rec.get("instrument") or "stocks",
                }
            )

        want_execute = bool(rec.get("execute_trades"))
        instrument = (rec.get("instrument") or "stocks").strip().lower()
        if instrument not in ("stocks", "options"):
            instrument = "stocks"
        trade_results: List[Dict[str, Any]] = []
        executed = False
        execute_blocked_reason = None

        if want_execute:
            assert_paper_only()
            if instrument == "options":
                execute_blocked_reason = (
                    "Options paper execute not wired yet — research-only. "
                    "Switch instrument to Stocks to place paper equity orders."
                )
                logger.warning(
                    "Paper run %s: execute_trades blocked for options (research-only)",
                    run_id,
                )
            else:
                trade_results = _execute_paper_decisions(decisions, mode)
                executed = True
                logger.info(
                    "Paper run %s executed %d trade result(s)",
                    run_id,
                    len(trade_results),
                )

        summary = {
            "mode": mode,
            "instrument": instrument,
            "ticker_count": len(tickers),
            "analyst_count": len(analysts),
            "action_counts": action_counts,
            "signals_agents": list(analyst_signals.keys())[:30],
            "decisions": decision_rows,
            "paper": True,
            "executed_trades": executed,
            "execute_blocked_reason": execute_blocked_reason,
            "trade_results": trade_results,
        }

        _update_run(
            run_id,
            status="complete",
            completed_at=_now_iso(),
            summary=summary,
            decisions=decisions,
            mode=mode,
        )
        logger.info("Paper run %s complete", run_id)
    except Exception as e:
        # Never include env/secrets in error message
        err = f"{type(e).__name__}: {e}"
        logger.exception("Paper run %s failed: %s", run_id, type(e).__name__)
        _update_run(run_id, status="error", error=err, completed_at=_now_iso())

    return get_run(run_id)  # type: ignore


def start_paper_run_async(run_id: str) -> None:
    thread = threading.Thread(target=execute_paper_run, args=(run_id,), daemon=True)
    thread.start()
