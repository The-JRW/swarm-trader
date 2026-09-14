"""
Tiingo market-data client.

Used as the primary price source when TIINGO_API_KEY is set.
Falls back callers should keep yfinance/SEC paths intact.
Docs: https://www.tiingo.com/documentation/general/overview
"""

from __future__ import annotations

import os
from typing import Any

import requests

TIINGO_API_BASE = "https://api.tiingo.com"


def tiingo_api_key(explicit: str | None = None) -> str | None:
    """Return Tiingo API key from arg or TIINGO_API_KEY env."""
    key = (explicit or os.environ.get("TIINGO_API_KEY") or "").strip()
    return key or None


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Token {api_key}",
    }


def get_daily_prices(
    ticker: str,
    start_date: str,
    end_date: str,
    api_key: str | None = None,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    """Fetch EOD daily bars from Tiingo.

    Returns list of dicts with keys: date, open, high, low, close, volume
    (and adj* fields when present). Empty list on failure / missing key.
    """
    key = tiingo_api_key(api_key)
    if not key:
        return []

    url = f"{TIINGO_API_BASE}/tiingo/daily/{ticker.upper()}/prices"
    params = {
        "startDate": start_date,
        "endDate": end_date,
        "format": "json",
        "resampleFreq": "daily",
    }
    try:
        resp = requests.get(url, headers=_headers(key), params=params, timeout=timeout)
        if resp.status_code != 200:
            print(f"[tiingo] daily prices HTTP {resp.status_code} for {ticker}: {resp.text[:200]}")
            return []
        data = resp.json()
        if not isinstance(data, list):
            return []
        return data
    except Exception as e:
        print(f"[tiingo] daily prices error for {ticker}: {e}")
        return []


def get_iex_prices(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    api_key: str | None = None,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    """Fetch IEX intraday/historical prices from Tiingo (when available on plan).

    Returns raw Tiingo IEX price dicts, or [] on failure.
    """
    key = tiingo_api_key(api_key)
    if not key:
        return []

    url = f"{TIINGO_API_BASE}/iex/{ticker.upper()}/prices"
    params: dict[str, str] = {"format": "json", "resampleFreq": "1day"}
    if start_date:
        params["startDate"] = start_date
    if end_date:
        params["endDate"] = end_date
    try:
        resp = requests.get(url, headers=_headers(key), params=params, timeout=timeout)
        if resp.status_code != 200:
            print(f"[tiingo] IEX prices HTTP {resp.status_code} for {ticker}: {resp.text[:200]}")
            return []
        data = resp.json()
        if not isinstance(data, list):
            return []
        return data
    except Exception as e:
        print(f"[tiingo] IEX prices error for {ticker}: {e}")
        return []


def bars_to_price_dicts(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize Tiingo daily/IEX bars into Price-compatible dicts."""
    prices: list[dict[str, Any]] = []
    for bar in bars:
        # Daily endpoint uses "date"; IEX may use "date" or "timestamp"
        raw_time = bar.get("date") or bar.get("timestamp") or ""
        if not raw_time:
            continue
        # Normalize to ISO-ish date string expected by downstream Price model
        time_str = str(raw_time)
        if "T" not in time_str:
            time_str = f"{time_str[:10]}T00:00:00Z"
        elif not time_str.endswith("Z") and "+" not in time_str:
            time_str = time_str.replace(" ", "T")
            if not time_str.endswith("Z"):
                time_str = time_str + ("Z" if "T" in time_str else "")

        open_px = bar.get("open", bar.get("adjOpen"))
        close_px = bar.get("close", bar.get("adjClose"))
        high_px = bar.get("high", bar.get("adjHigh"))
        low_px = bar.get("low", bar.get("adjLow"))
        volume = bar.get("volume", bar.get("adjVolume", 0))
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


def get_prices(
    ticker: str,
    start_date: str,
    end_date: str,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Primary helper: prefer daily EOD, fall back to IEX daily resample."""
    bars = get_daily_prices(ticker, start_date, end_date, api_key=api_key)
    if not bars:
        bars = get_iex_prices(ticker, start_date=start_date, end_date=end_date, api_key=api_key)
    return bars_to_price_dicts(bars)
