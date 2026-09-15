"""G3 (Wave G) — optional, read-only market-data quote WebSocket for HIT.

Off by default (``SWARM_HIT_QUOTE_WS_ENABLED``). When enabled, maintains a
**single** connection to Alpaca's market-data quote stream
(``wss://stream.data.alpaca.markets/v2/{feed}``) to shave the REST
request/response round-trip off quote freshness for the F2/G3 cost gate.
This is the closest this paper/broker-API stack gets to "live" market data —
it is still a retail data feed over a public API, not co-located, and this
module makes no latency claim beyond "fresher than one-shot REST polling".

**Single-connection discipline is mandatory, not a nice-to-have.** Alpaca's
market-data stream allows exactly one connection per feed per account/key —
opening a second one drops the first (the same constraint F5's docs cite for
why this codebase has never opened a ``trade_updates`` order-stream
connection). ``start()`` therefore refuses to start a second connection while
one is already running; callers get ``False`` back, not a queued/duplicate
attempt.

**No order/trade_updates WebSocket is added here or anywhere by this
module.** This is read-only market data (quotes) only; order state
(submitted/filled) is still read via REST exactly as before (F5's
``_place_alpaca_order`` best-effort follow-up ``GET /orders/{id}``). Nothing
here places, cancels, or watches orders.

REST fallback is unconditional: every call site that consults this cache
(``cost_gate_service.fetch_quotes_and_prices``) always falls back to a
one-shot REST quote fetch when this cache has no fresh entry — whether
because the WS is disabled (default), not yet connected, reconnecting, or
simply has not received a quote for that ticker yet. The WS is a latency
optimization, never a hard dependency.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

QUOTE_WS_ENABLED_ENV = "SWARM_HIT_QUOTE_WS_ENABLED"
DEFAULT_WS_BASE_URL = "wss://stream.data.alpaca.markets/v2"

# How long a cached entry may sit before this module stops offering it at
# all (independent of — and looser than — the G3 cost-gate freshness budget,
# which re-checks the quote's own timestamp regardless of source). This is
# just housekeeping so a dead/reconnecting stream does not serve minutes-old
# "cached" quotes as if they were merely REST-latency-fresh.
CACHE_HARD_EVICT_SECONDS = 30.0


def quote_ws_enabled() -> bool:
    """True only when ``SWARM_HIT_QUOTE_WS_ENABLED`` is explicitly truthy."""
    val = (os.environ.get(QUOTE_WS_ENABLED_ENV) or "").strip().lower()
    return val in ("1", "true", "yes", "on")


def quote_ws_feed() -> str:
    """Market-data feed for the stream URL — mirrors ``ALPACA_DATA_FEED``."""
    feed = (os.environ.get("ALPACA_DATA_FEED") or "sip").strip().lower()
    return feed or "sip"


def quote_ws_url() -> str:
    base = (os.environ.get("SWARM_HIT_QUOTE_WS_URL") or DEFAULT_WS_BASE_URL).rstrip("/")
    return f"{base}/{quote_ws_feed()}"


def parse_quote_message(msg: Any) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Parse one decoded Alpaca data-stream message into ``(ticker, quote)``.

    Only quote messages (``"T": "q"``) are handled — trade ("t"), bar ("b"),
    control (``"success"``/``"subscription"``/``"error"``) messages all
    return ``None``. Returns ``None`` for anything malformed rather than
    guessing. The returned ``quote`` dict uses the same key names
    (``bp``/``ap``/``t``/...) as the REST latest-quote endpoint so both
    sources are interchangeable to ``cost_gate_service``.
    """
    if not isinstance(msg, dict):
        return None
    if msg.get("T") != "q":
        return None
    sym = msg.get("S")
    if not sym or not isinstance(sym, str):
        return None
    # "as" (ask size) is a plain string dict key here — only a problem as a
    # Python identifier/keyword, not as a key in a dict literal/comprehension.
    quote = {k: msg.get(k) for k in ("bp", "ap", "bs", "as", "t") if k in msg}
    return sym.strip().upper(), quote


