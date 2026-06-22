import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from src.config import BASE_DIR
from src.pii_engine import PIIEngine
from src.gateway import Gateway
from src.services.config_service import ConfigService
from src.utils.logger import init_db
from src.middleware.auth import APIKeyAuthMiddleware
import src.dependencies as deps

# Import Routers
from src.routers import (
    config_router,
    playground_router,
    proxy_router,
    logs_router,
    documents_router
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Config persistence path
CONFIG_FILE = BASE_DIR / "gateway_config.json"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events manager for FastAPI."""
    import httpx
    logger.info("Initializing SQLite database...")
    init_db()
    
    # Initialize ConfigService
    deps.config_service = ConfigService(CONFIG_FILE)
    config = deps.config_service.get()
    
    # Initialize PII Engine
    deps.pii_engine = PIIEngine()
    deps.pii_engine.set_config(
        active_entities=config["active_entities"],
        threshold=config["threshold"],
        whitelist=config.get("whitelist"),
        blacklist=config.get("blacklist"),
        entity_strategies=config.get("entity_strategies"),
        chunking_enabled=config.get("chunking_enabled", True),
        chunk_size=config.get("chunk_size", 4000)
    )
    
    # Initialize http_client
    http_client = httpx.AsyncClient(timeout=30.0)
    
    # Initialize Gateway Proxy
    deps.gateway = Gateway(deps.pii_engine, http_client)
    
    try:
        yield
    finally:
        await http_client.aclose()

app = FastAPI(
    title="DSGVO LLM Privacy Gateway",
    description="Ein sicheres Proxy-Gateway zum Erkennen und Maskieren von PII vor der Übertragung an LLMs.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration – restrict to configured origins (comma-separated via env)
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in ALLOWED_ORIGINS],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

# API Key Authentication Middleware – active when GATEWAY_API_KEY env var is set
app.add_middleware(APIKeyAuthMiddleware)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
    return response

# Simple IP-based Rate Limiting (100 requests per minute)
import time
from fastapi.responses import JSONResponse
request_counts = {}
last_prune_time = 0.0
MAX_IP_TRACKED = 2000

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    global last_prune_time
    client_ip = request.client.host if request.client else "unknown"
    current_time = time.time()
    
    # Periodic pruning of the dictionary to prevent memory exhaustion (every 5 minutes or if size > MAX_IP_TRACKED)
    if current_time - last_prune_time > 300 or len(request_counts) > MAX_IP_TRACKED:
        ips_to_delete = [
            ip for ip, times in request_counts.items()
            if not times or current_time - times[-1] >= 60
        ]
        for ip in ips_to_delete:
            request_counts.pop(ip, None)
        last_prune_time = current_time
    
    if client_ip not in request_counts:
        # Enforce hard limit to prevent memory exhaustion
        if len(request_counts) >= MAX_IP_TRACKED:
            return JSONResponse(status_code=429, content={"detail": "Too many requests - system overloaded"})
        request_counts[client_ip] = []
        
    # Clean up old requests
    request_counts[client_ip] = [t for t in request_counts[client_ip] if current_time - t < 60]
    
    if len(request_counts[client_ip]) >= 100:
        return JSONResponse(status_code=429, content={"detail": "Too many requests"})
        
    request_counts[client_ip].append(current_time)
    return await call_next(request)


# Register routers
app.include_router(playground_router.router)
app.include_router(config_router.router)
app.include_router(logs_router.router)
app.include_router(proxy_router.router)
app.include_router(documents_router.router)

# Serve Frontend
static_dir = BASE_DIR / "src" / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the SPA frontend, falling back to a placeholder if assets aren't built yet."""
    index_path = static_dir / "index.html"
    if not index_path.exists():
        return HTMLResponse(
            content="<h1>DSGVO Privacy Gateway Dashboard</h1><p>Frontend assets are being generated. Please refresh in a moment.</p>"
        )
    return FileResponse(str(index_path))
