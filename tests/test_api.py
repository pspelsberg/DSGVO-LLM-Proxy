import os
import pytest
from fastapi.testclient import TestClient

# Set a mock global API key for the test run
os.environ["GATEWAY_API_KEY"] = "test-secret-key"

# Use a isolated clean test database file to prevent test pollution
TEST_DB_PATH = "gateway_test_logs.db"
os.environ["DB_PATH"] = TEST_DB_PATH

from src.main import app

@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db():
    # Remove the test database file if it exists before the run
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass
    yield
    # Clean up after the session completes
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass

@pytest.fixture
def client():
    # Automatically supply the test API key header for all request helper calls in the tests
    with TestClient(app, headers={"X-API-Key": "test-secret-key"}) as c:
        yield c

def test_unauthenticated_access():
    # Verify that a client without headers receives a 401 Unauthorized response
    with TestClient(app) as unauth_client:
        response = unauth_client.get("/api/config")
        assert response.status_code == 401

def test_security_headers(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert "Strict-Transport-Security" in response.headers
    assert "Content-Security-Policy" in response.headers

def test_rate_limiting(client):
    from src.main import request_counts
    request_counts.clear()
    try:
        # Send 100 requests (all should succeed)
        for _ in range(100):
            response = client.get("/api/config")
            assert response.status_code == 200
            
        # 101st request should trigger 429 Too Many Requests
        response = client.get("/api/config")
        assert response.status_code == 429
        assert response.json() == {"detail": "Too many requests"}
    finally:
        request_counts.clear()

def test_agent_api_key_encryption(client):
    # Set config with a mock agent
    agent_payload = {
        "active_entities": ["PERSON"],
        "threshold": 0.35,
        "mock_mode": True,
        "provider": "mock",
        "model_name": "gpt-4o",
        "whitelist": [],
        "blacklist": [],
        "entity_strategies": {},
        "api_keys": {},
        "safe_logging_mode": False,
        "chunking_enabled": True,
        "chunk_size": 4000,
        "sliding_window_enabled": True,
        "max_context_tokens": 12000,
        "agents": [
            {
                "id": "agent-test-1",
                "name": "Test Agent",
                "api_key": "my-secret-agent-key",
                "token_limit": 5000
            }
        ]
    }
    
    response = client.post("/api/config", json=agent_payload)
    assert response.status_code == 200
    
    # Read the gateway_config.json file directly from disk to verify it's encrypted at rest
    import json
    from src.main import CONFIG_FILE
    with open(CONFIG_FILE, "r") as f:
        disk_config = json.load(f)
        
    agents_on_disk = disk_config.get("agents", [])
    assert len(agents_on_disk) == 1
    disk_key = agents_on_disk[0].get("api_key")
    # It must be encrypted (not plaintext)
    assert disk_key != "my-secret-agent-key"
    assert disk_key != ""
    
    # Getting configuration via API should return it masked
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert data["agents"][0]["api_key"] == "********"

def test_get_config(client):
    # Ensure a consistent default state before testing
    client.post("/api/config", json={
        "active_entities": ["PERSON"],
        "threshold": 0.35,
        "mock_mode": True,
        "provider": "mock",
        "model_name": "gpt-4o",
        "whitelist": [],
        "blacklist": [],
        "entity_strategies": {},
        "api_keys": {},
        "safe_logging_mode": False
    })
    
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert "active_entities" in data
    assert "threshold" in data
    assert "mock_mode" in data
    assert data["mock_mode"] is True

def test_api_analyze(client):
    response = client.post("/api/analyze", json={
        "text": "Mein Name ist Max Mustermann und ich wohne in Berlin.",
        "language": "de"
    })
    assert response.status_code == 200
    data = response.json()
    # At least one entity (Max Mustermann or Berlin) should be detected
    assert len(data) > 0
    entity_types = [e["entity_type"] for e in data]
    assert "PERSON" in entity_types or "LOCATION" in entity_types

def test_update_config(client):
    # Update config
    payload = {
        "active_entities": ["PERSON", "EMAIL_ADDRESS"],
        "threshold": 0.4,
        "mock_mode": True,
        "provider": "mock",
        "model_name": "gpt-4o"
    }
    response = client.post("/api/config", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify it updated
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert data["active_entities"] == ["PERSON", "EMAIL_ADDRESS"]
    assert data["threshold"] == 0.4

def test_chat_completions_proxy_mock_mode(client):
    # Force mock mode and openai provider config
    client.post("/api/config", json={
        "active_entities": ["PERSON", "EMAIL_ADDRESS", "LOCATION"],
        "threshold": 0.35,
        "mock_mode": True,
        "provider": "mock",
        "model_name": "gpt-4o"
    })

    # Call proxy endpoint
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "Hallo, mein Name ist Albert und ich brauche Hilfe."}
        ]
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "choices" in data
    assert len(data["choices"]) > 0
    content = data["choices"][0]["message"]["content"]
    
    # In mock mode, the gateway de-anonymizes placeholders in response.
    # So the output content should contain "Albert" instead of "<PERSON_0>"
    assert "Albert" in content
    assert "<PERSON_0>" not in content

