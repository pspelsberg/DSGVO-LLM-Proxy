from fastapi import HTTPException
from typing import Optional
from src.pii_engine import PIIEngine
from src.gateway import Gateway
from src.services.config_service import ConfigService

# In-memory singletons
pii_engine: Optional[PIIEngine] = None
gateway: Optional[Gateway] = None
config_service: Optional[ConfigService] = None

def get_pii_engine() -> PIIEngine:
    """Dependency to get the PII Engine singleton."""
    if pii_engine is None:
        raise HTTPException(status_code=503, detail="PII Engine not initialized")
    return pii_engine

def get_gateway() -> Gateway:
    """Dependency to get the Gateway singleton."""
    if gateway is None:
        raise HTTPException(status_code=503, detail="Gateway not initialized")
    return gateway

def get_config_service() -> ConfigService:
    """Dependency to get the Config Service singleton."""
    if config_service is None:
        raise HTTPException(status_code=503, detail="Config Service not initialized")
    return config_service
