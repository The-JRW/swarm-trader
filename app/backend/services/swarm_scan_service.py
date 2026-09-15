"""C1 — Swarm market scan service (paper-only orchestration).

Wraps ``scan_market.scan()``, optionally intersects with mode universe,
persists last scan + history under /app/data/automation/. Never stores secrets.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from app.backend.services.automation_store import (
    APPLY_RECIPE_MAX,
    HIT_APPLY_RECIPE_MAX,
    apply_recipe_max_for,
    auto_launch_env_allows,
    read_cron_recipe,
    read_last_scan,
    read_scan_history,
    write_cron_recipe,
    write_last_scan,
)
from app.backend.services.paper_run_service import CORE_STRATEGY_IDS

logger = logging.getLogger(__name__)

OTHER_SECTOR = "other"
DEFAULT_SECTOR_PCT = 0.30

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
    # F4 — HIT preset: deterministic/fast signals ahead of heavier LLM research.
    "hit": [
        "technical_analyst",
        "market_regime",
        "autoresearch",
        "sentiment_analyst",
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


def _normalize_universe_mode(mode: Optional[str]) -> str:
    m = (mode or "swing").strip().lower()
    if m == "auto" or m not in ("swing", "day", "hit"):
        return "swing"
    return m


def _mode_universe_tickers(mode: str) -> Set[str]:
    """All tickers from get_mode_config(mode)['universe'] buckets."""
    try:
        from src.config import get_mode_config

        universe = get_mode_config(_normalize_universe_mode(mode)).get("universe") or {}
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


def _sector_policy(mode: Optional[str]) -> Dict[str, Any]:
    """D3 — ticker→sector map plus sector caps/labels for the mode universe.

    Sector percentage caps come from ``src.config`` (the same numbers
    ``risk_manager`` enforces). Nothing here widens a cap; unknown tickers land
    in the ``other`` bucket which uses the mode-level ``max_sector_pct``.
    """
    resolved = _normalize_universe_mode(mode)
    ticker_sector: Dict[str, str] = {}
    sector_pct: Dict[str, float] = {}
    sector_label: Dict[str, str] = {}
    default_pct = DEFAULT_SECTOR_PCT
    try:
        from src.config import get_mode_config

        config = get_mode_config(resolved)
        risk = config.get("risk") or {}
        default_pct = float(risk.get("max_sector_pct") or DEFAULT_SECTOR_PCT)
        for key, bucket in (config.get("universe") or {}).items():
            if not isinstance(bucket, dict):
                continue
            sector_pct[key] = float(bucket.get("max_sector_pct") or default_pct)
            sector_label[key] = str(bucket.get("label") or key.replace("_", " ").title())
            for t in bucket.get("tickers") or []:
                if t:
                    ticker_sector[str(t).strip().upper()] = key
    except Exception as e:
        logger.warning("Could not load sector policy (%s)", type(e).__name__)

    sector_pct[OTHER_SECTOR] = default_pct
    sector_label[OTHER_SECTOR] = "Unclassified / off-universe"
    return {
        "mode": resolved,
        "ticker_sector": ticker_sector,
        "sector_pct": sector_pct,
        "sector_label": sector_label,
        "default_pct": default_pct,
    }


def _sector_slot_cap(sector_pct: float, slots: int) -> int:
    """Translate a sector % cap into a max ticker count for ``slots`` picks."""
    try:
        cap = int(float(sector_pct) * int(slots))
    except (TypeError, ValueError):
        cap = slots
    return max(1, min(cap, slots))


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
    max_tickers: Optional[int] = None,
    include_core: bool = True,
    min_price: float = 10.0,
    min_trades: int = 5000,
    persist: bool = True,
) -> Dict[str, Any]:
    """Run market scan, tag candidates, optional mode-universe intersect, persist.

    Default ``intersect_universe=True`` (amendment: ON for swing/day).

    James t180u — ``max_tickers=None`` (the default) now resolves to
    ``scan_market.HIT_MAX_TICKERS`` (hundreds) when the resolved mode is
    ``hit``, or ``scan_market.DEFAULT_MAX_TICKERS`` (25, unchanged)
    otherwise. Callers may still pass an explicit ``max_tickers`` to
    override either default.
    """
    from scan_market import DEFAULT_MAX_TICKERS, HIT_MAX_TICKERS
    from scan_market import scan as market_scan

    recipe = read_cron_recipe()
    resolved_mode = (mode or recipe.get("mode") or "swing").strip().lower()
    if resolved_mode not in ("swing", "day", "hit", "auto"):
        resolved_mode = "swing"
    intersect_mode = "swing" if resolved_mode == "auto" else resolved_mode

    if max_tickers is None:
        max_tickers = HIT_MAX_TICKERS if intersect_mode == "hit" else DEFAULT_MAX_TICKERS

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


def _candidate_pool(
    *,
    tickers: Optional[List[str]] = None,
    candidates: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Ordered, de-duped candidate pool from explicit input or the last scan."""
    pool: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    def _add(sym: str, cand: Optional[Dict[str, Any]] = None) -> None:
        if not sym or not sym.replace(".", "").isalnum() or sym in seen:
            return
        seen.add(sym)
        pool.append(_sanitize_candidate(cand or {"symbol": sym, "sources": ["mover"]}))

    if tickers:
        for t in tickers:
            _add(str(t).strip().upper())
        return pool

    if candidates:
        for c in candidates:
            if not isinstance(c, dict):
                continue
            _add(str(c.get("symbol") or c.get("ticker") or "").strip().upper(), c)
        return pool

    last = read_last_scan() or {}
    for c in last.get("candidates") or []:
        if not isinstance(c, dict):
            continue
        _add(str(c.get("symbol") or "").strip().upper(), c)
    if not pool:
        for t in last.get("tickers") or []:
            _add(str(t).strip().upper())
    return pool


