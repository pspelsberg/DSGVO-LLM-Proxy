import os
import logging
import hmac
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from fastapi import Request
from src.dependencies import get_config_service

logger = logging.getLogger(__name__)

class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. Check if path needs protection (only protect /api/... and /v1/...)
        path = request.url.path
        is_protected = (
            path == "/api" or path.startswith("/api/") or
            path == "/v1" or path.startswith("/v1/")
        )
        if not is_protected:
            return await call_next(request)

        # 2. Fail-closed: If no key is configured, block access to protected endpoints
        expected_key = os.getenv("GATEWAY_API_KEY")
        if not expected_key:
            logger.error(
                "GATEWAY_API_KEY is not set. Access to protected API endpoints is blocked. "
                "Set the GATEWAY_API_KEY environment variable to enable API access."
            )
            return JSONResponse(
                status_code=503,
                content={"detail": "Service unavailable: Security configuration missing. Set GATEWAY_API_KEY."}
            )
            
        # 3. Retrieve API key from request
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                api_key = auth_header[len("Bearer "):].strip()
                
        # 4. Verify API key
        matched_agent_id = None
        is_global_key = (
            expected_key is not None 
            and api_key is not None 
            and hmac.compare_digest(api_key, expected_key)
        )
        
        if not is_global_key and api_key is not None:
            # Check agent keys
            try:
                config = get_config_service().get()
                agents = config.get("agents", [])
                for agent in agents:
                    agent_key = agent.get("api_key")
                    if agent_key and hmac.compare_digest(api_key, agent_key):
                        matched_agent_id = agent.get("id")
                        break
            except Exception as e:
                logger.error(f"Error checking agent keys: {e}")
                
        if not is_global_key:
            if not matched_agent_id:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Unauthorized: Invalid or missing API key."}
                )
            # Restrict agents to proxy and RAG endpoints
            if not (path.startswith("/v1/chat/completions") or path.startswith("/api/rag/chat")):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Forbidden: Agents cannot access administrative endpoints."}
                )
            
        request.state.agent_id = matched_agent_id
        return await call_next(request)
