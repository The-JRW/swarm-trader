"""
Alpaca market-data client (SIP / IEX / delayed_sip).

Prefer for prices when ALPACA_API_KEY + ALPACA_API_SECRET are set and
ALPACA_DATA_FEED is sip (default). Requires Algo Trader Plus for recent SIP.

Trading stays separate (paper vs live via ALPACA_TRADING_MODE) — this module
only talks to the data API.
Docs: https://docs.alpaca.markets/reference/stockbars
"""

from __future__ import annotations

import os
from typing import Any

import requests

DEFAULT_DATA_URL = "https://data.alpaca.markets"
DEFAULT_FEED = "sip"


def alpaca_api_key() -> str | None:
    key = (os.environ.get("ALPACA_API_KEY") or "").strip()
    return key or None


def alpaca_api_secret() -> str | None:
    secret = (os.environ.get("ALPACA_API_SECRET") or "").strip()
    return secret or None


def alpaca_credentials_configured() -> bool:
    return bool(alpaca_api_key() and alpaca_api_secret())


def alpaca_data_feed() -> str:
    feed = (os.environ.get("ALPACA_DATA_FEED") or DEFAULT_FEED).strip().lower()
    return feed or DEFAULT_FEED


def alpaca_data_url() -> str:
    return (os.environ.get("ALPACA_DATA_URL") or DEFAULT_DATA_URL).rstrip("/")


def alpaca_sip_preferred() -> bool:
    """True when keys are set and feed is sip (default when unset)."""
    return alpaca_credentials_configured() and alpaca_data_feed() == "sip"


def _headers() -> dict[str, str]:
    key = alpaca_api_key()
    secret = alpaca_api_secret()
    if not key or not secret:
        return {}
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
    }


def bars_to_price_dicts(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize Alpaca bars into Price-compatible dicts (same shape as Tiingo)."""
    prices: list[dict[str, Any]] = []
    for bar in bars:
        raw_time = bar.get("t") or bar.get("timestamp") or ""
        if not raw_time:
            continue
        time_str = str(raw_time)
        if "T" not in time_str:
            time_str = f"{time_str[:10]}T00:00:00Z"
        elif not time_str.endswith("Z") and "+" not in time_str:
            time_str = time_str.replace(" ", "T")
            if not time_str.endswith("Z"):
                time_str = time_str + "Z"

        open_px = bar.get("o", bar.get("open"))
        close_px = bar.get("c", bar.get("close"))
        high_px = bar.get("h", bar.get("high"))
        low_px = bar.get("l", bar.get("low"))
        volume = bar.get("v", bar.get("volume", 0))
        if open_px is None or close_px is None or high_px is None or low_px is None:
            continue
        prices.append({
            "open": float(open_px),
            "close": float(close_px),
            "high": float(high_px),
            "low": float(low_px),
            "volume": int(volume or 0),
            "time": time_str,
        })
    return prices


def get_bars(
    ticker: str,
    start_date: str,
    end_date: str,
    timeframe: str = "1Day",
    feed: str | None = None,
    timeout: int = 30,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """Fetch stock bars from Alpaca Data API with pagination.

    GET /v2/stocks/{symbol}/bars
    Returns list of raw Alpaca bar dicts (t/o/h/l/c/v), or [] on failure.
    Never logs secret values.
    """
    if not alpaca_credentials_configured():
        return []

    symbol = ticker.upper().strip()
    base = alpaca_data_url()
    use_feed = (feed or alpaca_data_feed()).strip().lower() or DEFAULT_FEED
    url = f"{base}/v2/stocks/{symbol}/bars"
    headers = _headers()

    all_bars: list[dict[str, Any]] = []
    page_token: str | None = None

    try:
        while True:
            params: dict[str, Any] = {
                "timeframe": timeframe,
                "start": start_date,
                "end": end_date,
                "adjustment": "raw",
                "feed": use_feed,
                "limit": limit,
                "sort": "asc",
            }
            if page_token:
                params["page_token"] = page_token

            resp = requests.get(url, headers=headers, params=params, timeout=timeout)
            if resp.status_code != 200:
                # Do not log response bodies that might echo auth; status + ticker only
                print(f"[alpaca_data] bars HTTP {resp.status_code} for {symbol} feed={use_feed}")
                return []

            payload = resp.json()
            bars = payload.get("bars") or []
            if isinstance(bars, list):
                all_bars.extend(bars)

            page_token = payload.get("next_page_token") or None
            if not page_token:
                break

        return all_bars
    except Exception as e:
        print(f"[alpaca_data] bars error for {symbol}: {type(e).__name__}: {e}")
        return []


def get_prices(
    ticker: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """Fetch daily bars and normalize to Price dict shape (time/open/high/low/close/volume)."""
    bars = get_bars(ticker, start_date, end_date, timeframe="1Day")
    return bars_to_price_dicts(bars)


def get_latest_trade(ticker: str, feed: str | None = None, timeout: int = 15) -> dict[str, Any] | None:
    """Optional helper: latest trade for symbol. Returns raw dict or None."""
    if not alpaca_credentials_configured():
        return None
    symbol = ticker.upper().strip()
    use_feed = (feed or alpaca_data_feed()).strip().lower() or DEFAULT_FEED
    url = f"{alpaca_data_url()}/v2/stocks/{symbol}/trades/latest"
    try:
        resp = requests.get(
            url,
            headers=_headers(),
            params={"feed": use_feed},
            timeout=timeout,
        )
        if resp.status_code != 200:
            print(f"[alpaca_data] latest trade HTTP {resp.status_code} for {symbol}")
            return None
        data = resp.json()
        return data.get("trade") if isinstance(data, dict) else None
    except Exception as e:
        print(f"[alpaca_data] latest trade error for {symbol}: {type(e).__name__}: {e}")
        return None


def get_latest_quote(ticker: str, feed: str | None = None, timeout: int = 15) -> dict[str, Any] | None:
    """Optional helper: latest quote for symbol. Returns raw dict or None."""
    if not alpaca_credentials_configured():
        return None
    symbol = ticker.upper().strip()
    use_feed = (feed or alpaca_data_feed()).strip().lower() or DEFAULT_FEED
    url = f"{alpaca_data_url()}/v2/stocks/{symbol}/quotes/latest"
    try:
        resp = requests.get(
            url,
            headers=_headers(),
            params={"feed": use_feed},
            timeout=timeout,
        )
        if resp.status_code != 200:
            print(f"[alpaca_data] latest quote HTTP {resp.status_code} for {symbol}")
            return None
        data = resp.json()
        return data.get("quote") if isinstance(data, dict) else None
    except Exception as e:
        print(f"[alpaca_data] latest quote error for {symbol}: {type(e).__name__}: {e}")
        return None
