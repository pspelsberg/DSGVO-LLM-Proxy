import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from src.config import (
    BASE_DIR, DEFAULT_THRESHOLD, DEFAULT_ACTIVE_ENTITIES, PROVIDERS,
    DEFAULT_WHITELIST, DEFAULT_BLACKLIST, DEFAULT_ENTITY_STRATEGIES,
    DEFAULT_API_KEYS, DEFAULT_SAFE_LOGGING_MODE,
    DEFAULT_CHUNKING_ENABLED, DEFAULT_CHUNK_SIZE,
    DEFAULT_SLIDING_WINDOW_ENABLED, DEFAULT_MAX_CONTEXT_TOKENS,
    DEFAULT_GLOBAL_TOKEN_LIMIT
)
from src.utils.crypto import encrypt_key, decrypt_key
from src.models import GatewayConfig

logger = logging.getLogger(__name__)

class ConfigService:
    def __init__(self, config_file: Optional[Path] = None):
        self.config_file = config_file or (BASE_DIR / "gateway_config.json")
        self._config: Dict[str, Any] = {}
        self._dirty: bool = True  # Start dirty to force initial load

    def get(self) -> Dict[str, Any]:
        """Get config from cache, loading from disk if dirty."""
        if self._dirty:
            self._config = self._load_config()
            self._dirty = False
        return self._config

    def update(self, new_config: Dict[str, Any]) -> None:
        """Update cache, save to disk, and mark dirty to ensure reload consistency."""
        self._save_config(new_config)
        self._config = new_config
        self._dirty = False

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from disk with defaults and decryption."""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    config = json.load(f)
                    
                    # Migrate or ensure fields exist
                    config.setdefault("active_entities", DEFAULT_ACTIVE_ENTITIES)
                    config.setdefault("threshold", DEFAULT_THRESHOLD)
                    config.setdefault("mock_mode", True)
                    config.setdefault("provider", "mock")
                    config.setdefault("model_name", "gpt-4o")
                    config.setdefault("whitelist", DEFAULT_WHITELIST)
                    config.setdefault("blacklist", DEFAULT_BLACKLIST)
                    config.setdefault("entity_strategies", DEFAULT_ENTITY_STRATEGIES)
                    config.setdefault("api_keys", DEFAULT_API_KEYS.copy())
                    config.setdefault("safe_logging_mode", DEFAULT_SAFE_LOGGING_MODE)
                    config.setdefault("chunking_enabled", DEFAULT_CHUNKING_ENABLED)
                    config.setdefault("chunk_size", DEFAULT_CHUNK_SIZE)
                    config.setdefault("sliding_window_enabled", DEFAULT_SLIDING_WINDOW_ENABLED)
                    config.setdefault("max_context_tokens", DEFAULT_MAX_CONTEXT_TOKENS)
                    config.setdefault("global_token_limit", DEFAULT_GLOBAL_TOKEN_LIMIT)
                    config.setdefault("agents", [])

                    # Decrypt keys
                    decrypted_keys = {}
                    for provider, key in config.get("api_keys", {}).items():
                        if key:
                            decrypted = decrypt_key(key)
                            if decrypted:
                                decrypted_keys[provider] = decrypted
                            else:
                                logger.error(f"Failed to decrypt key for {provider}. Setting to empty.")
                                decrypted_keys[provider] = ""
                        else:
                            decrypted_keys[provider] = ""
                    config["api_keys"] = decrypted_keys

                    # Decrypt agent keys
                    decrypted_agents = []
                    for agent in config.get("agents", []):
                        agent_copy = dict(agent)
                        if agent_copy.get("api_key"):
                            decrypted = decrypt_key(agent_copy["api_key"])
                            if decrypted:
                                agent_copy["api_key"] = decrypted
                            else:
                                logger.error(f"Failed to decrypt api_key for agent {agent_copy.get('id')}. Setting to empty.")
                                agent_copy["api_key"] = ""
                        else:
                            agent_copy["api_key"] = ""
                        decrypted_agents.append(agent_copy)
                    config["agents"] = decrypted_agents

                    return config
            except Exception as e:
                logger.error(f"Failed to read config file: {str(e)}")

        # Default config if file doesn't exist or read fails
        return {
            "active_entities": DEFAULT_ACTIVE_ENTITIES.copy(),
            "threshold": DEFAULT_THRESHOLD,
            "mock_mode": True,
            "provider": "mock",
            "model_name": "gpt-4o",
            "whitelist": DEFAULT_WHITELIST.copy(),
            "blacklist": DEFAULT_BLACKLIST.copy(),
            "entity_strategies": DEFAULT_ENTITY_STRATEGIES.copy(),
            "api_keys": DEFAULT_API_KEYS.copy(),
            "safe_logging_mode": DEFAULT_SAFE_LOGGING_MODE,
            "chunking_enabled": DEFAULT_CHUNKING_ENABLED,
            "chunk_size": DEFAULT_CHUNK_SIZE,
            "sliding_window_enabled": DEFAULT_SLIDING_WINDOW_ENABLED,
            "max_context_tokens": DEFAULT_MAX_CONTEXT_TOKENS,
            "global_token_limit": DEFAULT_GLOBAL_TOKEN_LIMIT,
            "agents": []
        }

    def _save_config(self, config: Dict[str, Any]) -> None:
        """Encrypt keys and save to disk."""
        try:
            config_to_save = dict(config)
            # Encrypt keys
            encrypted_keys = {}
            for provider, key in config_to_save.get("api_keys", {}).items():
                if key:
                    encrypted_keys[provider] = encrypt_key(key)
                else:
                    encrypted_keys[provider] = ""
            config_to_save["api_keys"] = encrypted_keys

            # Encrypt agent keys
            encrypted_agents = []
            for agent in config.get("agents", []):
                agent_copy = dict(agent)
                if agent_copy.get("api_key"):
                    agent_copy["api_key"] = encrypt_key(agent_copy["api_key"])
                else:
                    agent_copy["api_key"] = ""
                encrypted_agents.append(agent_copy)
            config_to_save["agents"] = encrypted_agents

            with open(self.config_file, "w") as f:
                json.dump(config_to_save, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save config file: {str(e)}")

    def get_masked(self) -> GatewayConfig:
        """Returns GatewayConfig with masked api keys."""
        config = self.get()
        all_entities = [
            "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "DE_PHONE_NUMBER", "IP_ADDRESS", 
            "CREDIT_CARD", "CRYPTO", "IBAN_CODE", "DE_TAX_ID", 
            "DE_STEUERNR", "DE_LICENSE_PLATE", "DE_ID_CARD", "LOCATION", "STREET_ADDRESS"
        ]
        masked_keys = {prov: ("********" if key else "") for prov, key in config.get("api_keys", {}).items()}
        
        masked_agents = []
        for agent in config.get("agents", []):
            agent_copy = dict(agent)
            agent_copy["api_key"] = "********" if agent_copy.get("api_key") else ""
            masked_agents.append(agent_copy)

        return GatewayConfig(
            active_entities=config["active_entities"],
            threshold=config["threshold"],
            mock_mode=config["mock_mode"],
            provider=config["provider"],
            model_name=config["model_name"],
            available_providers=list(PROVIDERS.keys()),
            all_available_entities=all_entities,
            whitelist=config.get("whitelist", []),
            blacklist=config.get("blacklist", []),
            entity_strategies=config.get("entity_strategies", {}),
            api_keys=masked_keys,
            safe_logging_mode=config.get("safe_logging_mode", False),
            chunking_enabled=config.get("chunking_enabled", True),
            chunk_size=config.get("chunk_size", 4000),
            sliding_window_enabled=config.get("sliding_window_enabled", True),
            max_context_tokens=config.get("max_context_tokens", 12000),
            global_token_limit=config.get("global_token_limit", None),
            agents=masked_agents
        )
