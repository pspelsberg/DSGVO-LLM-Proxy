import copy
import hashlib
import hmac
import logging
import os
import re
from typing import List, Dict, Any, Optional, Tuple
from presidio_analyzer import AnalyzerEngine, RecognizerRegistry, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from src.config import DEFAULT_THRESHOLD, DEFAULT_ACTIVE_ENTITIES, SUPPORTED_LANGUAGES
from src.models import PIIEntity

logger = logging.getLogger(__name__)

# Custom German PII Regex Patterns
# 1. German Tax ID (Steueridentifikationsnummer - 11 digits)
DE_TAX_ID_PATTERN = Pattern(
    name="de_tax_id_pattern",
    regex=r"\b\d{11}\b",
    score=0.95
)

# 2. German Tax Number (Steuernummer - e.g. 12/345/67890 or 123/456/78901)
DE_STEUERNR_PATTERN = Pattern(
    name="de_steuernr_pattern",
    regex=r"\b\d{2,4}/\d{3,4}/\d{4,5}\b",
    score=0.85
)

# 3. German Vehicle License Plate (Kfz-Kennzeichen - e.g. B-MW 1234 or HH-AB 123)
DE_LICENSE_PLATE_PATTERN = Pattern(
    name="de_license_plate_pattern",
    regex=r"\b[A-ZÄÖÜ]{1,3}-[A-Z]{1,2}\s\d{1,4}[EH]?\b",
    score=0.9
)

# 4. German Identity Card Number (Personalausweisnummer - e.g. T22000129)
DE_ID_CARD_PATTERN = Pattern(
    name="de_id_card_pattern",
    regex=r"\b[C-FGHJKLMNPRTVWXYZ0-9]{9}\b",
    score=0.8
)

# 5. German Phone Number (more targeted than built-in phone recognizer for DE context)
DE_PHONE_PATTERN = Pattern(
    name="de_phone_pattern",
    regex=r"\b(?:\+49|0049|0)(?:[1-9]\d{1,4})(?:[ /.-]?\d{3,10})\b",
    score=0.85
)

# 6. German IBAN (starts with DE, followed by 20 digits, can contain spaces)
DE_IBAN_PATTERN = Pattern(
    name="de_iban_pattern",
    regex=r"\bDE\d{2}[ ]?(?:\d{4}[ ]?){4}\d{2}\b",
    score=0.95
)

# 7. German Street Address (compound street suffix + house number)
DE_STREET_ADDRESS_PATTERN = Pattern(
    name="de_street_address_pattern",
    regex=r"\b[A-ZÄÖÜ][a-zA-ZäöüÄÖÜß-]+(?:straße|str\.?|weg|gasse|allee|platz|ring|damm|zeile|pfad|steig|chaussee|ufer)\s+\d+[a-zA-Z]?\b",
    score=0.85
)

# 8. German Street Address (with preposition/article: Am, Im, An der)
DE_STREET_ADDRESS_AM_PATTERN = Pattern(
    name="de_street_address_am_pattern",
    regex=r"\b(?:Am|An\s+der|Im)\s+[A-ZÄÖÜ][a-zA-ZäöüÄÖÜß-]+\s+\d+[a-zA-Z]?\b",
    score=0.85
)

# 9. English Street Address (house number + name + street suffix)
EN_STREET_ADDRESS_PATTERN = Pattern(
    name="en_street_address_pattern",
    regex=r"\b\d+\s+[A-Z][A-Za-z0-9\s.-]+(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Boulevard|Blvd\.?|Drive|Dr\.?|Lane|Ln\.?|Court|Ct\.?|Way)\b",
    score=0.85
)


