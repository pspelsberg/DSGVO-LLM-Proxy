from fastapi import APIRouter, Depends, Request, HTTPException
from typing import Dict, Any
import logging
from src.dependencies import get_gateway, get_config_service
from src.gateway import Gateway
from src.services.config_service import ConfigService
from src.config import PROVIDERS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/chat/completions", tags=["proxy"])

@router.post("")
async def chat_completions_proxy(
    request: Request,
    gw: Gateway = Depends(get_gateway),
    config_service: ConfigService = Depends(get_config_service)
):
    """
    OpenAI-compatible Chat Completion proxy endpoint.
    Main endpoint for programmatic requests.
    """
    try:
        try:
            # Prevent DoS by limiting request body size to 5MB
            content_length = request.headers.get('content-length')
            if content_length and int(content_length) > 5 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Payload too large")
            # Parse body as JSON dict
            body = await request.json()
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
            
        # Load current configuration from the config service
        config = config_service.get()
        
        provider = config["provider"]
        model_name = config["model_name"]
        
        # Dynamic routing check from client model payload (e.g. for n8n)
        model_field = body.get("model", "")
        if "/" in model_field:
            parts = model_field.split("/", 1)
            req_provider = parts[0].lower()
            req_model = parts[1]
            
            # Check if provider is valid
            if req_provider in PROVIDERS:
                provider = req_provider
                model_name = req_model
                logger.info(f"Dynamic routing: Routing request to provider '{provider}' and model '{model_name}'")
        else:
            # Fallback detection from prefix if provider is not explicitly set with a slash
            model_field_lower = model_field.lower()
            if model_field_lower.startswith("gpt-"):
                provider = "openai"
                model_name = model_field
            elif model_field_lower.startswith("claude-"):
                provider = "anthropic"
                model_name = model_field
            elif model_field_lower.startswith("gemini-"):
                provider = "gemini"
                model_name = model_field
            elif model_field_lower.startswith("mistral-"):
                provider = "mistral"
                model_name = model_field
            elif model_field:
                model_name = model_field

        # Mock mode logic: if provider is 'mock', mock_mode is True. Otherwise read from config.
        mock_mode = config["mock_mode"] or (provider == "mock")
        
        # Auto-detect request language (default to 'de', check message content)
        # Simple check: search for common German words, otherwise default to English/German depending on config.
        lang = "de"
        messages = body.get("messages", [])
        if messages:
            last_msg = messages[-1].get("content", "")
            text_content = ""
            if isinstance(last_msg, str):
                text_content = last_msg
            elif isinstance(last_msg, list):
                for item in last_msg:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_val = item.get("text")
                        if isinstance(text_val, str):
                            text_content += " " + text_val
                        
            de_words = {"ich", "ist", "und", "der", "die", "das", "mit", "von", "zu", "für", "ein", "eine", "nicht"}
            words = set(text_content.lower().split())
            if text_content and not de_words.intersection(words):
                lang = "en"  # Fallback to English if no common German words detected
                
        response_payload, status_code = await gw.process_chat_completion(
            request_body=body,
            provider=provider,
            model_name=model_name,
            mock_mode=mock_mode,
            language=lang,
            api_keys=config.get("api_keys"),
            safe_logging_mode=config.get("safe_logging_mode", False),
            sliding_window_enabled=config.get("sliding_window_enabled", True),
            max_context_tokens=config.get("max_context_tokens", 12000),
            global_token_limit=config.get("global_token_limit", None),
            agent_id=getattr(request.state, "agent_id", None),
            agents_config=config.get("agents", [])
        )
        
        if status_code != 200:
            # Re-raise HTTP Exception for error responses
            if isinstance(response_payload, dict) and "error" in response_payload:
                raise HTTPException(
                    status_code=status_code, 
                    detail=response_payload["error"].get("message", "LLM Provider Error")
                )
            raise HTTPException(status_code=status_code, detail="LLM provider request failed")
            
        return response_payload
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in proxy completion: {str(e)}", exc_info=True)
        raise HTTPException(status_code=502, detail="Bad gateway: LLM proxy error")
