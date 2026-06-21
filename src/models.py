from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Optional, Any

class PIIEntity(BaseModel):
    entity_type: str = Field(..., description="Type of PII (e.g. PERSON, EMAIL_ADDRESS)")
    start: int = Field(..., description="Start index in original text")
    end: int = Field(..., description="End index in original text")
    score: float = Field(..., description="Detection confidence score")
    text: str = Field(..., description="Original sensitive text value")

class AnonymizeRequest(BaseModel):
    text: str = Field(..., description="Raw input text to analyze and mask")
    language: str = Field("de", description="Language of input text ('de' or 'en')")

class AnonymizeResponse(BaseModel):
    original_text: str
    anonymized_text: str
    entities: List[PIIEntity]
    mapping: Dict[str, str] = Field(..., description="Placeholder to original value mapping")

class AgentConfig(BaseModel):
    id: str = Field(..., description="Unique agent identifier")
    name: str = Field(..., description="Display name for the agent")
    api_key: str = Field(..., description="Virtual API key for this agent")
    token_limit: Optional[int] = Field(None, description="Optional token limit for this specific agent")

class ConfigUpdate(BaseModel):
    active_entities: List[str] = Field(..., description="List of active PII entity types")
    threshold: float = Field(..., ge=0.0, le=1.0, description="Confidence threshold (0.0 to 1.0)")
    mock_mode: bool = Field(..., description="Toggle mock LLM mode vs real APIs")
    provider: str = Field(..., description="Selected LLM provider (mock, openai, anthropic, mistral, gemini)")
    model_name: Optional[str] = Field(None, description="Specific LLM model to request")
    whitelist: List[str] = Field(default_factory=list)
    blacklist: List[str] = Field(default_factory=list)
    entity_strategies: Dict[str, str] = Field(default_factory=dict)
    api_keys: Dict[str, str] = Field(default_factory=dict)
    safe_logging_mode: bool = False
    chunking_enabled: bool = True
    chunk_size: int = Field(4000, ge=100, le=50000)
    sliding_window_enabled: bool = True
    max_context_tokens: int = Field(12000, ge=1000, le=128000)
    global_token_limit: Optional[int] = Field(None, ge=1000, description="Global token limit since server start")
    agents: List[AgentConfig] = Field(default_factory=list)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        allowed = {"mock", "openai", "anthropic", "mistral", "gemini", "openrouter"}
        if v not in allowed:
            raise ValueError(f"Provider must be one of {allowed}")
        return v

    @field_validator("whitelist", "blacklist")
    @classmethod
    def validate_lists(cls, v: List[str]) -> List[str]:
        if len(v) > 500:
            raise ValueError("List cannot contain more than 500 items")
        for item in v:
            if len(item) > 100:
                raise ValueError("List items cannot exceed 100 characters")
        return v

class GatewayConfig(BaseModel):
    active_entities: List[str]
    threshold: float
    mock_mode: bool
    provider: str
    model_name: str
    available_providers: List[str]
    all_available_entities: List[str]
    whitelist: List[str]
    blacklist: List[str]
    entity_strategies: Dict[str, str]
    api_keys: Dict[str, str]
    safe_logging_mode: bool
    chunking_enabled: bool
    chunk_size: int
    sliding_window_enabled: bool
    max_context_tokens: int
    global_token_limit: Optional[int]
    agents: List[AgentConfig]

class AuditLogItem(BaseModel):
    id: int
    timestamp: str
    provider: str
    model_name: str
    original_prompt: str
    anonymized_prompt: str
    llm_response: str
    deanonymized_response: str
    entities_masked_count: int
    entities_details: List[Dict[str, Any]]
    latency_ms: int
    privacy_score: float

class RAGChatRequest(BaseModel):
    question: str
    language: str = "de"
    document_ids: Optional[List[int]] = Field(None, description="Optional list of document IDs to restrict search to")
