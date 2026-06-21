# DSGVO Privacy Gateway für LLMs - Konzept & Detailanalyse

## Projektübersicht
Das **DSGVO Privacy Gateway** ist ein datenschutzkonformer Proxy-Service, der zwischen Endnutzer-Anwendungen (bzw. Entwicklern) und öffentlichen LLM-APIs (wie OpenAI, Anthropic, Mistral, Google Gemini, OpenRouter) geschaltet wird.
Der Hauptzweck besteht darin, in Prompts enthaltene personenbezogene Daten (Personally Identifiable Information - PII) automatisch zu erkennen und zu pseudonymisieren/anonymisieren, **bevor** sie an externe (häufig US-basierte) Cloud-Anbieter gesendet werden. Die vom LLM generierte Antwort wird auf dem Rückweg wieder in den ursprünglichen Kontext de-anonymisiert. Dies ermöglicht die rechtssichere, DSGVO-konforme Nutzung von KI in Unternehmensumfeldern.

## Kernfunktionen im Detail

### 1. Bidirektionales PII-Mapping
- **Hinweg (Pseudonymisierung):** Sensible Daten im User-Prompt werden erkannt und durch Index-basierte Platzhalter ersetzt (z.B. wird "Max Mustermann" zu `<PERSON_0>`, eine Mailadresse zu `<EMAIL_ADDRESS_0>`).
- **Rückweg (De-Anonymisierung):** Wenn das LLM mit dem Platzhalter antwortet (z.B. "Hallo `<PERSON_0>`"), übersetzt das Gateway den Platzhalter wieder zurück in den Originalwert ("Hallo Max Mustermann"), bevor der Nutzer die Antwort sieht.

### 2. Drop-in Kompatibilität (OpenAI-Standard)
- Das Gateway stellt einen Standard-Endpunkt (`/v1/chat/completions`) bereit.
- Vorhandene Anwendungen müssen nicht umgeschrieben werden. Es reicht aus, die `base_url` des OpenAI-Clients auf das lokale Gateway zu ändern.

### 3. Dynamisches Model-Routing & Payload-Übersetzung
- Anfragen können durch spezielle Model-Namen gezielt an bestimmte Provider geroutet werden (z.B. `anthropic/claude-3-5-sonnet` oder `openai/gpt-4o`).
- Das Gateway übersetzt die standardisierten OpenAI-Request-Bodys in das native Format der jeweiligen Anbieter (Anthropic, Gemini, etc.).

### 4. Performance & Kontext-Management
- **Chunking (Text-Segmentierung):** Große Eingaben werden in überlappende Chunks zerlegt, um die Analyse durch SpaCy performant zu halten und Out-Of-Memory-Fehler zu vermeiden.
- **Sliding Window:** Verhindert das Überschreiten des LLM-Kontext-Limits, indem ältere Nachrichten verworfen werden, während der System-Prompt geschützt bleibt.
- **Lokales, sicheres RAG:** Dokumente können hochgeladen, lokal anonymisiert und in einer SQLite-Datenbank vektorisiert/durchsucht werden, bevor sie sicher an das LLM gehen.

## Architektur & Datenfluss

Der Datenfluss läuft über das Gateway als intelligente Middleware:
1. **Client** sendet Request mit PII.
2. **Gateway** fordert NER-Analyse (Named Entity Recognition) über Presidio & SpaCy an.
3. **Erkennung:** PII wird identifiziert.
4. **Mapping:** Gateway erstellt Platzhalter und speichert das Mapping lokal.
5. **Forwarding:** Anonymisierter Prompt geht an das externe LLM.
6. **Response:** LLM antwortet mit Platzhaltern.
7. **Wiederherstellung:** Gateway ersetzt Platzhalter durch die Originaldaten.
8. **Logging:** Metadaten der Transaktion (ohne sensible Inhalte bei aktiviertem Safe-Logging) werden in einer SQLite-Datenbank (Audit-Log) gespeichert.
9. **Auslieferung:** Bereinigte Antwort geht an den Client.

## Erkennbare PII-Kategorien (Fokus: Deutschland)
Neben den Standardkategorien (Namen, E-Mails, Telefonnummern, IP-Adressen, Kreditkarten, Orte) implementiert das Gateway maßgeschneiderte deutsche Erkennungslogiken (Custom Recognizers):
- **Steueridentifikationsnummer** (German Tax ID)
- **Steuernummer** (German Tax Number)
- **Kfz-Kennzeichen** (German Vehicle License Plates)
- **Personalausweisnummer** (German Identity Card Numbers)
- **Lokalisierte Telefonnummern & IBANs**

## Technologie-Stack
- **Backend:** Python 3.10+, FastAPI (asynchrones API-Framework)
- **NLP & PII-Erkennung:** Microsoft Presidio in Kombination mit SpaCy (Sprachmodelle: `en_core_web_sm`, `de_core_news_sm`)
- **Datenbank:** SQLite (für Audit-Logs und persistente Mappings)
- **Sicherheit:** Cryptography / Fernet (für AES-128 Verschlüsselung des API Key Vaults)
- **Frontend (Dashboard):** HTML, Vanilla CSS (Glassmorphism Dark Theme, HSL Colors), Vanilla JavaScript

## Enterprise- und Sicherheits-Features (V2)
- **Symmetrischer API Key Vault:** Externe API-Schlüssel werden lokal via Fernet verschlüsselt gespeichert und verwaltet, sodass sie nie im Klartext im Code liegen.
- **Whitelist & Blacklist:** Spezifische Begriffe können von der Maskierung ausgenommen (Whitelist) oder explizit immer maskiert werden (Blacklist).
- **Flexible Maskierungsstrategien:** Pro PII-Kategorie kann entschieden werden, wie maskiert wird:
  - *Placeholder* (`<PERSON_0>`)
  - *Redact* (Einfach löschen / schwärzen)
  - *Hash* (MD5-Hash)
  - *Faker* (Generierung synthetischer Fake-Daten)
- **Safe-Logging Compliance Mode:** Sorgt dafür, dass in der SQLite-Datenbank absolut keine sensiblen Prompt- oder Response-Inhalte protokolliert werden, sondern lediglich Performance-Metriken und PII-Statistiken.

## Projektstruktur (Auszug)
- `/src/main.py`: FastAPI App-Definition und Endpunkte (`/api/analyze`, `/api/config`, `/api/logs`).
- `/src/gateway.py`: Proxy-Logik, LLM-Routing, Request-Übersetzung und Bidirektionales Mapping.
- `/src/pii_engine.py`: Integration von Presidio, SpaCy, Custom Recognizers und Maskierungsstrategien.
- `/src/config.py` & `/src/models.py`: Pydantic Models, Konfigurationsmanagement, API Key Vault.
- `/src/static/`: Frontend-Dateien für das Sleek Web Dashboard (HTML, CSS, JS).
- `/tests/`: Unit- und Integrationstests (pytest).
- `/run.py`: Startup-Skript für automatisiertes Setup (Venv, Abhängigkeiten, SpaCy-Modelle).
- `gateway_logs.db`: Die SQLite-Datenbank für Audit-Trail und Logs.
