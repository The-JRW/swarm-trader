"""F3 + F4 — HIT pulse orchestration + preset. G2 (Wave G) — fast HIT path.

F3: default **scan-lite + analysis-only**. Execute is only attempted when the
caller explicitly asks for it **and** ``SWARM_HIT_EXECUTE`` is truthy (dual
gate, same pattern as B1/C4 cron execute). Cadence (how often a pulse fires)
is owned by an external scheduler/cron — nothing here schedules itself.
G5 (Wave G) keeps this default and the dual gate exactly as-is.

F4: the ``hit`` preset favors deterministic/fast signals (technical +
market_regime + autoresearch + sentiment) over heavier LLM-driven research —
HIT holds are short (minutes-hours), so this wave prefers signal classes with
a fast, defined evaluation cost over slower/heavier ones. Honest breakdown
(the graph in ``src/main.py`` fans every selected analyst out from
``start_node`` in parallel and fans back in at risk/PM — there is no
node-execution-order dependency here, so "fast" means *which analysts are
selected*, not a claim about node scheduling order):
  - ``technical_analyst``, ``autoresearch``: zero LLM calls (pure/deterministic).
  - ``market_regime``: one lightweight structured-output LLM classification
    call (SPY/QQQ regime label) — smaller than a full per-ticker trading
    decision, still an LLM call; grouped with the fast set by design intent,
    documented honestly rather than mislabeled as zero-LLM.
  - ``sentiment_analyst``: zero LLM calls (rule-based insider-trade/news scoring).

G2 (Wave G): ``apex`` and ``news_sentiment_analyst`` both make a full LLM
call per ticker (technical/tape reasoning and news summarization,
respectively) — the genuinely **slow path**. They are never included in the
default HIT preset. A caller may opt into them by explicitly requesting
``fast=False`` (mirrors the dual-gate philosophy: an explicit ask, never an
implicit default) — since every selected analyst still runs as a parallel
node feeding the same fan-in, adding the slow path makes the *whole* run
wait on an LLM call it would not otherwise need, which is exactly the
trade-off ``fast=True`` (the HIT default) avoids.

HIT is paper-only and never claims true HFT (no co-location, no queue
priority, no LOB imbalance modeling) — see docs/WAVE_F_HIT.md and
docs/WAVE_G_LATENCY_MAX.md.

James t180u (same PR/tag as G2's Ops-visible amendment, strategies-ux-16):
HIT analysis/flow must be able to cover **hundreds** of tickers, not the
previous ~10-15 hard ceiling. ``HIT_MAX_TICKERS`` (default 300, env
``SWARM_HIT_MAX_TICKERS``) replaces the old hardcoded ``15`` clamp in
``run_hit_pulse``; the *default* request size (``DEFAULT_HIT_TICKER_CAP``,
still 10) is unchanged so an unspecified/cron pulse stays exactly as fast
as before — hundreds only happen when a caller (scan-discovered tickers,
an explicit list, or a large ``top_n``) actually asks for them. Also adds
an auto-fast safety rail: even an explicit ``fast=False`` (slow path) ask
is overridden back to fast when the resolved ticker count exceeds
``HIT_AUTO_FAST_TICKER_THRESHOLD`` (30) — hundreds of tickers must never
wait on the LLM-heavy ``apex``/``news_sentiment_analyst`` pair, which would
turn a "latency-max" run into an LLM-call meltdown. See
docs/WAVE_G_LATENCY_MAX.md's "James t180u" section.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# F4 — deterministic/fast signals first, heavier LLM research after. See the
# module docstring above for exactly which of these make an LLM call.
HIT_PRESET_ANALYST_IDS: List[str] = [
    "technical_analyst",
    "market_regime",
    "autoresearch",
    "sentiment_analyst",
]

# G2 — optional "slow path". Both make one full LLM call per ticker; never
# included by default. Only added when a caller explicitly requests
# ``fast=False`` on ``run_hit_pulse``.
HIT_SLOW_LLM_ANALYST_IDS: List[str] = [
    "apex",
    "news_sentiment_analyst",
]

DEFAULT_HIT_TICKER_CAP = 10

# James t180u — the ceiling a HIT pulse may request/allow, not a default.
# Alpaca's screener may still return fewer names than requested on a given
# call (see scan_market.HIT_MAX_TICKERS) — this only raises what this
# codebase is willing to accept when a caller does ask for hundreds.
HIT_MAX_TICKERS = int(os.environ.get("SWARM_HIT_MAX_TICKERS", "300"))

# James t180u — safety rail, not a new default: an explicit fast=False (slow
# path) request is auto-overridden back to fast when the resolved ticker
# count exceeds this, so hundreds of tickers never wait on apex/
# news_sentiment_analyst's one-full-LLM-call-per-ticker each. Does not
# affect fast=True (already the default for any N) or small slow-path runs.
HIT_AUTO_FAST_TICKER_THRESHOLD = 30


def resolve_hit_analyst_ids(fast: bool = True) -> List[str]:
    """G2 — the analyst set for a HIT run.

    ``fast=True`` (the default — mirrors ``mode == "hit"``'s existing
    behavior unchanged): the fast preset only, never the LLM-heavy pair.
    ``fast=False`` (explicit opt-in only): fast preset **plus** the slow-path
    pair appended after it — an explicit, documented trade-off, not a hidden
    default; the whole run now waits on two more LLM calls per ticker.
    """
    ids = list(HIT_PRESET_ANALYST_IDS)
    if not fast:
        ids.extend(HIT_SLOW_LLM_ANALYST_IDS)
    return ids


def hit_universe_tickers(cap: int = DEFAULT_HIT_TICKER_CAP) -> List[str]:
    """Liquid tickers from ``MODES['hit']['universe']`` (James t180u — widened
    to 100+ well-known liquid large-cap names across sectors, plus SPY/QQQ;
    see ``src/config.py``'s ``hit`` universe comment). ``cap`` may be as
    large as the full universe size; this is a fallback for when no scan
    result or explicit ticker list is available — the primary way a HIT run
    reaches "hundreds" is the market scanner or an explicit ticker list."""
    from src.config import get_mode_config

    universe = get_mode_config("hit").get("universe") or {}
    out: List[str] = []
    for bucket in universe.values():
        if not isinstance(bucket, dict):
            continue
        for t in bucket.get("tickers") or []:
            sym = str(t).strip().upper()
            if sym and sym not in out:
                out.append(sym)
    return out[: max(1, cap)] if cap else out


def run_hit_pulse(
    *,
    tickers: Optional[List[str]] = None,
    execute_requested: bool = False,
    top_n: int = DEFAULT_HIT_TICKER_CAP,
    fast: bool = True,
) -> Dict[str, Any]:
    """F3 — start a HIT paper run. Analysis-only unless dual-gated execute.

    Reuses the same paper_run_service / risk_manager / conviction-digest path
    as every other paper run — no bypass, no parallel execution logic. The
    F2 cost gate is applied inside ``paper_run_service.execute_paper_run``
    whenever ``mode == "hit"`` and execute is effectively on.

    G2 — ``fast`` (default ``True``, matching every prior HIT pulse
    behavior unchanged) selects the analyst set via
    ``resolve_hit_analyst_ids``: fast preset only by default, or fast preset
    + the LLM-heavy ``apex``/``news_sentiment_analyst`` pair when the caller
    explicitly passes ``fast=False``.

    James t180u — ``top_n`` may now request up to ``HIT_MAX_TICKERS`` (300
    by default) instead of the previous hard 15-ticker ceiling; the
    *default* (``top_n`` omitted) is still ``DEFAULT_HIT_TICKER_CAP`` (10),
    unchanged. When the resolved ticker count exceeds
    ``HIT_AUTO_FAST_TICKER_THRESHOLD`` (30), an explicit ``fast=False`` is
    auto-overridden back to ``fast=True`` — see module docstring.
    """
    from app.backend.services.automation_store import read_cron_recipe, write_last_paper_run
    from app.backend.services.hit_ops_service import hit_execute_env_allows, resolve_hit_execute
    from app.backend.services.paper_run_service import (
        alpaca_trading_mode,
        assert_paper_only,
        create_run_record,
        has_alpaca_keys,
        start_paper_run_async,
    )

    if not has_alpaca_keys():
        raise PermissionError(
            "FAIL_CLOSED: ALPACA_API_KEY and ALPACA_API_SECRET are not set — "
            "cannot start a HIT pulse."
        )
    assert_paper_only()
    if alpaca_trading_mode() == "live":
        raise PermissionError("FAIL_CLOSED: HIT pulse refuses ALPACA_TRADING_MODE=live")

    recipe = read_cron_recipe()
    # James t180u — ceiling raised from a hardcoded 15 to HIT_MAX_TICKERS
    # (default 300); the default *size* when top_n is omitted is unchanged
    # (DEFAULT_HIT_TICKER_CAP, 10).
    cap = max(1, min(int(top_n or DEFAULT_HIT_TICKER_CAP), HIT_MAX_TICKERS))
    use_tickers = tickers or (
        recipe.get("tickers") if (recipe.get("mode") or "").lower() == "hit" else None
    ) or hit_universe_tickers(cap)
    use_tickers = [str(t).strip().upper() for t in use_tickers if t][:cap]
    if not use_tickers:
        use_tickers = hit_universe_tickers(cap)

    # Dual gate: request/body true AND SWARM_HIT_EXECUTE truthy.
    do_execute = resolve_hit_execute(execute_requested)

    # James t180u — auto-fast safety rail: hundreds of tickers must never
    # wait on the LLM-heavy slow pair, even if the caller explicitly asked
    # for fast=False. Small/medium slow-path requests (<= threshold) are
    # honored exactly as before — this never touches fast=True.
    requested_fast = bool(fast)
    auto_fast_override = (not requested_fast) and len(use_tickers) > HIT_AUTO_FAST_TICKER_THRESHOLD
    effective_fast = True if auto_fast_override else requested_fast

    analyst_ids = resolve_hit_analyst_ids(fast=effective_fast)
    run_id = create_run_record(
        use_tickers,
        analyst_ids,
        "hit",
        execute_trades=do_execute,
        instrument="stocks",
    )
    start_paper_run_async(run_id)

    if auto_fast_override:
        fast_path_note = (
            f"fast=false was requested but auto-overridden to fast=true — "
            f"{len(use_tickers)} tickers exceeds the "
            f"{HIT_AUTO_FAST_TICKER_THRESHOLD}-ticker auto-fast threshold "
            "(James t180u safety rail: hundreds of tickers never wait on the "
            "apex + news_sentiment_analyst slow pair). See "
            "docs/WAVE_G_LATENCY_MAX.md."
        )
    elif effective_fast:
        fast_path_note = (
            "fast=true (default): technical_analyst/market_regime/autoresearch/"
            "sentiment_analyst only. fast=false: adds apex + news_sentiment_analyst "
            "(one full LLM call per ticker each) — the slow path, opt-in only. "
            "See docs/WAVE_G_LATENCY_MAX.md."
        )
    else:
        fast_path_note = (
            "fast=false (explicit opt-in): adds apex + news_sentiment_analyst "
            "(one full LLM call per ticker each) to the fast preset. "
            "See docs/WAVE_G_LATENCY_MAX.md."
        )

    payload = {
        "run_id": run_id,
        "status": "queued",
        "mode": "hit",
        "tickers": use_tickers,
        # James t180u — Ops-visible ticker count, so Reviewer/James can see
        # "hundreds" without counting the tickers array by hand.
        "ticker_count": len(use_tickers),
        "strategy_ids": analyst_ids,
        "fast": bool(effective_fast),
        "fast_requested": requested_fast,
        "auto_fast_override": auto_fast_override,
        "execute_trades": do_execute,
        "execute_requested": bool(execute_requested),
        "hit_execute_env_allows": hit_execute_env_allows(),
        "paper": True,
        "paper_only": True,
        "message": "HIT pulse started — analysis-only unless SWARM_HIT_EXECUTE ∧ requested",
        "cadence_note": (
            "Cadence is Scheduler/cron-owned (e.g. every ~15m during RTH) — this "
            "endpoint does not schedule itself. See docs/WAVE_F_HIT.md."
        ),
        "fast_path_note": fast_path_note,
    }
    try:
        write_last_paper_run(payload)
    except Exception as e:
        logger.warning("Could not persist last HIT pulse (%s)", type(e).__name__)
    return payload
