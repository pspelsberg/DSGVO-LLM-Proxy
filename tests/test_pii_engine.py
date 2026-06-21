import pytest
from src.pii_engine import PIIEngine

@pytest.fixture
def pii_engine():
    return PIIEngine()

def test_analyze_english_person(pii_engine):
    text = "Hello John Doe, how are you?"
    entities = pii_engine.analyze(text, language="en")
    entity_types = [e.entity_type for e in entities]
    assert "PERSON" in entity_types
    
    # Check that John Doe is identified
    john_doe_ent = next(e for e in entities if e.entity_type == "PERSON")
    assert john_doe_ent.text == "John Doe"

def test_analyze_german_person(pii_engine):
    text = "Mein Name ist Max Mustermann."
    entities = pii_engine.analyze(text, language="de")
    entity_types = [e.entity_type for e in entities]
    assert "PERSON" in entity_types
    
    person_texts = [e.text for e in entities if e.entity_type == "PERSON"]
    assert "Max Mustermann" in person_texts

def test_analyze_email(pii_engine):
    text = "Schreiben Sie mir an max@muster.de für Details."
    entities = pii_engine.analyze(text, language="de")
    entity_types = [e.entity_type for e in entities]
    assert "EMAIL_ADDRESS" in entity_types
    
    email_ent = next(e for e in entities if e.entity_type == "EMAIL_ADDRESS")
    assert email_ent.text == "max@muster.de"

def test_custom_de_tax_id(pii_engine):
    text = "Meine Steueridentifikationsnummer lautet 87293847192."
    entities = pii_engine.analyze(text, language="de")
    entity_types = [e.entity_type for e in entities]
    assert "DE_TAX_ID" in entity_types
    
    tax_ent = next(e for e in entities if e.entity_type == "DE_TAX_ID")
    assert tax_ent.text == "87293847192"

def test_custom_de_license_plate(pii_engine):
    text = "Das Auto hat das Kennzeichen HH-AB 1234."
    entities = pii_engine.analyze(text, language="de")
    entity_types = [e.entity_type for e in entities]
    assert "DE_LICENSE_PLATE" in entity_types
    
    plate_ent = next(e for e in entities if e.entity_type == "DE_LICENSE_PLATE")
    assert plate_ent.text == "HH-AB 1234"

def test_anonymize_and_deanonymize(pii_engine):
    text = "Hallo Max Mustermann, bitte melden Sie sich unter max@muster.de."
    entities = pii_engine.analyze(text, language="de")
    
    anonymized, mapping = pii_engine.anonymize(text, entities)
    
    # The anonymized prompt should not contain the original name or email
    assert "Max Mustermann" not in anonymized
    assert "max@muster.de" not in anonymized
    assert "<PERSON_0>" in anonymized
    assert "<EMAIL_ADDRESS_0>" in anonymized
    
    # We simulate the LLM echoing back the placeholders
    llm_response = "Hallo <PERSON_0>, ich habe Ihre E-Mail <EMAIL_ADDRESS_0> erhalten."
    
    deanonymized = pii_engine.deanonymize(llm_response, mapping)
    
    # The deanonymized response should have restored the original name and email
    assert "Max Mustermann" in deanonymized
    assert "max@muster.de" in deanonymized
    assert "<PERSON_0>" not in deanonymized
    assert "<EMAIL_ADDRESS_0>" not in deanonymized

def test_whitelist(pii_engine):
    # Setup config with whitelist
    pii_engine.set_config(
        active_entities=["PERSON", "LOCATION"],
        threshold=0.3,
        whitelist=["Munich", "Max"]
    )
    # Munich should not be detected because it is on the whitelist
    text = "Max works in Munich."
    entities = pii_engine.analyze(text, language="en")
    
    entity_texts = [e.text for e in entities]
    assert "Munich" not in entity_texts
    assert "Max" not in entity_texts

def test_blacklist(pii_engine):
    # Setup config with blacklist
    pii_engine.set_config(
        active_entities=["PERSON"],
        threshold=0.3,
        blacklist=["Project Phoenix", "ConfidentialCorp"]
    )
    
    text = "Check Project Phoenix details for ConfidentialCorp."
    entities = pii_engine.analyze(text, language="en")
    
    entity_types = [e.entity_type for e in entities]
    assert "BLACKLIST" in entity_types
    
    blacklist_texts = [e.text for e in entities if e.entity_type == "BLACKLIST"]
    assert "Project Phoenix" in blacklist_texts
    assert "ConfidentialCorp" in blacklist_texts

def test_anonymize_strategies(pii_engine):
    pii_engine.set_config(
        active_entities=["PERSON", "EMAIL_ADDRESS", "LOCATION"],
        threshold=0.35,
        entity_strategies={
            "PERSON": "faker",
            "EMAIL_ADDRESS": "redact",
            "LOCATION": "hash"
        }
    )
    
    text = "Hello John Doe, write me at john@doe.com. I live in Berlin."
    entities = pii_engine.analyze(text, language="en")
    
    anonymized, mapping = pii_engine.anonymize(text, entities)
    
    # 1. PERSON strategy: 'faker'
    # 'John Doe' should be replaced by a fake name (like Max Müller or Erika Mustermann etc.)
    assert "John Doe" not in anonymized
    # We should have a mapping for the fake name
    fake_name = next(k for k, v in mapping.items() if v == "John Doe")
    assert fake_name in ["Max Müller", "Erika Mustermann", "Christian Schmidt", "Laura Weber", "Thomas Fischer"]

    # 2. EMAIL_ADDRESS strategy: 'redact'
    # 'john@doe.com' should be replaced by '[REDACTED_EMAIL_ADDRESS]'
    assert "john@doe.com" not in anonymized
    assert "[REDACTED_EMAIL_ADDRESS]" in anonymized
    # 'redact' is not stored in mapping
    assert "[REDACTED_EMAIL_ADDRESS]" not in mapping

    # 3. LOCATION strategy: 'hash'
    # 'Berlin' should be replaced by an HMAC-SHA256 hash prefix '[HASH_...]'
    assert "Berlin" not in anonymized
    hash_replacement = next(k for k, v in mapping.items() if v == "Berlin")
    assert hash_replacement.startswith("[HASH_")
    assert hash_replacement in anonymized


