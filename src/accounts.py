"""
Account routing for multi-account Alpaca setup.

Two accounts:
  - "swing" (Primary):     ALPACA_API_KEY / ALPACA_API_SECRET — multi-day holds
  - "day"   (DayTrading):  ALPACA_DAY_API_KEY / ALPACA_DAY_API_SECRET — intraday, flattens EOD

Credentials are selected based on trading mode. All API helpers accept
an optional `mode` parameter; if omitted, the current trading mode
(from trading_mode.json) determines which account to use.

If only the primary account is configured, both modes share it (backward compatible).
"""

import os
from dataclasses import dataclass


PAPER_ALPACA_BASE_URL = "https://paper-api.alpaca.markets/v2"
LIVE_ALPACA_BASE_URL = "https://api.alpaca.markets/v2"


def resolve_alpaca_base_url() -> str:
    """Resolve Alpaca REST base URL from env (defaults to paper for safety).

    Priority:
      1. ALPACA_BASE_URL if set explicitly
      2. ALPACA_TRADING_MODE=live|paper
      3. paper endpoint
    """
    explicit = os.environ.get("ALPACA_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")

    mode = os.environ.get("ALPACA_TRADING_MODE", "paper").strip().lower()
    if mode == "live":
        return LIVE_ALPACA_BASE_URL
    return PAPER_ALPACA_BASE_URL


@dataclass
class AlpacaAccount:
    """Credentials + metadata for a single Alpaca account."""
    name: str
    account_id: str
    api_key: str
    api_secret: str
    base_url: str = PAPER_ALPACA_BASE_URL

    @property
    def headers(self) -> dict:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Content-Type": "application/json",
        }


# Account registry — loaded from env vars
_ACCOUNTS: dict[str, AlpacaAccount] = {}


def _load_accounts() -> None:
    """Load account credentials from environment. Called once on import."""
    global _ACCOUNTS

    # Swing account (primary — ALPACA_API_KEY / ALPACA_API_SECRET)
    swing_key = os.environ.get("ALPACA_API_KEY", "")
    swing_secret = os.environ.get("ALPACA_API_SECRET", "")
    base_url = resolve_alpaca_base_url()

    if swing_key and swing_secret:
        _ACCOUNTS["swing"] = AlpacaAccount(
            name="Swing",
            account_id=os.environ.get("ALPACA_ACCOUNT_ID", "unknown"),
            api_key=swing_key,
            api_secret=swing_secret,
            base_url=base_url,
        )

    # Day trading account (optional — ALPACA_DAY_API_KEY / ALPACA_DAY_API_SECRET)
    day_key = os.environ.get("ALPACA_DAY_API_KEY", "")
    day_secret = os.environ.get("ALPACA_DAY_API_SECRET", "")
    if day_key and day_secret:
        _ACCOUNTS["day"] = AlpacaAccount(
            name="DayTrading",
            account_id=os.environ.get("ALPACA_DAY_ACCOUNT_ID", "unknown"),
            api_key=day_key,
            api_secret=day_secret,
            base_url=base_url,
        )


def get_account_for_mode(mode: str = None) -> AlpacaAccount:
    """
    Get the correct Alpaca account for the given trading mode.

    Args:
        mode: "swing" or "day". If None, resolves from trading_mode.json.

    Returns:
        AlpacaAccount with credentials for the appropriate account.

    Raises:
        ValueError if the account for the given mode is not configured.
    """
    if not _ACCOUNTS:
        _load_accounts()
    if not _ACCOUNTS:
        # Env may have been populated after first import — force reload
        _load_accounts()

    if mode is None:
        from src.config import resolve_mode
        mode = resolve_mode()
        if mode == "auto":
            mode = "swing"  # safe default

    mode = mode.lower()

    # HIT (Wave F) has no dedicated Alpaca account — it trades intraday like
    # "day", so prefer the day account, falling back to swing.
    if mode == "hit":
        if "day" in _ACCOUNTS:
            return _ACCOUNTS["day"]
        if "swing" in _ACCOUNTS:
            return _ACCOUNTS["swing"]

    if mode in _ACCOUNTS:
        return _ACCOUNTS[mode]

    # Prefer swing when day is missing (common: only ALPACA_API_KEY set)
    if mode == "day" and "swing" in _ACCOUNTS:
        return _ACCOUNTS["swing"]

    # Fallback: if swing account isn't configured yet, use day account
    if mode == "swing" and "day" in _ACCOUNTS:
        return _ACCOUNTS["day"]

    if "swing" in _ACCOUNTS:
        return _ACCOUNTS["swing"]

    if "day" in _ACCOUNTS:
        return _ACCOUNTS["day"]

    raise ValueError(
        f"No Alpaca account configured for mode '{mode}'. "
        "Check ALPACA_API_KEY / ALPACA_SWING_API_KEY in .env"
    )


def get_all_accounts() -> dict[str, AlpacaAccount]:
    """Return all configured accounts."""
    if not _ACCOUNTS:
        _load_accounts()
    return dict(_ACCOUNTS)


# Auto-load on import
_load_accounts()