def parse_quote_messages(payload: Any) -> List[Tuple[str, Dict[str, Any]]]:
    """Parse a raw WS frame (single message or a list of messages) into
    ``[(ticker, quote), ...]`` — quote messages only, others skipped."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            return []
    items = payload if isinstance(payload, list) else [payload]
    out: List[Tuple[str, Dict[str, Any]]] = []
    for item in items:
        parsed = parse_quote_message(item)
        if parsed:
            out.append(parsed)
    return out


class QuoteCache:
    """Thread-safe latest-quote-per-ticker cache. Pure in-memory, no I/O."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: Dict[str, Dict[str, Any]] = {}

    def set(self, ticker: str, quote: Dict[str, Any]) -> None:
        sym = (ticker or "").strip().upper()
        if not sym:
            return
        with self._lock:
            self._store[sym] = {**quote, "_cached_at": time.monotonic()}

    def get(self, ticker: str, *, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Latest cached quote for ``ticker``, or ``None`` if absent/evicted.

        Only hard-evicts entries older than ``CACHE_HARD_EVICT_SECONDS`` of
        wall-clock cache residency — the *real* freshness check (against the
        quote's own ``t`` timestamp) happens once, centrally, in
        ``cost_gate_service.evaluate_cost_gate`` for every quote regardless
        of source.
        """
        sym = (ticker or "").strip().upper()
        with self._lock:
            entry = self._store.get(sym)
            if not entry:
                return None
            cached_at = entry.get("_cached_at")
            now_m = now if now is not None else time.monotonic()
            if cached_at is not None and (now_m - cached_at) > CACHE_HARD_EVICT_SECONDS:
                del self._store[sym]
                return None
            return {k: v for k, v in entry.items() if k != "_cached_at"}

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


class HitQuoteWebSocketClient:
    """Single-connection-disciplined optional quote WS client.

    Off unless explicitly enabled. ``start()`` refuses to start a second
    connection while one is already running (Alpaca allows only one stream
    connection per feed per account) — it returns ``False`` rather than
    queuing or silently replacing the existing one.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.cache = QuoteCache()

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def start(self, tickers: List[str]) -> bool:
        """Start the single allowed connection. Returns ``False`` (no-op)
        when disabled, credentials are missing, or already running."""
        if not quote_ws_enabled():
            logger.info("HIT quote WS disabled (%s unset) — REST-only", QUOTE_WS_ENABLED_ENV)
            return False
        try:
            from src.tools.alpaca_data import alpaca_credentials_configured

            if not alpaca_credentials_configured():
                logger.info("HIT quote WS: no Alpaca credentials configured — REST-only")
                return False
        except Exception as e:  # pragma: no cover - import should always succeed
            logger.warning("HIT quote WS: could not check credentials (%s)", type(e).__name__)
            return False

        with self._lock:
            if self._running:
                logger.warning(
                    "HIT quote WS: start() refused — a connection is already running "
                    "(single-connection discipline; Alpaca allows one stream per feed/account)"
                )
                return False
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run, args=(list(tickers or []),), daemon=True
            )
            self._thread.start()
            return True

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            if not self._running:
                return
            self._stop_event.set()
            thread = self._thread
        if thread:
            thread.join(timeout=timeout)
        with self._lock:
            self._running = False
            self._thread = None

    def _run(self, tickers: List[str]) -> None:
        """Background thread body — owns its own asyncio loop.

        Overridden/monkeypatched in tests to avoid opening a real socket;
        the reconnect-with-backoff live-socket path is exercised manually
        (staging), not by the automated unit suite — see docs/WAVE_G_LATENCY_MAX.md.
        """
        import asyncio

        try:
            asyncio.run(self._run_async(tickers))
        except Exception as e:
            logger.warning("HIT quote WS loop exited (%s)", type(e).__name__)
        finally:
            with self._lock:
                self._running = False

    async def _run_async(self, tickers: List[str]) -> None:
        import asyncio
        import websockets

        from src.tools.alpaca_data import alpaca_api_key, alpaca_api_secret

        backoff = 1.0
        max_backoff = 30.0
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(quote_ws_url(), open_timeout=10) as ws:
                    await ws.send(
                        json.dumps(
                            {
                                "action": "auth",
                                "key": alpaca_api_key(),
                                "secret": alpaca_api_secret(),
                            }
                        )
                    )
                    await ws.recv()  # auth ack — content not trusted/parsed beyond ignoring
                    await ws.send(json.dumps({"action": "subscribe", "quotes": tickers}))
                    backoff = 1.0  # reset after a clean connect
                    while not self._stop_event.is_set():
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        for sym, quote in parse_quote_messages(raw):
                            if sym in tickers or not tickers:
                                self.cache.set(sym, quote)
            except asyncio.TimeoutError:
                continue  # idle recv timeout — loop back and check stop_event
            except Exception as e:
                if self._stop_event.is_set():
                    break
                logger.info(
                    "HIT quote WS disconnected (%s) — reconnecting in %.0fs",
                    type(e).__name__,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(max_backoff, backoff * 2)


_client_lock = threading.Lock()
_client: Optional[HitQuoteWebSocketClient] = None


def get_client() -> HitQuoteWebSocketClient:
    """Module-level singleton — enforces the single-connection discipline
    process-wide (not just per-instance)."""
    global _client
    with _client_lock:
        if _client is None:
            _client = HitQuoteWebSocketClient()
        return _client


def start_quote_ws(tickers: List[str]) -> bool:
    return get_client().start(tickers)


def stop_quote_ws() -> None:
    get_client().stop()


def is_quote_ws_running() -> bool:
    return get_client().is_running()


def get_cached_quote(ticker: str) -> Optional[Dict[str, Any]]:
    """Freshest cached quote for ``ticker``, or ``None``.

    ``None`` means "no fresh WS-cached quote" for any reason (disabled, not
    started, disconnected, ticker not subscribed, entry hard-evicted) —
    callers (``cost_gate_service.fetch_quotes_and_prices``) always have a
    REST fallback for that case.
    """
    return get_client().cache.get(ticker)


def reset_for_tests() -> None:
    """Test-only: replace the singleton so tests never share WS/cache state."""
    global _client
    with _client_lock:
        _client = HitQuoteWebSocketClient()
