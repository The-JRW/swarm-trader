"""C1 — Swarm market scan service (paper-only orchestration).

Wraps ``scan_market.scan()``, optionally intersects with mode universe,
persists last scan + history under /app/data/automation/. Never stores secrets.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from app.backend.services.automation_store import (
    APPLY_RECIPE_MAX,
    auto_launch_env_allows,
    read_cron_recipe,
    read_last_scan,
    read_scan_history,
    write_cron_recipe,
    write_last_scan,
)
from app.backend.services.paper_run_service import CORE_STRATEGY_IDS

logger = logging.getLogger(__name__)

_PRESET_ANALYST_IDS = {
    "core": list(CORE_STRATEGY_IDS),
    "value": [
        "ben_graham",
        "warren_buffett",
        "charlie_munger",
        "aswath_damodaran",
        "fundamentals_analyst",
        "valuation_analyst",
    ],
    "growth": [
        "cathie_wood",
        "peter_lynch",
        "phil_fisher",
        "growth_analyst",
        "technical_analyst",
    ],
    "quant": [
        "technical_analyst",
        "autoresearch",
        "apex",
        "market_regime",
        "sentiment_analyst",
        "news_sentiment_analyst",
    ],
}


def _strategy_ids_for_preset(preset: str) -> List[str]:
    p = (preset or "core").strip().lower()
    if p == "custom":
        return list(CORE_STRATEGY_IDS)
    return list(_PRESET_ANALYST_IDS.get(p, CORE_STRATEGY_IDS))


def _normalize_source_tags(raw_source: str, *, is_core: bool = False) -> List[str]:
    """Map scan_market sources → mover | active | core tags."""
    tags: List[str] = []
    if is_core:
        tags.append("core")
    src = (raw_source or "").lower()
    if "gainer" in src or "loser" in src or "mover" in src:
        tags.append("mover")
    if "active" in src:
        tags.append("active")
    seen: Set[str] = set()
    out: List[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    if out:
        return out
    return ["core"] if is_core else ["mover"]


def _mode_universe_tickers(mode: str) -> Set[str]:
    """All tickers from get_mode_config(mode)['universe'] buckets."""
    try:
        from src.config import get_mode_config

        m = (mode or "swing").strip().lower()
        if m == "auto" or m not in ("swing", "day"):
            m = "swing"
        universe = get_mode_config(m).get("universe") or {}
        out: Set[str] = set()
        for bucket in universe.values():
            if not isinstance(bucket, dict):
                continue
            for t in bucket.get("tickers") or []:
                if t:
                    out.add(str(t).strip().upper())
        return out
    except Exception as e:
        logger.warning("Could not load mode universe (%s)", type(e).__name__)
        return set()


def _sanitize_candidate(c: Dict[str, Any]) -> Dict[str, Any]:
    """Strip anything secret-looking; keep public scan fields + source tags."""
    sym = str(c.get("symbol") or c.get("ticker") or "").strip().upper()
    sources = c.get("sources")
    if not isinstance(sources, list):
        sources = _normalize_source_tags(str(c.get("source") or ""), is_core=False)
    clean_sources = [str(s) for s in sources if str(s) in ("mover", "active", "core")]
    out: Dict[str, Any] = {
        "symbol": sym,
        "sources": clean_sources or ["mover"],
    }
    for key in ("price", "change_pct", "trade_count", "volume"):
        if key in c and c[key] is not None:
            out[key] = c[key]
    return out


def run_swarm_scan(
    *,
    mode: Optional[str] = None,
    intersect_universe: bool = True,
    max_tickers: int = 25,
    include_core: bool = True,
    min_price: float = 10.0,
    min_trades: int = 5000,
    persist: bool = True,
) -> Dict[str, Any]:
    """Run market scan, tag candidates, optional mode-universe intersect, persist.

    Default ``intersect_universe=True`` (amendment: ON for swing/day).
    """
    from scan_market import scan as market_scan

    recipe = read_cron_recipe()
    resolved_mode = (mode or recipe.get("mode") or "swing").strip().lower()
    if resolved_mode not in ("swing", "day", "auto"):
        resolved_mode = "swing"
    intersect_mode = "swing" if resolved_mode == "auto" else resolved_mode

    raw = market_scan(
        min_price=min_price,
        min_trades=min_trades,
        max_tickers=max_tickers,
        include_core=include_core,
    )

    discovered_meta = {
        str(d.get("symbol", "")).upper(): d
        for d in (raw.get("discovered") or [])
        if d.get("symbol")
    }
    candidates: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    core_set = {str(s).strip().upper() for s in (raw.get("core_watchlist") or [])}

    for sym in raw.get("core_watchlist") or []:
        s = str(sym).strip().upper()
        if not s or s in seen:
            continue
        seen.add(s)
        meta = discovered_meta.get(s) or {}
        tags = _normalize_source_tags(str(meta.get("source") or ""), is_core=True)
        cand = {
            "symbol": s,
            "sources": tags,
            **{k: meta[k] for k in ("price", "change_pct", "trade_count", "volume") if k in meta},
        }
        candidates.append(_sanitize_candidate(cand))

    for d in raw.get("discovered") or []:
        s = str(d.get("symbol") or "").strip().upper()
        if not s or s in seen:
            continue
        seen.add(s)
        tags = _normalize_source_tags(str(d.get("source") or ""), is_core=False)
        cand = {
            "symbol": s,
            "sources": tags,
            **{k: d[k] for k in ("price", "change_pct", "trade_count", "volume") if k in d},
        }
        candidates.append(_sanitize_candidate(cand))

    for t in raw.get("tickers") or []:
        s = str(t).strip().upper()
        if not s or s in seen:
            continue
        seen.add(s)
        candidates.append(
            _sanitize_candidate(
                {"symbol": s, "sources": ["core"] if s in core_set else ["mover"]}
            )
        )

    universe: Set[str] = set()
    did_intersect = False
    if intersect_universe:
        universe = _mode_universe_tickers(intersect_mode)
        if universe:
            filtered = [c for c in candidates if c["symbol"] in universe]
            did_intersect = True
            if filtered:
                candidates = filtered
            else:
                # Intersect empty — keep universe names as core-tagged fallback (still safe)
                candidates = [
                    _sanitize_candidate({"symbol": sym, "sources": ["core"]})
                    for sym in list(universe)[:max_tickers]
                ]

    tickers = [c["symbol"] for c in candidates]

    result: Dict[str, Any] = {
        "timestamp": raw.get("timestamp"),
        "mode": resolved_mode,
        "intersect_universe": bool(intersect_universe),
        "intersected": did_intersect,
        "universe_size": len(universe) if intersect_universe else None,
        "candidates": candidates,
        "tickers": tickers,
        "candidate_count": len(candidates),
        "paper_only": True,
        "source": "scan_market.scan",
    }

    if persist:
        try:
            write_last_scan(result)
        except Exception as e:
            logger.warning("Could not persist last scan (%s)", type(e).__name__)

    return result


def apply_scan_to_recipe(
    *,
    top_n: int = APPLY_RECIPE_MAX,
    tickers: Optional[List[str]] = None,
    candidates: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """C2 — Apply top N (≤15) scan candidates to cron_recipe tickers."""
    n = max(1, min(int(top_n or APPLY_RECIPE_MAX), APPLY_RECIPE_MAX))

    chosen: List[str] = []
    applied_candidates: List[Dict[str, Any]] = []

    def _push(sym: str, cand: Optional[Dict[str, Any]] = None) -> None:
        nonlocal chosen, applied_candidates
        if len(chosen) >= n:
            return
        if not sym or not sym.replace(".", "").isalnum():
            return
        if sym in chosen:
            return
        chosen.append(sym)
        applied_candidates.append(
            _sanitize_candidate(cand or {"symbol": sym, "sources": ["mover"]})
        )

    if tickers:
        for t in tickers:
            _push(str(t).strip().upper())
    elif candidates:
        for c in candidates:
            if not isinstance(c, dict):
                continue
            sym = str(c.get("symbol") or c.get("ticker") or "").strip().upper()
            _push(sym, c)
    else:
        last = read_last_scan() or {}
        for c in last.get("candidates") or []:
            if not isinstance(c, dict):
                continue
            sym = str(c.get("symbol") or "").strip().upper()
            _push(sym, c)
        if not chosen:
            for t in last.get("tickers") or []:
                _push(str(t).strip().upper())

    if not chosen:
        raise ValueError("No candidates to apply — run a scan first")

    chosen = chosen[:APPLY_RECIPE_MAX]
    applied_candidates = applied_candidates[: len(chosen)]

    current = read_cron_recipe()
    saved = write_cron_recipe({**current, "tickers": chosen})
    return {
        "recipe": saved,
        "applied_tickers": chosen,
        "applied_count": len(chosen),
        "cap": APPLY_RECIPE_MAX,
        "candidates": applied_candidates,
        "paper_only": True,
    }


def get_last_scan_payload() -> Dict[str, Any]:
    last = read_last_scan()
    history = read_scan_history(limit=10)
    return {
        "paper_only": True,
        "last_scan": last,
        "recent_scans": history,
        "auto_launch_env_allows": auto_launch_env_allows(),
        "apply_cap": APPLY_RECIPE_MAX,
    }


def launch_analysis_from_recipe(
    *,
    execute_trades: bool = False,
    tickers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """C3 — Start paper analysis using recipe tickers + preset analysts.

    Prefer analysis-only. Execute only when explicitly requested AND dual-gated
    by ``SWARM_CRON_EXECUTE_TRADES`` ∧ request. Never flips MONITOR_DRY_RUN or live.
    """
    from app.backend.services.automation_store import (
        cron_execute_env_allows,
        resolve_cron_execute_trades,
        write_last_paper_run,
    )
    from app.backend.services.paper_run_service import (
        alpaca_trading_mode,
        assert_paper_only,
        create_run_record,
        has_alpaca_keys,
        start_paper_run_async,
    )

    if not has_alpaca_keys():
        raise PermissionError(
            "FAIL_CLOSED: ALPACA_API_KEY and ALPACA_API_SECRET are not set"
        )
    assert_paper_only()
    if alpaca_trading_mode() == "live":
        raise PermissionError("FAIL_CLOSED: refuses ALPACA_TRADING_MODE=live")

    recipe = read_cron_recipe()
    mode = (recipe.get("mode") or "swing").strip().lower()
    if mode not in ("swing", "day", "auto"):
        mode = "swing"

    use_tickers = tickers or recipe.get("tickers") or []
    use_tickers = [str(t).strip().upper() for t in use_tickers if t][:APPLY_RECIPE_MAX]
    if not use_tickers:
        raise ValueError("No tickers — apply scan to recipe or provide tickers")

    strategy_ids = _strategy_ids_for_preset(recipe.get("preset") or "core")

    # Analysis-only default; execute only if caller explicitly asks + dual gate
    do_execute = False
    if execute_trades:
        do_execute = resolve_cron_execute_trades(True)

    run_id = create_run_record(
        use_tickers,
        strategy_ids,
        mode,
        execute_trades=do_execute,
        instrument="stocks",
    )
    start_paper_run_async(run_id)

    payload = {
        "run_id": run_id,
        "status": "queued",
        "mode": mode,
        "tickers": use_tickers,
        "strategy_ids": strategy_ids,
        "execute_trades": do_execute,
        "execute_requested": bool(execute_trades),
        "cron_execute_env_allows": cron_execute_env_allows(),
        "paper": True,
        "paper_only": True,
        "message": "Paper analysis started from swarm scan / recipe",
    }
    try:
        write_last_paper_run(payload)
    except Exception:
        pass
    return payload