def test_api_whitelist_blacklist(client):
    # Set config with whitelist and blacklist
    client.post("/api/config", json={
        "active_entities": ["PERSON", "LOCATION"],
        "threshold": 0.35,
        "mock_mode": True,
        "provider": "mock",
        "model_name": "gpt-4o",
        "whitelist": ["Munich"],
        "blacklist": ["PhoenixProject"],
        "entity_strategies": {},
        "api_keys": {},
        "safe_logging_mode": False
    })

    # Test live analyze endpoint respects whitelist and blacklist
    response = client.post("/api/analyze", json={
        "text": "Tell John about PhoenixProject in Munich.",
        "language": "en"
    })
    assert response.status_code == 200
    data = response.json()
    entity_texts = [e["text"] for e in data]
    entity_types = [e["entity_type"] for e in data]
    
    # 'Munich' should be whitelisted, so not detected
    assert "Munich" not in entity_texts
    # 'PhoenixProject' should be blacklisted, so detected
    assert "PhoenixProject" in entity_texts
    assert "BLACKLIST" in entity_types

def test_api_safe_logging_mode(client):
    # Enable safe logging mode
    client.post("/api/config", json={
        "active_entities": ["PERSON"],
        "threshold": 0.35,
        "mock_mode": True,
        "provider": "mock",
        "model_name": "gpt-4o",
        "whitelist": [],
        "blacklist": [],
        "entity_strategies": {},
        "api_keys": {},
        "safe_logging_mode": True
    })

    # Call proxy endpoint
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "Mein Name ist Arthur Dent."}
        ]
    }
    client.post("/v1/chat/completions", json=payload)
    
    # Retrieve audit logs
    response = client.get("/api/logs?limit=1")
    assert response.status_code == 200
    logs = response.json()
    assert len(logs) > 0
    latest_log = logs[0]
    
    # The prompt and response should be redacted in SQLite database log
    assert latest_log["original_prompt"] == "[REDACTED FOR COMPLIANCE]"
    assert latest_log["anonymized_prompt"] == "[REDACTED FOR COMPLIANCE]"
    assert latest_log["llm_response"] == "[REDACTED FOR COMPLIANCE]"
    assert latest_log["deanonymized_response"] == "[REDACTED FOR COMPLIANCE]"
    
    # The entities details text should also be redacted
    for ent in latest_log["entities_details"]:
        assert ent["text"] == "[REDACTED]"


def test_api_key_encryption(client):
    test_key = "sk-proj-12345abcdefg"
    
    # Save the config
    response = client.post("/api/config", json={
        "active_entities": ["PERSON"],
        "threshold": 0.35,
        "mock_mode": True,
        "provider": "mock",
        "model_name": "gpt-4o",
        "whitelist": [],
        "blacklist": [],
        "entity_strategies": {},
        "api_keys": {"openai": test_key},
        "safe_logging_mode": False
    })
    assert response.status_code == 200
    
    # Verify GET config returns masked key
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert data["api_keys"]["openai"] == "********"
    
    # Verify config file on disk actually contains the encrypted version
    import json
    from src.main import CONFIG_FILE
    with open(CONFIG_FILE, "r") as f:
        disk_config = json.load(f)
    disk_key = disk_config["api_keys"]["openai"]
    assert disk_key != test_key
    assert disk_key != "********"
    assert len(disk_key) > 20
    
    # Verify decryption
    from src.utils.crypto import decrypt_key
    assert decrypt_key(disk_key) == test_key


def test_api_chat_completions_faker_strategy(client):
    # Setup config with faker strategies for PERSON and STREET_ADDRESS
    client.post("/api/config", json={
        "active_entities": ["PERSON", "STREET_ADDRESS", "EMAIL_ADDRESS"],
        "threshold": 0.35,
        "mock_mode": True,
        "provider": "mock",
        "model_name": "gpt-4o",
        "entity_strategies": {
            "PERSON": "faker",
            "STREET_ADDRESS": "faker",
            "EMAIL_ADDRESS": "faker"
        }
    })

    # Call proxy endpoint
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "Hallo, ich bin Christian Schmidt, wohne in der Goethestraße 15, und meine Mail ist christian.schmidt@mail.de."}
        ]
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    
    # In mock mode, the mock responder returns the replacements found in the prompt,
    # and then the gateway deanonymizes them back to the original values.
    # Therefore, the output should contain the original values.
    assert "Christian Schmidt" in content
    assert "Goethestraße 15" in content
    assert "christian.schmidt@mail.de" in content


