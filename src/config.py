import os
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional

# Load environment variables from .env file
load_dotenv()

# Project Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "gateway_logs.db"))

# Server Config
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

# Default PII Settings
DEFAULT_THRESHOLD = float(os.getenv("DEFAULT_THRESHOLD", "0.35"))
SUPPORTED_LANGUAGES = ["de", "en"]

# LLM Providers Configuration
PROVIDERS = {
    "mock": {
        "name": "Mock LLM (Demo)",
        "url": None,
        "api_key": None
    },
    "openai": {
        "name": "OpenAI (GPT)",
        "url": "https://api.openai.com/v1/chat/completions",
        "api_key_env": "OPENAI_API_KEY"
    },
    "anthropic": {
        "name": "Anthropic (Claude)",
        "url": "https://api.anthropic.com/v1/messages",
        "api_key_env": "ANTHROPIC_API_KEY"
    },
    "mistral": {
        "name": "Mistral AI",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "api_key_env": "MISTRAL_API_KEY"
    },
    "gemini": {
        "name": "Google Gemini",
        "url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "api_key_env": "GEMINI_API_KEY"
    },
    "openrouter": {
        "name": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "api_key_env": "OPENROUTER_API_KEY"
    }
}

# Default Active PII Entities to anonymize
DEFAULT_ACTIVE_ENTITIES = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "DE_PHONE_NUMBER",
    "IP_ADDRESS",
    "CREDIT_CARD",
    "CRYPTO",
    "IBAN_CODE",
    "DE_TAX_ID",
    "DE_STEUERNR",
    "DE_LICENSE_PLATE",
    "DE_ID_CARD",
    "LOCATION",
    "STREET_ADDRESS"
]

# Default V2 Settings
DEFAULT_WHITELIST = []
DEFAULT_BLACKLIST = []
DEFAULT_ENTITY_STRATEGIES = {ent: "placeholder" for ent in DEFAULT_ACTIVE_ENTITIES}
DEFAULT_API_KEYS = {"openai": "", "anthropic": "", "mistral": "", "gemini": "", "openrouter": ""}
DEFAULT_SAFE_LOGGING_MODE = False
DEFAULT_CHUNKING_ENABLED = True
DEFAULT_CHUNK_SIZE = 4000
DEFAULT_SLIDING_WINDOW_ENABLED = True
DEFAULT_MAX_CONTEXT_TOKENS = 12000

limit_env = os.getenv("GLOBAL_TOKEN_LIMIT")
DEFAULT_GLOBAL_TOKEN_LIMIT = int(limit_env) if limit_env and limit_env.isdigit() else None

def get_api_key(provider: str, config_keys: Optional[dict] = None) -> str:
    """Helper to retrieve provider API key from configured keys (UI) or env."""
    provider_lower = provider.lower()
    if config_keys and provider_lower in config_keys and config_keys[provider_lower]:
        return config_keys[provider_lower]
        
    provider_info = PROVIDERS.get(provider_lower)
    if not provider_info or "api_key_env" not in provider_info:
        return ""
    return os.getenv(provider_info["api_key_env"], "")
