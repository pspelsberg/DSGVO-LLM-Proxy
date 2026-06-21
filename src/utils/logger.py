import sqlite3
import json
from datetime import datetime
from src.config import DB_PATH
from typing import List, Dict, Any, Optional
from src.utils.crypto import encrypt_key, decrypt_key

def init_db():
    """Initialize the SQLite database and create the audit log table."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                provider TEXT NOT NULL,
                model_name TEXT,
                original_prompt TEXT NOT NULL,
                anonymized_prompt TEXT NOT NULL,
                llm_response TEXT NOT NULL,
                deanonymized_response TEXT NOT NULL,
                entities_masked_count INTEGER NOT NULL,
                entities_details TEXT NOT NULL,
                latency_ms INTEGER NOT NULL,
                privacy_score REAL NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                uploaded_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER,
                chunk_index INTEGER,
                original_text TEXT NOT NULL,
                anonymized_text TEXT NOT NULL,
                mapping_json TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES documents(id)
            )
        """)
        conn.commit()
    finally:
        conn.close()

def log_request(
    provider: str,
    model_name: str,
    original_prompt: str,
    anonymized_prompt: str,
    llm_response: str,
    deanonymized_response: str,
    entities_masked_count: int,
    entities_details: List[Dict[str, Any]],
    latency_ms: int,
    safe_logging_mode: bool = False
) -> int:
    """Save an execution log entry to the SQLite database."""
    # Calculate privacy score (simple metric: percentage of characters masked)
    orig_len = len(original_prompt)
    if orig_len > 0:
        masked_chars = sum(len(e.get("text", "")) for e in entities_details)
        privacy_score = min(1.0, masked_chars / orig_len)
    else:
        privacy_score = 0.0

    # Apply Safe-Logging Redactions or Encryption
    if safe_logging_mode:
        original_prompt = "[REDACTED FOR COMPLIANCE]"
        anonymized_prompt = "[REDACTED FOR COMPLIANCE]"
        llm_response = "[REDACTED FOR COMPLIANCE]"
        deanonymized_response = "[REDACTED FOR COMPLIANCE]"
        entities_details = [
            {**e, "text": "[REDACTED]"} for e in entities_details
        ]
    else:
        # Encrypt sensitive fields
        original_prompt = encrypt_key(original_prompt)
        anonymized_prompt = encrypt_key(anonymized_prompt)
        llm_response = encrypt_key(llm_response)
        deanonymized_response = encrypt_key(deanonymized_response)
        entities_details = [
            {**e, "text": encrypt_key(e.get("text", ""))} for e in entities_details
        ]

    timestamp = datetime.now().isoformat()
    entities_json = json.dumps(entities_details)

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO audit_logs (
                timestamp, provider, model_name, original_prompt, 
                anonymized_prompt, llm_response, deanonymized_response, 
                entities_masked_count, entities_details, latency_ms, privacy_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp, provider, model_name, original_prompt,
            anonymized_prompt, llm_response, deanonymized_response,
            entities_masked_count, entities_json, latency_ms, privacy_score
        ))
        log_id = cursor.lastrowid
        conn.commit()
        if log_id is None:
            raise sqlite3.DatabaseError("Failed to retrieve inserted log ID")
        return log_id
    finally:
        conn.close()

def get_logs(limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve the latest audit logs from the database."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM audit_logs 
            ORDER BY id DESC 
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
    finally:
        conn.close()

    logs = []
    for row in rows:
        log_item = dict(row)
        
        # Try to decrypt key fields
        for field in ["original_prompt", "anonymized_prompt", "llm_response", "deanonymized_response"]:
            val = log_item.get(field, "")
            if val and val != "[REDACTED FOR COMPLIANCE]":
                decrypted = decrypt_key(val)
                if decrypted:
                    log_item[field] = decrypted
                    
        # Parse entities_details back to a list of dicts
        try:
            log_item["entities_details"] = json.loads(log_item["entities_details"])
            # Try to decrypt entities text
            if isinstance(log_item["entities_details"], list):
                for e in log_item["entities_details"]:
                    t = e.get("text", "")
                    if t and t != "[REDACTED]":
                        dec = decrypt_key(t)
                        if dec:
                            e["text"] = dec
        except Exception:
            log_item["entities_details"] = []
            
        logs.append(log_item)
    return logs

def clear_logs():
    """Clear all records from audit logs."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM audit_logs")
        conn.commit()
    finally:
        conn.close()

def save_document(filename: str, chunks: List[Dict[str, Any]]) -> int:
    """Save a document and its anonymized chunks to the database."""
    timestamp = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO documents (filename, uploaded_at) VALUES (?, ?)",
            (encrypt_key(filename), timestamp)
        )
        doc_id = cursor.lastrowid
        if doc_id is None:
            raise sqlite3.DatabaseError("Failed to retrieve inserted document ID")
        
        for idx, chunk in enumerate(chunks):
            # Encrypt original chunk and mapping for privacy compliance
            enc_original = encrypt_key(chunk["original_text"])
            enc_mapping = encrypt_key(json.dumps(chunk["mapping"]))
            
            cursor.execute("""
                INSERT INTO document_chunks (document_id, chunk_index, original_text, anonymized_text, mapping_json)
                VALUES (?, ?, ?, ?, ?)
            """, (doc_id, idx, enc_original, chunk["anonymized_text"], enc_mapping))
            
        conn.commit()
        return doc_id
    finally:
        conn.close()

def get_documents() -> List[Dict[str, Any]]:
    """Retrieve all uploaded documents."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents ORDER BY id DESC")
        rows = cursor.fetchall()
        docs = []
        for r in rows:
            doc = dict(r)
            dec_name = decrypt_key(doc["filename"])
            if dec_name:
                doc["filename"] = dec_name
            docs.append(doc)
        return docs
    finally:
        conn.close()

def delete_document_by_id(doc_id: int):
    """Delete a document and all its chunks from the database."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM document_chunks WHERE document_id = ?", (doc_id,))
        cursor.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.commit()
    finally:
        conn.close()

def get_anonymized_chunks(document_ids: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    """Retrieve chunks (optionally filtered by document IDs) with decrypted original text and mapping."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if document_ids is not None:
            if not document_ids:
                return []
            placeholders = ",".join("?" for _ in document_ids)
            cursor.execute(f"SELECT * FROM document_chunks WHERE document_id IN ({placeholders})", document_ids)
        else:
            cursor.execute("SELECT * FROM document_chunks")
        rows = cursor.fetchall()
        
        chunks = []
        for r in rows:
            chunk = dict(r)
            dec_orig = decrypt_key(chunk["original_text"])
            dec_map = decrypt_key(chunk["mapping_json"])
            try:
                chunk["original_text"] = dec_orig
                chunk["mapping"] = json.loads(dec_map) if dec_map else {}
            except Exception:
                chunk["mapping"] = {}
            chunks.append(chunk)
        return chunks
    finally:
        conn.close()
