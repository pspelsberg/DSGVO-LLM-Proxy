import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from src.models import AnonymizeRequest, PIIEntity
from src.dependencies import get_pii_engine
from src.pii_engine import PIIEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analyze", tags=["playground"])

@router.post("", response_model=List[PIIEntity])
async def analyze_text(req: AnonymizeRequest, engine: PIIEngine = Depends(get_pii_engine)):
    """
    Endpoint for live highlight checking in the UI.
    Analyzes prompt text and returns list of detected PII details.
    """
    try:
        import asyncio
        return await asyncio.to_thread(engine.analyze, req.text, language=req.language)
    except Exception as e:
        logger.error(f"Error during PII analysis: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during analysis")