def test_street_address_detection(pii_engine):
    # German address detection
    text_de = "Ich wohne in der Goethestraße 15 in Berlin."
    entities_de = pii_engine.analyze(text_de, language="de")
    entity_types_de = [e.entity_type for e in entities_de]
    assert "STREET_ADDRESS" in entity_types_de
    addr_ent_de = next(e for e in entities_de if e.entity_type == "STREET_ADDRESS")
    assert addr_ent_de.text == "Goethestraße 15"

    # English address detection
    text_en = "Please send it to 123 Main St, New York."
    entities_en = pii_engine.analyze(text_en, language="en")
    entity_types_en = [e.entity_type for e in entities_en]
    assert "STREET_ADDRESS" in entity_types_en
    addr_ent_en = next(e for e in entities_en if e.entity_type == "STREET_ADDRESS")
    assert addr_ent_en.text == "123 Main St"


def test_street_address_faker(pii_engine):
    pii_engine.set_config(
        active_entities=["STREET_ADDRESS"],
        threshold=0.35,
        entity_strategies={"STREET_ADDRESS": "faker"}
    )
    text = "Meine Adresse ist Goethestraße 15."
    entities = pii_engine.analyze(text, language="de")
    anonymized, mapping = pii_engine.anonymize(text, entities)
    
    assert "Goethestraße 15" not in anonymized
    fake_addr = next(k for k, v in mapping.items() if v == "Goethestraße 15")
    assert fake_addr in ["Musterstraße 123", "Hauptstraße 45", "Goethestraße 9", "Bahnhofstraße 22", "Schillerstraße 10"]


def test_deanonymize_substring_safety(pii_engine):
    # Test that a shorter string which is a substring of a longer string
    # does not mess up deanonymization when replaced.
    mapping = {
        "Max Müller": "Albert Einstein",
        "Max": "Isaac"
    }
    # If "Max" is replaced first, "Max Müller" becomes "Isaac Müller", and then
    # "Isaac Müller" won't match "Max Müller".
    # Sorting keys by length ensures "Max Müller" is replaced first.
    text = "Hallo Max Müller und Max."
    deanonymized = pii_engine.deanonymize(text, mapping)
    assert deanonymized == "Hallo Albert Einstein und Isaac."


def test_chunking_large_text(pii_engine):
    # Generiere einen sehr großen Text (> 9000 Zeichen) und platziere PII am Ende
    large_text = "Dies ist ein Fülltext für den Stresstest. " * 250
    large_text += " Mein Name ist Max Mustermann."
    
    entities = pii_engine.analyze(large_text, language="de")
    person_texts = [e.text for e in entities if e.entity_type == "PERSON"]
    
    assert "Max Mustermann" in person_texts


def test_left_to_right_numbering_order(pii_engine):
    # Test that entities are numbered in their natural left-to-right appearance order.
    text = "John Doe works with Jane Smith."
    entities = pii_engine.analyze(text, language="en")
    
    anonymized, mapping = pii_engine.anonymize(text, entities)
    
    # John Doe (first) should get <PERSON_0> and Jane Smith (second) should get <PERSON_1>
    assert "John Doe" not in anonymized
    assert "Jane Smith" not in anonymized
    assert "<PERSON_0> works with <PERSON_1>." in anonymized
    assert mapping["<PERSON_0>"] == "John Doe"
    assert mapping["<PERSON_1>"] == "Jane Smith"
def test_secure_hash_salt_fallback():
    # If no PII_HASH_SALT environment variable is set, it generates a fallback.
    import os
    orig_salt = os.environ.pop("PII_HASH_SALT", None)
    try:
        engine = PIIEngine()
        assert engine.hash_salt is not None
        assert len(engine.hash_salt) > 0
        # Check that it remains persistent during the engine session
        text = "My name is John Doe."
        entities = engine.analyze(text, language="en")
        engine.set_config(active_entities=["PERSON"], threshold=0.3, entity_strategies={"PERSON": "hash"})
        anon, mapping = engine.anonymize(text, entities)
        hash_val = next(k for k, v in mapping.items() if v == "John Doe")
        assert hash_val.startswith("[HASH_")
    finally:
        if orig_salt is not None:
            os.environ["PII_HASH_SALT"] = orig_salt


def test_config_update_pydantic_validation():
    from src.models import ConfigUpdate
    import pytest
    
    # 1. Test whitelist/blacklist count limits
    with pytest.raises(ValueError, match="cannot contain more than 500 items"):
        ConfigUpdate(
            active_entities=["PERSON"],
            threshold=0.35,
            mock_mode=True,
            provider="mock",
            whitelist=["item"] * 501,
            blacklist=[]
        )
        
    # 2. Test whitelist/blacklist character length limits
    with pytest.raises(ValueError, match="cannot exceed 100 characters"):
        ConfigUpdate(
            active_entities=["PERSON"],
            threshold=0.35,
            mock_mode=True,
            provider="mock",
            whitelist=["a" * 101],
            blacklist=[]
        )

