import copy
import httpx
import logging
import time
import re
import asyncio
import os
from typing import Dict, Any, Tuple, Optional, List
from src.pii_engine import PIIEngine
from src.config import PROVIDERS, get_api_key
from src.utils.logger import log_request
from src.providers import get_provider_strategy

logger = logging.getLogger(__name__)

class Gateway:
    def __init__(self, pii_engine: PIIEngine, http_client: httpx.AsyncClient):
        self.pii_engine = pii_engine
        self.http_client = http_client
        self.global_token_count = 0
        self.agent_token_counts = {}
        limit_env = os.getenv("GLOBAL_TOKEN_LIMIT")
        self.global_token_limit = int(limit_env) if limit_env and limit_env.isdigit() else None
        self._token_lock = asyncio.Lock()

    async def process_chat_completion(
        self,
        request_body: Dict[str, Any],
        provider: str,
        model_name: str,
        mock_mode: bool,
        language: str = "de",
        api_keys: Optional[Dict[str, str]] = None,
        safe_logging_mode: bool = False,
        sliding_window_enabled: bool = True,
        max_context_tokens: int = 12000,
        global_token_limit: Optional[int] = None,
        agent_id: Optional[str] = None,
        agents_config: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[Dict[str, Any], int]:
        """
        Main entry point for proxying `/v1/chat/completions`.
        Anonymizes prompts, calls the LLM (or mock), deanonymizes response, logs to DB, and returns OpenAI-style response.
        """
        # 1. Extract messages
        messages = request_body.get("messages", [])
        if not messages:
            return {"error": {"message": "No messages provided", "type": "invalid_request_error"}}, 400
            
        def estimate_tokens(msgs):
            total_len = 0
            for m in msgs:
                content = m.get("content")
                if isinstance(content, str):
                    total_len += len(content)
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                            total_len += len(item.get("text", ""))
            return total_len // 4

        start_time = time.time()
        
        # Deep copy to prevent in-place mutation of the caller's dict
        request_body = copy.deepcopy(request_body)
        
        if sliding_window_enabled:
            MAX_CONTEXT_TOKENS = max_context_tokens
                
            system_msg = None
            chat_messages = []
            for msg in messages:
                if msg.get("role") == "system":
                    system_msg = msg
                else:
                    chat_messages.append(msg)
                    
            # Sliding window loop: discard oldest messages until we fit in context
            start_idx = 0
            while len(chat_messages) - start_idx > 1:
                current_msgs = [system_msg] + chat_messages[start_idx:] if system_msg else chat_messages[start_idx:]
                if estimate_tokens(current_msgs) <= MAX_CONTEXT_TOKENS:
                    break
                # Discard the oldest chat message (and ensure we keep alternating roles by discarding pairs if needed)
                start_idx += 1
                if start_idx < len(chat_messages) and chat_messages[start_idx].get("role") != "user":
                    start_idx += 1
                
            # Re-assemble messages
            chat_messages = chat_messages[start_idx:]
            messages = [system_msg] + chat_messages if system_msg else chat_messages
            request_body["messages"] = messages
            
        # Token Reservation (Fix for CWE-367 Race Condition)
        estimated_input = estimate_tokens(messages)
        raw_max_tokens = request_body.get("max_tokens")
        try:
            expected_output = int(raw_max_tokens) if (raw_max_tokens is not None and int(raw_max_tokens) > 0) else 1000
        except (ValueError, TypeError):
            expected_output = 1000
        reserved_tokens = estimated_input + expected_output
        
        actual_limit = global_token_limit if global_token_limit is not None else self.global_token_limit
        async with self._token_lock:
            if actual_limit is not None and (self.global_token_count + reserved_tokens) > actual_limit:
                return {"error": {"message": f"Global token limit of {actual_limit} exceeded.", "type": "quota_exceeded_error"}}, 429
                
            if agent_id and agents_config:
                agent_cfg = next((a for a in agents_config if a.get("id") == agent_id), None)
                if agent_cfg and agent_cfg.get("token_limit"):
                    agent_limit = agent_cfg["token_limit"]
                    agent_used = self.agent_token_counts.get(agent_id, 0)
                    if (agent_used + reserved_tokens) > agent_limit:
                        return {"error": {"message": f"Agent '{agent_cfg.get('name', agent_id)}' token limit of {agent_limit} exceeded.", "type": "quota_exceeded_error"}}, 429
            
            # Reserve tokens proactively
            self.global_token_count += reserved_tokens
            if agent_id:
                self.agent_token_counts[agent_id] = self.agent_token_counts.get(agent_id, 0) + reserved_tokens
        
        # 2. Analyze & Anonymize all user messages in the thread to prevent history leaks
        mapping = {}
        entities = []
        original_prompts = []
        anonymized_prompts = []
        
        has_user_message = False
        type_counts = {}
        
        for msg in messages:
            role = msg.get("role")
            if role in ["user", "assistant"]:
                if role == "user":
                    has_user_message = True
                content_field = msg.get("content", "")
                
                if isinstance(content_field, str):
                    if role == "user":
                        original_prompts.append(content_field)
                    msg_ents = self.pii_engine.analyze(content_field, language=language)
                    anon_prompt, msg_mapping = self.pii_engine.anonymize(content_field, msg_ents, type_counts)
                    msg["content"] = anon_prompt
                    mapping.update(msg_mapping)
                    entities.extend(msg_ents)
                    if role == "user":
                        anonymized_prompts.append(anon_prompt)
                elif isinstance(content_field, list):
                    # Process multimodal list structures safely
                    text_parts = []
                    anon_parts = []
                    for item in content_field:
                        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                            text_val = item.get("text", "")
                            text_parts.append(text_val)
                            item_ents = self.pii_engine.analyze(text_val, language=language)
                            # We map back matching indices inside the individual text block
                            anon_text, item_mapping = self.pii_engine.anonymize(text_val, item_ents, type_counts)
                            item["text"] = anon_text
                            mapping.update(item_mapping)
                            entities.extend(item_ents)
                            anon_parts.append(anon_text)
                    if role == "user":
                        original_prompts.append(" ".join(text_parts))
                        anonymized_prompts.append(" ".join(anon_parts))
                    
        if not has_user_message:
            return {"error": {"message": "No user message found in history", "type": "invalid_request_error"}}, 400
            
        original_prompt = "\n".join(original_prompts)
        anonymized_prompt = "\n".join(anonymized_prompts)
        
        # 3. Call LLM (Mock or Real)
        llm_response_text = ""
        error_response = None
        error_status = 500
        response_payload = {}
        
        if mock_mode or provider.lower() == "mock":
            # Call smart mock responder
            llm_response_text = self._generate_mock_response(anonymized_prompt, mapping, language)
            # Create standard OpenAI response structure
            response_payload = self._create_openai_response_structure(llm_response_text, model_name)
        else:
            # Forward to external LLM provider
            try:
                response_payload, status_code = await self._forward_to_provider(
                    request_body, provider, model_name, api_keys
                )
                if status_code != 200:
                    error_response = response_payload
                    error_status = status_code
                else:
                    # Extract text response from provider payload
                    llm_response_text = self._extract_response_text(response_payload, provider)
            except Exception as e:
                logger.error(f"Error calling LLM provider {provider}: {str(e)}")
                error_response = {"error": {"message": f"Failed to contact provider: {str(e)}", "type": "api_connection_error"}}
                error_status = 502

        if error_response:
            async with self._token_lock:
                self.global_token_count -= reserved_tokens
                if agent_id:
                    self.agent_token_counts[agent_id] = self.agent_token_counts.get(agent_id, 0) - reserved_tokens
            return error_response, error_status

        # 4. Deanonymize LLM response
        deanonymized_response_text = self.pii_engine.deanonymize(llm_response_text, mapping)
        
        # 5. Insert deanonymized text back into response payload (uses copy under the hood)
        modified_response = self._inject_response_text(response_payload, deanonymized_response_text, provider)
        
        # 6. Global Token Counter Update (Input, Output, Reasoning Tokens)
        total = 0
        if "usage" in modified_response:
            usage = modified_response["usage"]
            # total_tokens generally includes input (prompt) + output (completion including reasoning)
            total = usage.get("total_tokens", usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0))
            
        async with self._token_lock:
            self.global_token_count = self.global_token_count - reserved_tokens + total
            if agent_id:
                self.agent_token_counts[agent_id] = self.agent_token_counts.get(agent_id, 0) - reserved_tokens + total
        
        # 7. Log transaction to database
        latency_ms = int((time.time() - start_time) * 1000)
        entities_details = [
            {"entity_type": e.entity_type, "text": e.text, "start": e.start, "end": e.end, "score": e.score}
            for e in entities
        ]
        
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: log_request(
                    provider=provider,
                    model_name=model_name,
                    original_prompt=original_prompt,
                    anonymized_prompt=anonymized_prompt,
                    llm_response=llm_response_text,
                    deanonymized_response=deanonymized_response_text,
                    entities_masked_count=len(entities),
                    entities_details=entities_details,
                    latency_ms=latency_ms,
                    safe_logging_mode=safe_logging_mode
                )
            )
        except Exception as db_err:
            logger.error(f"Failed to save log to SQLite: {str(db_err)}")
            
        return modified_response, 200

    def _generate_mock_response(self, anonymized_prompt: str, mapping: Dict[str, str], language: str) -> str:
        """
        A smart mock responder that echoes back the placeholders and faker values in a natural way.
        This demonstrates how the gateway deanonymizes placeholders returned by the LLM.
        """
        # Find all replacements in the anonymized prompt
        placeholders = [k for k in mapping.keys() if k in anonymized_prompt]
        
        if language.lower() == "de":
            if not placeholders:
                return "Hallo! Ich habe Ihre Anfrage erhalten. Da keine sensiblen personenbezogenen Daten (PII) erkannt wurden, wurde die Anfrage direkt verarbeitet. Wie kann ich Ihnen heute helfen?"
            
            # Construct a dynamic response listing the detected tokens
            p_list = ", ".join(placeholders)
            return (
                f"Hallo! Ich bin ein sicheres Sprachmodell. In Ihrer Anfrage wurden folgende anonymisierte "
                f"Identifikatoren erkannt: {p_list}.\n\n"
                f"Ich antworte Ihnen direkt unter Verwendung dieser Platzhalter. Zum Beispiel weiß ich, "
                f"dass Ihre Identität {placeholders[0] if placeholders else '<unbekannt>'} geschützt ist. "
                f"Unser Proxy-Gateway wird diesen Text nun wieder de-anonymisieren, sodass Sie Ihre echten Daten sehen, "
                f"während sie für mich (das LLM) unsichtbar blieben!"
            )
        else:
            if not placeholders:
                return "Hello! I have received your request. Since no sensitive personal data (PII) was detected, the prompt was processed directly. How can I assist you today?"
            
            p_list = ", ".join(placeholders)
            return (
                f"Hello! I am a privacy-compliant language model. In your prompt, I detected the following anonymized "
                f"tokens: {p_list}.\n\n"
                f"I will reply referencing these placeholders. For instance, I know that the identity of "
                f"{placeholders[0] if placeholders else '<unknown>'} is protected. "
                f"Our Proxy Gateway will now de-anonymize this response so you see your real data, "
                f"which remained completely hidden from me!"
            )

    async def _forward_to_provider(
        self, request_body: Dict[str, Any], provider: str, model_name: str, api_keys: Optional[Dict[str, str]] = None
    ) -> Tuple[Dict[str, Any], int]:
        """
        Sends the anonymized request to the actual LLM API.
        Handles API format translation if necessary.
        """
        provider_key = provider.lower()
        if provider_key not in PROVIDERS:
            return {"error": {"message": f"Unsupported provider: {provider}", "type": "invalid_request_error"}}, 400
            
        api_key = get_api_key(provider_key, api_keys)
        if not api_key:
            return {"error": {"message": f"API Key for {provider} not configured in settings or .env", "type": "authentication_error"}}, 401
            
        provider_info = PROVIDERS[provider_key]
        try:
            strategy = get_provider_strategy(provider_key)
        except ValueError as e:
            return {"error": {"message": str(e), "type": "invalid_request_error"}}, 400
            
        url = strategy.get_url(provider_info.get("url") or "", model_name)
        headers = strategy.get_headers(api_key, provider_key)
        payload = strategy.format_request(request_body, model_name)
        
        response = await self.http_client.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            openai_compatible = strategy.format_response(response.json(), model_name)
            return openai_compatible, 200
        else:
            return response.json(), response.status_code

    def _extract_response_text(self, response_payload: Dict[str, Any], provider: str) -> str:
        """Extract plain text response from the provider's native payload format."""
        try:
            val = response_payload["choices"][0]["message"]["content"]
            return val if val is not None else ""
        except Exception as e:
            logger.error(f"Error extracting response text from payload: {str(e)}")
            return ""

    def _inject_response_text(
        self, response_payload: Dict[str, Any], deanonymized_text: str, provider: str
    ) -> Dict[str, Any]:
        """Inject the deanonymized text back into the response payload."""
        try:
            payload_copy = copy.deepcopy(response_payload)
            payload_copy["choices"][0]["message"]["content"] = deanonymized_text
            return payload_copy
        except Exception as e:
            logger.error(f"Error injecting response text: {str(e)}")
            return response_payload

    def _create_openai_response_structure(self, text: str, model_name: str) -> Dict[str, Any]:
        """Helper to create a standard mock OpenAI chat completion response."""
        return {
            "id": f"chatcmpl-mock-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": text
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": len(text) // 4,
                "completion_tokens": len(text) // 4,
                "total_tokens": len(text) // 2
            }
        }
