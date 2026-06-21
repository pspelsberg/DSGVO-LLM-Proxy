import asyncio
import logging
from typing import List
from fastapi import APIRouter, HTTPException
from src.models import AuditLogItem
from src.utils.logger import get_logs, clear_logs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/logs", tags=["logs"])

@router.get("", response_model=List[AuditLogItem])
async def get_audit_logs(limit: int = 50):
    """Retrieve transaction history logs from SQLite."""
    if limit < 1 or limit > 500:
        limit = min(max(limit, 1), 500)
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: get_logs(limit=limit))
    except Exception as e:
        logger.error(f"Failed to fetch logs: {str(e)}")
        raise HTTPException(status_code=500, detail="Database error")

@router.post("/clear")
async def clear_audit_logs():
    """Clear audit logs history."""
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, clear_logs)
        return {"status": "success", "message": "Audit logs cleared"}
    except Exception as e:
        logger.error(f"Failed to clear logs: {str(e)}")
        raise HTTPException(status_code=500, detail="Database error")