def select_sector_aware(
    pool: List[Dict[str, Any]],
    *,
    slots: int,
    policy: Dict[str, Any],
    current_tickers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """D3 — diversify first (underweight sectors), then fill, reporting skips.

    Sector caps only ever *trim* the pick list; they never widen risk. Skipped
    candidates always carry a reason so the UI can explain a short list.
    """
    ticker_sector: Dict[str, str] = policy.get("ticker_sector") or {}
    sector_pct: Dict[str, float] = policy.get("sector_pct") or {}
    sector_label: Dict[str, str] = policy.get("sector_label") or {}
    default_pct = float(policy.get("default_pct") or DEFAULT_SECTOR_PCT)

    def sector_of(symbol: str) -> str:
        return ticker_sector.get(symbol, OTHER_SECTOR)

    def label_of(sector: str) -> str:
        return sector_label.get(sector, sector.replace("_", " ").title())

    queues: Dict[str, List[Dict[str, Any]]] = {}
    first_rank: Dict[str, int] = {}
    for rank, cand in enumerate(pool):
        sector = sector_of(cand["symbol"])
        queues.setdefault(sector, []).append(cand)
        first_rank.setdefault(sector, rank)

    # ``other`` is unclassified, not a sector — risk_manager's sector rule skips
    # it too, so it stays uncapped here (round-robin still spreads the picks).
    caps = {
        sector: slots
        if sector == OTHER_SECTOR
        else _sector_slot_cap(sector_pct.get(sector, default_pct), slots)
        for sector in queues
    }

    # Sectors already represented in the live recipe are "overweight" for the
    # next apply — underweight sectors get first pick.
    current_counts: Dict[str, int] = {}
    for t in current_tickers or []:
        sym = str(t).strip().upper()
        if sym:
            sector = sector_of(sym)
            current_counts[sector] = current_counts.get(sector, 0) + 1

    taken: Dict[str, int] = {sector: 0 for sector in queues}
    chosen: List[Dict[str, Any]] = []

    while len(chosen) < slots:
        order = sorted(
            (s for s in queues if queues[s] and taken[s] < caps[s]),
            key=lambda s: (taken[s], current_counts.get(s, 0), first_rank[s]),
        )
        if not order:
            break
        before = len(chosen)
        for sector in order:
            if len(chosen) >= slots:
                break
            if taken[sector] >= caps[sector] or not queues[sector]:
                continue
            chosen.append(queues[sector].pop(0))
            taken[sector] += 1
        if len(chosen) == before:
            break

    skipped: List[Dict[str, Any]] = []
    for sector, remaining in queues.items():
        for cand in remaining:
            # A sector cap is only the binding constraint when it is tighter
            # than the overall slot budget; otherwise the 15-slot cap trimmed it.
            hit_sector_cap = taken[sector] >= caps[sector] and caps[sector] < slots
            skipped.append(
                {
                    "symbol": cand["symbol"],
                    "sector": sector,
                    "sector_label": label_of(sector),
                    "kind": "sector_cap" if hit_sector_cap else "slot_cap",
                    "reason": (
                        f"{label_of(sector)} sector cap reached — kept {taken[sector]} of "
                        f"{slots} slots (≤{round(sector_pct.get(sector, default_pct) * 100)}% "
                        "sector cap)"
                        if hit_sector_cap
                        else f"apply cap reached — {slots} of {APPLY_RECIPE_MAX} tickers filled"
                    ),
                }
            )

    sectors = [
        {
            "sector": sector,
            "label": label_of(sector),
            "picked": taken[sector],
            "slot_cap": caps[sector],
            "max_sector_pct": None
            if sector == OTHER_SECTOR
            else round(sector_pct.get(sector, default_pct) * 100, 2),
            "candidates_seen": taken[sector] + len(queues[sector]),
            "in_current_recipe": current_counts.get(sector, 0),
        }
        for sector in sorted(queues, key=lambda s: (-taken[s], first_rank[s]))
    ]

    return {
        "chosen": chosen,
        "skipped": skipped,
        "sectors": sectors,
        "sector_caps_trimmed": any(s["kind"] == "sector_cap" for s in skipped),
    }


def apply_scan_to_recipe(
    *,
    top_n: Optional[int] = None,
    tickers: Optional[List[str]] = None,
    candidates: Optional[List[Dict[str, Any]]] = None,
    sector_aware: bool = True,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """C2 + D3 — apply top N candidates to cron_recipe, sector-aware.

    Sector-aware ordering prefers underweight sectors, then fills the remaining
    slots. The recipe is never left empty: if sector selection yields nothing we
    fall back to plain scan order and say so in ``notes``.

    James t180u — the apply cap is mode-aware: ``mode`` (or preset "hit" via
    the current recipe) raises the ceiling to ``HIT_APPLY_RECIPE_MAX``
    (hundreds); every other mode keeps the original ``APPLY_RECIPE_MAX``
    (15) unchanged. ``top_n=None`` (the default) uses the full resolved cap;
    an explicit smaller ``top_n`` is still honored.
    """
    pool = _candidate_pool(tickers=tickers, candidates=candidates)
    if not pool:
        raise ValueError("No candidates to apply — run a scan first")

    current = read_cron_recipe()
    resolved_mode = (mode or current.get("mode") or "swing").strip().lower()
    apply_max = apply_recipe_max_for(resolved_mode, current.get("preset"))
    n = max(1, min(int(top_n or apply_max), apply_max))

    policy = _sector_policy(resolved_mode)
    notes: List[str] = []
    skipped: List[Dict[str, Any]] = []
    sectors: List[Dict[str, Any]] = []
    trimmed = False

    applied_candidates: List[Dict[str, Any]] = []
    if sector_aware:
        selection = select_sector_aware(
            pool,
            slots=n,
            policy=policy,
            current_tickers=current.get("tickers") or [],
        )
        applied_candidates = selection["chosen"]
        skipped = selection["skipped"]
        sectors = selection["sectors"]
        trimmed = bool(selection["sector_caps_trimmed"])
        if trimmed:
            notes.append(
                "Sector caps trimmed the candidate list — see skip reasons "
                "(diversification first, then fill)."
            )

    if not applied_candidates:
        # Never silently produce an empty CORE / recipe.
        applied_candidates = pool[:n]
        skipped = [
            {
                "symbol": c["symbol"],
                "sector": policy["ticker_sector"].get(c["symbol"], OTHER_SECTOR),
                "sector_label": "",
                "kind": "slot_cap",
                "reason": f"apply cap reached — {n} of {apply_max} tickers filled",
            }
            for c in pool[n:]
        ]
        if sector_aware:
            notes.append(
                "Sector-aware selection produced no picks — fell back to scan order "
                "so the recipe is never left empty."
            )

    chosen = [c["symbol"] for c in applied_candidates][:apply_max]
    applied_candidates = applied_candidates[: len(chosen)]
    if not chosen:
        raise ValueError("No candidates to apply — run a scan first")

    # James t180u — only stamp the recipe's own mode when the caller
    # explicitly asked for one (e.g. mode="hit"): write_cron_recipe's own
    # normalization caps tickers by the *persisted* recipe mode/preset, so a
    # hundreds-scale hit apply must actually persist mode="hit" or it would
    # be silently re-clamped back down to 20 on the next read. When mode is
    # omitted, behavior is unchanged — the current recipe's mode is kept
    # exactly as before (mode here was sector-policy-only).
    recipe_patch: Dict[str, Any] = {**current, "tickers": chosen}
    if mode is not None:
        recipe_patch["mode"] = resolved_mode
    saved = write_cron_recipe(recipe_patch)
    if not saved.get("tickers"):
        raise ValueError("Recipe write produced an empty ticker list — refusing empty CORE")

    return {
        "recipe": saved,
        "applied_tickers": chosen,
        "applied_count": len(chosen),
        "cap": apply_max,
        "candidates": applied_candidates,
        "sector_aware": bool(sector_aware),
        "sector_mode": policy["mode"],
        "sectors": sectors,
        "skipped": skipped,
        "skipped_count": len(skipped),
        "sector_caps_trimmed": trimmed,
        "candidate_pool_count": len(pool),
        "notes": notes,
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
    if mode not in ("swing", "day", "hit", "auto"):
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
