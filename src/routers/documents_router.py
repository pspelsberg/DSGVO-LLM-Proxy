import asyncio
import logging
import re
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from src.models import RAGChatRequest
from src.dependencies import get_pii_engine, get_gateway, get_config_service
from src.pii_engine import PIIEngine
from src.gateway import Gateway
from src.services.config_service import ConfigService
from src.utils.logger import (
    save_document, get_documents, delete_document_by_id, get_anonymized_chunks
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])

@router.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    engine: PIIEngine = Depends(get_pii_engine)
):
    """Upload a document, segment it into chunks, anonymize it, and save it to RAG."""
    MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
    chunk_size = 1024 * 1024  # 1 MB
    content = bytearray()
    try:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > MAX_UPLOAD_SIZE:
                raise HTTPException(status_code=413, detail="File too large. Maximum size is 10 MB.")
        text = content.decode("utf-8")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Only UTF-8 encoded text files are supported currently")
        
    if not text.strip():
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
        
    # Segment text into overlapping chunks
    CHUNK_SIZE = 1000
    OVERLAP = 100
    
    # Generate unique prefix for this upload to avoid placeholder collisions in RAG context
    upload_prefix = f"doc_{uuid.uuid4().hex[:6]}_"
    type_counts = {}
    
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunk_text = text[start:end]
        
        # Analyze and anonymize the chunk
        entities = await asyncio.to_thread(engine.analyze, chunk_text)
        anon_text, mapping = engine.anonymize(
            chunk_text, 
            entities, 
            type_counts=type_counts, 
            placeholder_prefix=upload_prefix
        )
        
        chunks.append({
            "original_text": chunk_text,
            "anonymized_text": anon_text,
            "mapping": mapping
        })
        
        step = CHUNK_SIZE - OVERLAP
        start += max(step, 1)
        if end == len(text):
            break
            
    raw_filename = file.filename or "unknown_file"
    # Prevent path traversal and clean special characters
    safe_name = Path(raw_filename).name
    safe_name = re.sub(r"[^\w\-_.]", "_", safe_name)
    if len(safe_name) > 100:
        parts = safe_name.rsplit(".", 1)
        if len(parts) == 2:
            ext = parts[1]
            base = parts[0][:95 - len(ext)]
            safe_name = f"{base}.{ext}"
        else:
            safe_name = safe_name[:100]
    filename = safe_name
    try:
        loop = asyncio.get_running_loop()
        doc_id = await loop.run_in_executor(None, lambda: save_document(filename, chunks))
        return {"status": "success", "document_id": doc_id, "chunks_count": len(chunks)}
    except Exception as e:
        logger.error(f"Failed to save document: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save document to database")

@router.get("/api/documents")
async def list_documents():
    """List all uploaded documents in the RAG system."""
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, get_documents)
    except Exception as e:
        logger.error(f"Failed to list documents: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve documents")

@router.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: int):
    """Delete an uploaded document by ID."""
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: delete_document_by_id(doc_id))
        return {"status": "success", "message": "Document deleted"}
    except Exception as e:
        logger.error(f"Failed to delete document {doc_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete document")

@router.post("/api/rag/chat")
async def rag_chat(
    req: RAGChatRequest,
    request: Request,
    engine: PIIEngine = Depends(get_pii_engine),
    gw: Gateway = Depends(get_gateway),
    config_service: ConfigService = Depends(get_config_service)
):
    """
    DSGVO-compliant Retrieval-Augmented Generation (RAG).
    Retrieves anonymized context, queries the LLM, and deanonymizes the response.
    """
    # 1. Retrieve anonymized chunks (async-safe)
    loop = asyncio.get_running_loop()
    chunks = await loop.run_in_executor(None, lambda: get_anonymized_chunks(document_ids=req.document_ids))
    if not chunks:
        raise HTTPException(status_code=400, detail="No documents uploaded yet or no documents match the specified filter.")
        
    # 2. Simple keyword-based relevance matching (TF-IDF/Frequency simulation)
    # First, anonymize the user's question to maintain privacy in the LLM prompt
    question_entities = await asyncio.to_thread(engine.analyze, req.question, language=req.language)
    anon_question, question_mapping = engine.anonymize(req.question, question_entities)
    
    # Keyword matching against original text to ensure PII searches work correctly
    query_words = [w.lower() for w in req.question.split() if len(w) > 3]
    if not query_words:
        query_words = [w.lower() for w in req.question.split()]
        
    scored_chunks = []
    for chunk in chunks:
        score = 0
        # Fallback to anonymized if original is missing or falsy/None
        orig_text_lower = (chunk.get("original_text") or chunk["anonymized_text"]).lower()
        for word in query_words:
            if word in orig_text_lower:
                score += 1
        scored_chunks.append((score, chunk))
        
    # Sort by score descending, pick top 3
    scored_chunks = sorted(scored_chunks, key=lambda x: x[0], reverse=True)
    top_chunks = [item[1] for item in scored_chunks if item[0] > 0][:3]
    
    # Fallback to first 3 chunks if no keywords matched
    if not top_chunks:
        top_chunks = chunks[:3]
        
    # 3. Assemble combined mapping and prompt
    combined_mapping = dict(question_mapping)
    context_parts = []
    
    for idx, chunk in enumerate(top_chunks):
        context_parts.append(f"Dokument-Segment {idx+1}:\n{chunk['anonymized_text']}")
        # Merge mappings
        for k, v in chunk["mapping"].items():
            combined_mapping[k] = v
            
    context_str = "\n\n".join(context_parts)
    
    # 4. Construct prompts and proxy to LLM via Gateway
    system_prompt = (
        "Du bist ein sicheres Assistenz-Modell. Beantworte die Frage des Nutzers "
        "ausschließlich basierend auf dem bereitgestellten Dokumenten-Kontext. "
        "Falls die Antwort im Kontext nicht enthalten ist, antworte, dass du es nicht weißt. "
        "Antworte in derselben Sprache wie die Frage."
    )
    user_prompt = f"Hier ist der relevante Dokumenten-Kontext:\n<context>\n{context_str}\n</context>\n\nFrage: {anon_question}"
    
    config = config_service.get()
    body = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3
    }
    
    response_payload, status_code = await gw.process_chat_completion(
        request_body=body,
        provider=config["provider"],
        model_name=config["model_name"],
        mock_mode=config["mock_mode"],
        language=req.language,
        api_keys=config.get("api_keys"),
        safe_logging_mode=config.get("safe_logging_mode", False),
        global_token_limit=config.get("global_token_limit", None),
        agent_id=getattr(request.state, "agent_id", None),
        agents_config=config.get("agents", [])
    )
    
    if status_code != 200:
        if isinstance(response_payload, dict) and "error" in response_payload:
            raise HTTPException(
                status_code=status_code, 
                detail=response_payload["error"].get("message", "LLM Provider Error")
            )
        raise HTTPException(status_code=status_code, detail=str(response_payload))
        
    try:
        val = response_payload["choices"][0]["message"]["content"]
        llm_response_text = val if val is not None else ""
    except (KeyError, IndexError, TypeError):
        llm_response_text = ""
    
    # 5. Deanonymize response using the combined mapping
    deanonymized_response = engine.deanonymize(llm_response_text, combined_mapping)
    
    return {
        "anonymized_question": anon_question,
        "context_chunks_used": len(top_chunks),
        "llm_response": llm_response_text,
        "response": deanonymized_response
    }
