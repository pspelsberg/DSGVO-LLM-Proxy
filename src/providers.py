import time
import re
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

class ProviderStrategy(ABC):
    @abstractmethod
    def get_url(self, base_url: str, model_name: str) -> str:
        """Get target URL for the API call."""
        pass

    @abstractmethod
    def get_headers(self, api_key: str, provider_key: str) -> Dict[str, str]:
        """Get HTTP headers for the API call."""
        pass

    @abstractmethod
    def format_request(self, request_body: Dict[str, Any], model_name: str) -> Dict[str, Any]:
        """Translate OpenAI-style request to provider-specific request payload."""
        pass

    @abstractmethod
    def format_response(self, response_data: Dict[str, Any], model_name: str) -> Dict[str, Any]:
        """Translate provider-specific response payload back to OpenAI-style response."""
        pass


class OpenAIStyleProvider(ProviderStrategy):
    def get_url(self, base_url: str, model_name: str) -> str:
        return base_url

    def get_headers(self, api_key: str, provider_key: str) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        if provider_key == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/google/dsgvo-proxy"
            headers["X-Title"] = "DSGVO LLM Privacy Gateway"
        return headers

    def format_request(self, request_body: Dict[str, Any], model_name: str) -> Dict[str, Any]:
        payload = {**request_body, "model": model_name}
        if "stream" in payload:
            payload["stream"] = False
        return payload

    def format_response(self, response_data: Dict[str, Any], model_name: str) -> Dict[str, Any]:
        # Already OpenAI-compatible format
        return response_data


class AnthropicProvider(ProviderStrategy):
    def get_url(self, base_url: str, model_name: str) -> str:
        return base_url

    def get_headers(self, api_key: str, provider_key: str) -> Dict[str, str]:
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }

    def format_request(self, request_body: Dict[str, Any], model_name: str) -> Dict[str, Any]:
        openai_msgs = request_body.get("messages", [])
        anthropic_msgs = []
        system_prompt = ""
        
        for msg in openai_msgs:
            role = msg.get("role")
            content = msg.get("content")
            if role == "system":
                if isinstance(content, str):
                    system_prompt = content
                elif isinstance(content, list):
                    system_prompt = " ".join([
                        i.get("text", "") 
                        for i in content 
                        if isinstance(i, dict) and i.get("type") == "text"
                    ])
            elif role in ["user", "assistant"]:
                anthropic_msgs.append({"role": role, "content": content})
                
        payload = {
            "model": model_name,
            "messages": anthropic_msgs,
            "max_tokens": request_body.get("max_tokens", 1024),
            "temperature": request_body.get("temperature", 0.7)
        }
        if system_prompt:
            payload["system"] = system_prompt
        return payload

    def format_response(self, response_data: Dict[str, Any], model_name: str) -> Dict[str, Any]:
        text_content = ""
        for content_block in response_data.get("content", []):
            if content_block.get("type") == "text":
                text_content += content_block.get("text", "")
                
        return {
            "id": response_data.get("id", f"chatcmpl-anth-{int(time.time())}"),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": text_content
                    },
                    "finish_reason": "stop" if response_data.get("stop_reason") == "end_turn" else response_data.get("stop_reason")
                }
            ],
            "usage": {
                "prompt_tokens": response_data.get("usage", {}).get("input_tokens", 0),
                "completion_tokens": response_data.get("usage", {}).get("output_tokens", 0),
                "total_tokens": (
                    response_data.get("usage", {}).get("input_tokens", 0) + 
                    response_data.get("usage", {}).get("output_tokens", 0)
                )
            }
        }


class GeminiProvider(ProviderStrategy):
    def get_url(self, base_url: str, model_name: str) -> str:
        # Sanitize model name to prevent path injection
        clean_model = re.sub(r"[^a-zA-Z0-9_\-\.]", "", model_name)
        return base_url.format(model=clean_model)

    def get_headers(self, api_key: str, provider_key: str) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }

    def format_request(self, request_body: Dict[str, Any], model_name: str) -> Dict[str, Any]:
        openai_msgs = request_body.get("messages", [])
        gemini_contents = []
        system_instruction = None
        
        for msg in openai_msgs:
            role = msg.get("role")
            content = msg.get("content")
            if role == "system":
                if isinstance(content, str):
                    system_instruction = {"parts": [{"text": content}]}
                elif isinstance(content, list):
                    parts = [{"text": i.get("text", "")} for i in content if isinstance(i, dict) and i.get("type") == "text"]
                    if parts:
                        system_instruction = {"parts": parts}
            elif role in ["user", "assistant"]:
                gemini_role = "user" if role == "user" else "model"
                parts = []
                if isinstance(content, str):
                    parts = [{"text": content}]
                elif isinstance(content, list):
                    parts = [{"text": i.get("text", "")} for i in content if isinstance(i, dict) and i.get("type") == "text"]
                
                if parts:
                    gemini_contents.append({
                        "role": gemini_role,
                        "parts": parts
                    })
        
        payload = {
            "contents": gemini_contents,
            "generationConfig": {
                "temperature": request_body.get("temperature", 0.7),
                "maxOutputTokens": request_body.get("max_tokens", 1024)
            }
        }
        if system_instruction:
            payload["systemInstruction"] = system_instruction
        return payload

    def format_response(self, response_data: Dict[str, Any], model_name: str) -> Dict[str, Any]:
        try:
            text_content = response_data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            text_content = "Error: Could not extract content from Gemini response."
            
        return {
            "id": f"chatcmpl-gemini-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": text_content
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": len(text_content) // 4,
                "completion_tokens": len(text_content) // 4,
                "total_tokens": len(text_content) // 2
            }
        }


def get_provider_strategy(provider: str) -> ProviderStrategy:
    provider_key = provider.lower()
    if provider_key in ["openai", "mistral", "openrouter"]:
        return OpenAIStyleProvider()
    elif provider_key == "anthropic":
        return AnthropicProvider()
    elif provider_key == "gemini":
        return GeminiProvider()
    else:
        raise ValueError(f"Unsupported provider: {provider}")