def test_rag_workflow(client):
    # 1. Upload file
    import io
    file_content = (
        "Dies ist ein geheimes Dokument über das Projekt Phoenix. "
        "Der leitende Entwickler ist Herr Max Mustermann in Berlin. "
        "Seine Email ist max.m@domain.de."
    )
    file_bytes = io.BytesIO(file_content.encode("utf-8"))
    
    upload_response = client.post(
        "/api/documents/upload",
        files={"file": ("projekt_phoenix.txt", file_bytes, "text/plain")}
    )
    assert upload_response.status_code == 200
    upload_data = upload_response.json()
    assert upload_data["status"] == "success"
    doc_id = upload_data["document_id"]
    assert upload_data["chunks_count"] > 0
    
    # 2. Verify document list
    list_response = client.get("/api/documents")
    assert list_response.status_code == 200
    docs = list_response.json()
    assert any(d["id"] == doc_id for d in docs)
    
    # 3. Query RAG Chat
    rag_response = client.post("/api/rag/chat", json={
        "question": "Wer ist der leitende Entwickler von Projekt Phoenix?",
        "language": "de"
    })
    assert rag_response.status_code == 200
    rag_data = rag_response.json()
    assert "response" in rag_data
    # The response should be de-anonymized and contain "Max Mustermann"
    assert "Max Mustermann" in rag_data["response"]
    
    # 4. Delete document
    delete_response = client.delete(f"/api/documents/{doc_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "success"
    
    # Verify that it is deleted
    list_response2 = client.get("/api/documents")
    docs2 = list_response2.json()
    assert not any(d["id"] == doc_id for d in docs2)


def test_dynamic_routing_api(client):
    # Setup: Standard-Provider ist openai, mock_mode = False, ungültiger Anthropic-Key
    client.post("/api/config", json={
        "active_entities": ["PERSON"],
        "threshold": 0.35,
        "mock_mode": False,
        "provider": "openai",
        "model_name": "gpt-4o",
        "whitelist": [],
        "blacklist": [],
        "entity_strategies": {},
        "api_keys": {"anthropic": "invalid-key-for-testing"},
        "safe_logging_mode": False,
        "chunking_enabled": True,
        "chunk_size": 4000,
        "sliding_window_enabled": True,
        "max_context_tokens": 12000
    })
    
    # Request: Wir fragen ein Anthropic-Modell an
    response = client.post("/v1/chat/completions", json={
        "model": "anthropic/claude-3-5-sonnet",
        "messages": [{"role": "user", "content": "Hello"}]
    })
    # Die Anfrage sollte an Anthropic geroutet werden und wegen des ungültigen Keys scheitern (401 oder 400/502)
    assert response.status_code in [401, 400, 502]


def test_config_updates(client):
    # Teste, ob die neuen Parameter korrekt gespeichert und ausgelesen werden
    client.post("/api/config", json={
        "active_entities": ["PERSON"],
        "threshold": 0.35,
        "mock_mode": True,
        "provider": "mock",
        "model_name": "gpt-4o",
        "whitelist": [],
        "blacklist": [],
        "entity_strategies": {},
        "api_keys": {},
        "safe_logging_mode": False,
        "chunking_enabled": False,
        "chunk_size": 2500,
        "sliding_window_enabled": False,
        "max_context_tokens": 5000
    })
    
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert data["chunking_enabled"] is False
    assert data["chunk_size"] == 2500
    assert data["sliding_window_enabled"] is False
    assert data["max_context_tokens"] == 5000


def test_chat_completions_multimodal_proxy(client):
    # Setup: Mock-Modus aktivieren
    client.post("/api/config", json={
        "active_entities": ["PERSON", "EMAIL_ADDRESS"],
        "threshold": 0.35,
        "mock_mode": True,
        "provider": "mock",
        "model_name": "gpt-4o",
        "whitelist": [],
        "blacklist": [],
        "entity_strategies": {},
        "api_keys": {},
        "safe_logging_mode": False
    })
    
    # Request mit multimodalem Content-Format (Liste von Dictionaries)
    payload = {
        "model": "gpt-4o",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Hallo, ich bin Christian Schmidt und meine E-Mail lautet christian@schmidt.de."
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/jpeg;base64,..."
                        }
                    }
                ]
            }
        ]
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "choices" in data
    content = data["choices"][0]["message"]["content"]
    # Da mock mode de-anonymisiert, sollten Name und E-Mail in der Antwort stehen
    assert "Christian Schmidt" in content
    assert "christian@schmidt.de" in content


