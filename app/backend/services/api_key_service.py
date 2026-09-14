import logging
import os
from sqlalchemy.orm import Session
from typing import Dict, Optional
from app.backend.repositories.api_key_repository import ApiKeyRepository

logger = logging.getLogger(__name__)

# Env vars synced into the UI/api_keys DB store. Alpaca stays server-env only.
_ENV_SYNC_PROVIDERS = (
    ("OPENROUTER_API_KEY", "OPENROUTER_API_KEY", "Synced from OPENROUTER_API_KEY environment"),
    ("TIINGO_API_KEY", "TIINGO_API_KEY", "Synced from TIINGO_API_KEY environment"),
)


class ApiKeyService:
    """Simple service to load API keys for requests"""
    
    def __init__(self, db: Session):
        self.repository = ApiKeyRepository(db)
    
    def get_api_keys_dict(self) -> Dict[str, str]:
        """
        Load all active API keys from database and return as a dictionary
        suitable for injecting into requests
        """
        api_keys = self.repository.get_all_api_keys(include_inactive=False)
        return {key.provider: key.key_value for key in api_keys}
    
    def get_api_key(self, provider: str) -> Optional[str]:
        """Get a specific API key by provider"""
        api_key = self.repository.get_api_key_by_provider(provider)
        return api_key.key_value if api_key else None

    def sync_env_api_keys(self) -> int:
        """
        Upsert OPENROUTER_API_KEY and TIINGO_API_KEY from os.environ into the
        api_keys DB store when set. Does not sync Alpaca (paper trading keys
        remain server-env only and are never exposed via the UI store).
        Returns the number of providers synced. Never logs secret values.
        """
        synced = 0
        for env_name, provider, description in _ENV_SYNC_PROVIDERS:
            value = (os.environ.get(env_name) or "").strip()
            if not value:
                continue
            self.repository.create_or_update_api_key(
                provider=provider,
                key_value=value,
                description=description,
                is_active=True,
            )
            synced += 1
            logger.info("Synced %s from environment into api_keys store", provider)
        if synced == 0:
            logger.info("No OPENROUTER/TIINGO env keys to sync into api_keys store")
        return synced