class PIIEngine:
    def __init__(self):
        self.analyzer: Optional[AnalyzerEngine] = None
        self.anonymizer: Optional[AnonymizerEngine] = None
        self.active_entities: List[str] = DEFAULT_ACTIVE_ENTITIES
        self.threshold: float = DEFAULT_THRESHOLD
        self.whitelist: List[str] = []
        self.blacklist: List[str] = []
        self.entity_strategies: Dict[str, str] = {}
        self.chunking_enabled: bool = True
        self.chunk_size: int = 4000
        
        # Initialize hash salt securely – required for deterministic pseudonymization
        hash_salt_str = os.getenv("PII_HASH_SALT")
        if not hash_salt_str:
            # Fallback to persistent key file to maintain consistency across restarts
            from src.config import BASE_DIR
            salt_file = BASE_DIR / ".gateway_hash_salt.key"
            if salt_file.exists():
                try:
                    with open(salt_file, "r") as f:
                        hash_salt_str = f.read().strip()
                except Exception as e:
                    logger.error(f"Failed to read hash salt from file: {e}")
            
            if not hash_salt_str:
                import secrets
                hash_salt_str = secrets.token_hex(32)
                try:
                    with open(salt_file, "w") as f:
                        f.write(hash_salt_str)
                    logger.warning(f"Environment variable PII_HASH_SALT is not set. Generated a persistent fallback salt in {salt_file}.")
                except Exception as e:
                    logger.warning(f"Environment variable PII_HASH_SALT is not set. Generated a temporary fallback salt. Error writing file: {e}")
        self._hash_salt_str = hash_salt_str

        
        self._initialize_engines()

    @property
    def hash_salt(self) -> str:
        """Get the hash salt used for pseudonymization."""
        return self._hash_salt_str

    def _initialize_engines(self):
        """Configure spaCy and initialize Presidio engines."""
        logger.info("Initializing NLP and Presidio Engines...")
        
        # Configure spaCy for English and German
        configuration = {
            "nlp_engine_name": "spacy",
            "models": [
                {"lang_code": "en", "model_name": "en_core_web_sm"},
                {"lang_code": "de", "model_name": "de_core_news_sm"}
            ],
        }
        
        provider = NlpEngineProvider(nlp_configuration=configuration)
        nlp_engine = provider.create_engine()
        
        # Register custom recognizers in the registry
        registry = RecognizerRegistry(supported_languages=SUPPORTED_LANGUAGES)
        registry.load_predefined_recognizers(nlp_engine=nlp_engine)
        
        # Ensure predefined English recognizers are also active for German (e.g. Email, IP, Crypto)
        # Copy predefined English recognizers to also work for German
        de_recognizers = []
        for recognizer in registry.recognizers:
            if recognizer.supported_language == "en":
                de_rec = copy.copy(recognizer)
                de_rec.supported_language = "de"
                de_recognizers.append(de_rec)
        
        for de_rec in de_recognizers:
            registry.add_recognizer(de_rec)
        
        # Instantiate and add custom recognizers
        custom_recognizers = [
            PatternRecognizer(supported_entity="DE_TAX_ID", patterns=[DE_TAX_ID_PATTERN], supported_language="de"),
            PatternRecognizer(supported_entity="DE_STEUERNR", patterns=[DE_STEUERNR_PATTERN], supported_language="de"),
            PatternRecognizer(supported_entity="DE_LICENSE_PLATE", patterns=[DE_LICENSE_PLATE_PATTERN], supported_language="de"),
            PatternRecognizer(supported_entity="DE_ID_CARD", patterns=[DE_ID_CARD_PATTERN], supported_language="de"),
            PatternRecognizer(supported_entity="DE_PHONE_NUMBER", patterns=[DE_PHONE_PATTERN], supported_language="de"),
            # IBAN can be recognized in en and de
            PatternRecognizer(supported_entity="IBAN_CODE", patterns=[DE_IBAN_PATTERN], supported_language="de"),
            PatternRecognizer(supported_entity="IBAN_CODE", patterns=[DE_IBAN_PATTERN], supported_language="en"),
            PatternRecognizer(supported_entity="STREET_ADDRESS", patterns=[DE_STREET_ADDRESS_PATTERN, DE_STREET_ADDRESS_AM_PATTERN], supported_language="de"),
            PatternRecognizer(supported_entity="STREET_ADDRESS", patterns=[EN_STREET_ADDRESS_PATTERN], supported_language="en"),
        ]
        
        for recognizer in custom_recognizers:
            registry.add_recognizer(recognizer)
            
        self.analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine,
            registry=registry,
            supported_languages=SUPPORTED_LANGUAGES
        )
        self.anonymizer = AnonymizerEngine()
        logger.info("Presidio Engines successfully initialized.")

    def set_config(self, active_entities: List[str], threshold: float, whitelist: Optional[List[str]] = None, blacklist: Optional[List[str]] = None, entity_strategies: Optional[Dict[str, str]] = None, chunking_enabled: bool = True, chunk_size: int = 4000):
        """Update active PII categories and confidence score threshold."""
        self.active_entities = active_entities
        self.threshold = threshold
        self.whitelist = [w.lower().strip() for w in whitelist if w.strip()] if whitelist else []
        self.blacklist = [b.strip() for b in blacklist if b.strip()] if blacklist else []
        self.entity_strategies = entity_strategies or {}
        self.chunking_enabled = chunking_enabled
        self.chunk_size = chunk_size

    def analyze(self, text: str, language: str = "de") -> List[PIIEntity]:
        """Detect PII entities in the text, applying whitelist & blacklist filters."""
        if not text:
            return []
            
        language = language.lower()
        if language not in SUPPORTED_LANGUAGES:
            language = "de"  # Default back to German
            
        CHUNK_SIZE = self.chunk_size
        # Dynamically limit overlap to at most half of the chunk size, with a maximum of 200
        OVERLAP = min(200, CHUNK_SIZE // 2)
        
        pii_entities = []
        
        # If the text is short enough or chunking is disabled, analyze directly
        if not self.chunking_enabled or len(text) <= CHUNK_SIZE:
            pii_entities = self._analyze_chunk(text, language, offset=0)
        else:
            # Split text into overlapping chunks for large documents
            start = 0
            while start < len(text):
                end = min(start + CHUNK_SIZE, len(text))
                chunk_text = text[start:end]
                chunk_entities = self._analyze_chunk(chunk_text, language, offset=start)
                pii_entities.extend(chunk_entities)
                # Next chunk start (ensure start advances by at least 1 to avoid infinite loop)
                step = CHUNK_SIZE - OVERLAP
                start += max(step, 1)
                if end == len(text):
                    break
                
        # Resolve Overlaps (Keep larger spans and deduplicate)
        # Must run ALWAYS to resolve conflicts between Presidio and Blacklist matches
        sorted_ents = sorted(pii_entities, key=lambda x: (x.start, -(x.end - x.start)))
        non_overlapping = []
        last_end = -1
        for ent in sorted_ents:
            if ent.start >= last_end:
                non_overlapping.append(ent)
                last_end = ent.end
                
        return non_overlapping

    def _analyze_chunk(self, text: str, language: str, offset: int) -> List[PIIEntity]:
        """Helper method to analyze a single text segment."""
        if self.analyzer is None:
            return []
            
        results = self.analyzer.analyze(
            text=text,
            language=language,
            entities=self.active_entities,
            score_threshold=self.threshold
        )
        
        pii_entities = []
        for res in results:
            pii_entities.append(PIIEntity(
                entity_type=res.entity_type,
                start=res.start + offset,
                end=res.end + offset,
                score=res.score,
                text=text[res.start:res.end]
            ))
            
        # Inject blacklist terms as PII entities with maximum confidence
        # Match whole words or general terms case-insensitively
        for word in self.blacklist:
            # Match whole words or general terms case-insensitively
            for match in re.finditer(re.escape(word), text, re.IGNORECASE):
                start, end = match.span()
                matched_text = text[start:end]
                pii_entities.append(PIIEntity(
                    entity_type="BLACKLIST",
                    start=start + offset,
                    end=end + offset,
                    score=1.0,
                    text=matched_text
                ))
                
        # Filter Whitelist terms (case-insensitive)
        pii_entities = [e for e in pii_entities if e.text.lower().strip() not in self.whitelist]
        return pii_entities

    def anonymize(
        self,
        text: str,
        entities: List[PIIEntity],
        type_counts: Optional[Dict[str, int]] = None,
        placeholder_prefix: str = ""
    ) -> Tuple[str, Dict[str, str]]:
        """
        Replace detected PII based on category-specific masking strategies.
        Returns the anonymized text and a mapping dict of replacements to original values.
        """
        if not text or not entities:
            return text, {}

        if type_counts is None:
            type_counts = {}

        # 1. Assign replacements left-to-right to keep incremental indices natural (0, 1, ...)
        sorted_lr = sorted(entities, key=lambda x: x.start)
        entity_replacements = []
        
        for entity in sorted_lr:
            ent_type = entity.entity_type
            strategy = self.entity_strategies.get(ent_type, "placeholder")
            
            if strategy == "redact":
                replacement = f"[REDACTED_{ent_type}]"
            elif strategy == "hash":
                # HMAC-SHA256 with configurable salt for GDPR-compliant pseudonymization
                if not self._hash_salt_str:
                    raise ValueError(
                        "Cannot use 'hash' anonymization strategy: PII_HASH_SALT environment variable is not set. "
                        "Set it to a persistent secret value for reproducible pseudonymization."
                    )
                hash_salt = self._hash_salt_str.encode("utf-8")
                digest = hmac.new(hash_salt, entity.text.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
                replacement = f"[HASH_{digest}]"
            elif strategy == "faker":
                if ent_type not in type_counts:
                    type_counts[ent_type] = 0
                replacement = get_fake_value(ent_type, type_counts[ent_type])
                type_counts[ent_type] += 1
            else:  # "placeholder"
                if ent_type not in type_counts:
                    type_counts[ent_type] = 0
                placeholder = f"<{placeholder_prefix}{ent_type}_{type_counts[ent_type]}>"
                type_counts[ent_type] += 1
                replacement = placeholder
                
            entity_replacements.append((entity, replacement))

        # 2. Apply replacements right-to-left to keep indices valid
        mapping = {}
        anonymized_chars = list(text)
        for entity, replacement in sorted(entity_replacements, key=lambda x: x[0].start, reverse=True):
            ent_type = entity.entity_type
            strategy = self.entity_strategies.get(ent_type, "placeholder")
            if strategy != "redact":
                mapping[replacement] = entity.text
            anonymized_chars[entity.start:entity.end] = list(replacement)
            
        anonymized_text = "".join(anonymized_chars)
        return anonymized_text, mapping

    @staticmethod
    def deanonymize(text: str, mapping: Dict[str, str]) -> str:
        """Replace placeholders in the LLM response back with original values.
        
        Structured placeholders (e.g. <PERSON_0>, [HASH_abc]) are replaced by exact match.
        Faker values (e.g. 'Max Müller') are only replaced at word boundaries to prevent
        accidental replacement of regular words that happen to match a fake name or city.
        """
        if not text or not mapping:
            return text
            
        deanonymized_text = text
        # Sort keys by length descending to prevent replacing substrings first (e.g. replacing 'Max' before 'Max Müller')
        for placeholder in sorted(mapping.keys(), key=len, reverse=True):
            original_value = mapping[placeholder]
            
            # Structured placeholders: <...> or [...] – safe for direct replacement
            if (placeholder.startswith("<") and placeholder.endswith(">")) or \
               (placeholder.startswith("[") and placeholder.endswith("]")):
                deanonymized_text = deanonymized_text.replace(placeholder, original_value)
            else:
                # Faker values: only replace at word boundaries to avoid false positives
                escaped = re.escape(placeholder)
                deanonymized_text = re.sub(
                    rf"(?<!\w){escaped}(?!\w)",
                    lambda m, ov=original_value: ov,
                    deanonymized_text
                )
            
        return deanonymized_text

def get_fake_value(entity_type: str, index: int) -> str:
    fakes = {
        "PERSON": ["Max Müller", "Erika Mustermann", "Christian Schmidt", "Laura Weber", "Thomas Fischer"],
        "EMAIL_ADDRESS": ["max.mueller@mail.de", "erika.m@web.de", "c.schmidt@gmx.de", "laura.w@t-online.de", "thomas.f@gmail.com"],
        "LOCATION": ["Berlin", "München", "Hamburg", "Köln", "Frankfurt"],
        "STREET_ADDRESS": ["Musterstraße 123", "Hauptstraße 45", "Goethestraße 9", "Bahnhofstraße 22", "Schillerstraße 10"],
        "PHONE_NUMBER": ["+49 170 1111111", "+49 171 2222222", "+49 172 3333333", "+49 173 4444444", "+49 174 5555555"],
        "DE_PHONE_NUMBER": ["0170 1111111", "0171 2222222", "0172 3333333", "0173 4444444", "0174 5555555"],
        "IP_ADDRESS": ["192.168.1.1", "10.0.0.1", "172.16.0.1", "192.168.0.100", "8.8.8.8"],
        "CREDIT_CARD": ["4111-1111-1111-1111", "5555-5555-5555-5555", "3782-821938-10008", "4222-2222-2222-2222", "4111-2222-3333-4444"],
        "IBAN_CODE": ["DE89 3704 0044 0532 0130 00", "DE89 5001 0517 3847 2819 01", "DE89 1002 0000 0123 4567 89", "DE89 2003 0000 9876 5432 10"],
        "DE_TAX_ID": ["98765432109", "12345678901", "90123456789", "23456789012"],
        "DE_STEUERNR": ["12/345/67890", "123/456/78901", "12/345/67891", "123/456/78902"],
        "DE_LICENSE_PLATE": ["B-MW 1234", "HH-AB 123", "M-XY 9876", "K-ZZ 4444"],
        "DE_ID_CARD": ["T22000129", "F12345678", "G87654321", "C99999999"],
        "BLACKLIST": ["CONFIDENTIAL_ITEM", "SECRET_PROJECT", "CLASSIFIED_INFO"]
    }
    items = fakes.get(entity_type, [f"Mock_{entity_type}"])
    base_val = items[index % len(items)]
    suffix_num = index // len(items)
    if suffix_num > 0:
        if entity_type == "EMAIL_ADDRESS" and "@" in base_val:
            parts = base_val.split("@", 1)
            return f"{parts[0]}{suffix_num + 1}@{parts[1]}"
        return f"{base_val} {suffix_num + 1}"
    return base_val