def test_document_upload_filename_sanitization(client):
    import io
    file_content = "This is a simple test document."
    file_bytes = io.BytesIO(file_content.encode("utf-8"))
    
    # Upload with a filename containing path traversal and invalid characters
    upload_response = client.post(
        "/api/documents/upload",
        files={"file": ("../../invalid#name_test.txt", file_bytes, "text/plain")}
    )
    assert upload_response.status_code == 200
    upload_data = upload_response.json()
    assert upload_data["status"] == "success"
    doc_id = upload_data["document_id"]
    
    # Retrieve the document list and verify the sanitized filename
    list_response = client.get("/api/documents")
    assert list_response.status_code == 200
    docs = list_response.json()
    uploaded_doc = next(d for d in docs if d["id"] == doc_id)
    # The filename should be sanitized to "invalid_name_test.txt"
    assert uploaded_doc["filename"] == "invalid_name_test.txt"
    
    # Cleanup
    client.delete(f"/api/documents/{doc_id}")


def test_chunk_size_safety(client):
    # Set chunk_size to 100, which previously caused an infinite loop
    client.post("/api/config", json={
        "active_entities": ["PERSON"],
        "threshold": 0.35,
        "mock_mode": True,
        "provider": "mock",
        "model_name": "gpt-4o",
        "whitelist": [],
        "blacklist": [],
        "entity_strategies": {},
        "api_keys": {},
        "safe_logging_mode": False,
        "chunking_enabled": True,
        "chunk_size": 100,
        "sliding_window_enabled": True,
        "max_context_tokens": 12000
    })

    # Send a prompt that is longer than 100 chars, which triggers chunking
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "Mein Name ist Max Mustermann und ich wohne in einer sehr langen Strasse, die weit über hundert Zeichen lang ist."}
        ]
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "choices" in data


def test_rag_isolation(client):
    import io
    
    # 0. Ensure config uses mock mode with faker strategy for PERSON
    client.post("/api/config", json={
        "active_entities": ["PERSON"],
        "threshold": 0.35,
        "mock_mode": True,
        "provider": "mock",
        "model_name": "gpt-4o",
        "whitelist": [],
        "blacklist": [],
        "entity_strategies": {
            "PERSON": "faker"
        },
        "api_keys": {},
        "safe_logging_mode": False,
        "chunking_enabled": True,
        "chunk_size": 4000,
        "sliding_window_enabled": True,
        "max_context_tokens": 12000
    })

    # 1. Upload Doc A (Johannes Voigt)
    file_a_content = "Der leitende Entwickler fuer Projekt Phoenix ist Herr Johannes Voigt."
    file_a_bytes = io.BytesIO(file_a_content.encode("utf-8"))
    upload_a = client.post(
        "/api/documents/upload",
        files={"file": ("project_a.txt", file_a_bytes, "text/plain")}
    )
    assert upload_a.status_code == 200
    doc_a_id = upload_a.json()["document_id"]

    # 2. Upload Doc B (Peter Becker)
    file_b_content = "Der leitende Entwickler fuer Projekt Taurus ist Herr Peter Becker."
    file_b_bytes = io.BytesIO(file_b_content.encode("utf-8"))
    upload_b = client.post(
        "/api/documents/upload",
        files={"file": ("project_b.txt", file_b_bytes, "text/plain")}
    )
    assert upload_b.status_code == 200
    doc_b_id = upload_b.json()["document_id"]

    try:
        # 3. Query RAG restricting to Document B only
        rag_response = client.post("/api/rag/chat", json={
            "question": "Wer ist der leitende Entwickler fuer Projekt Taurus?",
            "language": "de",
            "document_ids": [doc_b_id]
        })
        assert rag_response.status_code == 200
        rag_data = rag_response.json()
        
        # The response should have been deanonymized to include "Peter Becker"
        # but it should NOT contain "Johannes Voigt" as it is restricted to Doc B
        assert "Peter Becker" in rag_data["response"]
        assert "Johannes Voigt" not in rag_data["response"]
        assert rag_data["context_chunks_used"] > 0
    finally:
        # Cleanup
        client.delete(f"/api/documents/{doc_a_id}")
        client.delete(f"/api/documents/{doc_b_id}")


def test_chat_completion_null_max_tokens(client):
    # Verify that max_tokens: None (json null) or invalid max_tokens doesn't crash the proxy
    payload = {
        "model": "mock/gpt-4o",
        "messages": [{"role": "user", "content": "Hallo Welt"}],
        "max_tokens": None
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    assert "choices" in response.json()


def test_playground_length_limit(client):
    # Verify that input text exceeding 50,000 characters fails validation
    long_text = "a" * 50001
    payload = {
        "text": long_text,
        "language": "de"
    }
    response = client.post("/api/analyze", json=payload)
    assert response.status_code == 422  # Validation Error


    







