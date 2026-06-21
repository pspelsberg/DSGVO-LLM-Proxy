from fastapi import APIRouter, Depends
from src.models import GatewayConfig, ConfigUpdate
from src.dependencies import get_config_service, get_pii_engine
from src.services.config_service import ConfigService
from src.pii_engine import PIIEngine

router = APIRouter(prefix="/api/config", tags=["config"])

@router.get("", response_model=GatewayConfig)
async def get_config(config_service: ConfigService = Depends(get_config_service)):
    """Get the current configuration of the DSGVO Privacy Gateway."""
    return config_service.get_masked()

@router.post("")
async def update_config(
    update: ConfigUpdate,
    config_service: ConfigService = Depends(get_config_service),
    engine: PIIEngine = Depends(get_pii_engine)
):
    """Update gateway configuration and save to persistence."""
    # Load existing config to resolve masked keys
    existing_config = config_service.get()
    existing_keys = existing_config.get("api_keys", {})
    existing_agents = {a.get("id"): a.get("api_key", "") for a in existing_config.get("agents", [])}
    
    new_keys = {}
    for provider in ["openai", "anthropic", "mistral", "gemini", "openrouter"]:
        incoming_key = update.api_keys.get(provider, "")
        if incoming_key == "********":
            new_keys[provider] = existing_keys.get(provider, "")
        else:
            new_keys[provider] = incoming_key

    resolved_agents = []
    if update.agents:
        for agent in update.agents:
            agent_dict = agent.model_dump()
            if agent_dict.get("api_key") == "********":
                agent_dict["api_key"] = existing_agents.get(agent_dict.get("id"), "")
            resolved_agents.append(agent_dict)

    config = {
        "active_entities": update.active_entities,
        "threshold": update.threshold,
        "mock_mode": update.mock_mode,
        "provider": update.provider,
        "model_name": update.model_name or "gpt-4o",
        "whitelist": update.whitelist,
        "blacklist": update.blacklist,
        "entity_strategies": update.entity_strategies,
        "api_keys": new_keys,
        "safe_logging_mode": update.safe_logging_mode,
        "chunking_enabled": update.chunking_enabled,
        "chunk_size": update.chunk_size,
        "sliding_window_enabled": update.sliding_window_enabled,
        "max_context_tokens": update.max_context_tokens,
        "agents": resolved_agents
    }
    
    # Save to file via config_service
    config_service.update(config)
    
    # Apply to in-memory Presidio engine
    engine.set_config(
        active_entities=update.active_entities,
        threshold=update.threshold,
        whitelist=update.whitelist,
        blacklist=update.blacklist,
        entity_strategies=update.entity_strategies,
        chunking_enabled=update.chunking_enabled,
        chunk_size=update.chunk_size
    )
    
    return {"status": "success", "message": "Configuration updated successfully"}
