document.addEventListener("DOMContentLoaded", () => {
    // State management
    let currentConfig = null;
    let categoryCounts = {};

    // DOM Elements
    const tabs = document.querySelectorAll(".nav-item");
    const tabContents = document.querySelectorAll(".tab-content");
    const pageTitle = document.getElementById("page-title");
    const globalModeBadge = document.getElementById("global-mode-badge");
    const globalProviderBadge = document.getElementById("global-provider-badge");

    // Stat fields
    const statsTotalRequests = document.getElementById("stats-total-requests");
    const statsTotalPii = document.getElementById("stats-total-pii");
    const statsAvgLatency = document.getElementById("stats-avg-latency");
    const statsPrivacyScore = document.getElementById("stats-privacy-score");
    const categoryChart = document.getElementById("category-chart");

    // Playground Elements
    const playgroundPrompt = document.getElementById("playground-prompt");
    const playgroundLang = document.getElementById("playground-lang");
    const btnSubmitPlayground = document.getElementById("btn-submit-playground");
    const presetDe = document.getElementById("preset-de");
    const presetEn = document.getElementById("preset-en");
    
    // Flow Panels & Tabs
    const flowTabs = document.querySelectorAll(".flow-tab");
    const flowPanels = document.querySelectorAll(".flow-panel");
    const highlightedView = document.getElementById("playground-highlighted-view");
    const legendContainer = document.getElementById("detected-legend-container");
    const anonymizedTextContent = document.getElementById("anonymized-text-content");
    const responseTextContent = document.getElementById("response-text-content");
    const deanonymizedTextContent = document.getElementById("deanonymized-text-content");

    // Settings Elements
    const settingsForm = document.getElementById("settings-form");
    const settingsMockMode = document.getElementById("settings-mock-mode");
    const settingsProvider = document.getElementById("settings-provider");
    const settingsModel = document.getElementById("settings-model");
    const settingsThreshold = document.getElementById("settings-threshold");
    const thresholdValLabel = document.getElementById("threshold-val-label");
    const entitiesToggleContainer = document.getElementById("entities-toggle-container");

    // Logs Elements
    const auditLogsBody = document.getElementById("audit-logs-body");
    const btnClearLogs = document.getElementById("btn-clear-logs");

    // Modal Elements
    const logModal = document.getElementById("log-detail-modal");
    const logModalBody = document.getElementById("log-modal-body");
    const closeLogModal = document.getElementById("close-log-modal");

    // Provider Defaults Models
    const providerModelDefaults = {
        "mock": "gpt-4o",
        "openai": "gpt-4o",
        "anthropic": "claude-3-5-sonnet-20241022",
        "mistral": "mistral-large-latest",
        "gemini": "gemini-1.5-pro",
        "openrouter": "google/gemini-2.5-flash"
    };

    // Preset Prompts
    const presets = {
        de: "Hallo, ich bin Christian Schmidt. Meine Adresse lautet Goethestraße 15 in Berlin. Meine Steuer-ID ist 42938472918. Bitte senden Sie mir die Vertragsunterlagen an christian.schmidt@mail.de oder rufen Sie mich unter +49 170 1234567 an. Meine IBAN lautet DE89370400440532013000.",
        en: "Hello, this is Sarah Connor. My IP address is 192.168.1.45. You can contact my assistant at sarah.connor@cyberdyne.com or call +1-555-0199. I live in Los Angeles, California. Please charge my credit card 4111-2222-3333-4444."
    };

    /* ----------------------------------------------------
       TAB ROUTING LOGIC
       ---------------------------------------------------- */
    tabs.forEach(tab => {
        tab.addEventListener("click", (e) => {
            e.preventDefault();
            const tabName = tab.getAttribute("data-tab");

            // Update Active Tab Class
            tabs.forEach(t => t.classList.remove("active"));
            tab.classList.add("active");

            // Update Tab Content View
            tabContents.forEach(content => content.classList.remove("active"));
            document.getElementById(`tab-${tabName}`).classList.add("active");

            // Set topbar title
            pageTitle.innerText = tab.innerText.replace(/[^\w\säöüÄÖÜ-]/g, '').trim();

            // Perform tab-specific data refreshes
            if (tabName === "dashboard") {
                fetchStatsAndLogs();
            } else if (tabName === "logs") {
                fetchAuditLogs();
            } else if (tabName === "settings") {
                fetchConfig();
            }
        });
    });

    /* ----------------------------------------------------
       PLAYGROUND FLOW TAB NAVIGATION
       ---------------------------------------------------- */
    flowTabs.forEach(tab => {
        tab.addEventListener("click", () => {
            const flowName = tab.getAttribute("data-flow");
            flowTabs.forEach(t => t.classList.remove("active"));
            tab.classList.add("active");

            flowPanels.forEach(panel => panel.classList.remove("active"));
            document.getElementById(`flow-panel-${flowName}`).classList.add("active");
        });
    });

    // Preset button triggers
    presetDe.addEventListener("click", () => {
        playgroundPrompt.value = presets.de;
        playgroundLang.value = "de";
    });
    presetEn.addEventListener("click", () => {
        playgroundPrompt.value = presets.en;
        playgroundLang.value = "en";
    });

    /* ----------------------------------------------------
       API INTERACTIVE INTEGRATIONS
       ---------------------------------------------------- */

    // Load active settings from API
    async function fetchConfig() {
        try {
            const res = await fetch("/api/config");
            const data = await res.json();
            currentConfig = data;

            // Update global indicators
            globalModeBadge.innerText = data.mock_mode ? "Mock-Modus" : "Proxy-Modus";
            globalModeBadge.style.color = data.mock_mode ? "var(--accent-green)" : "var(--accent-cyan)";
            globalModeBadge.style.borderColor = data.mock_mode ? "rgba(24,220,119,0.2)" : "rgba(0,229,255,0.2)";
            globalProviderBadge.innerText = data.provider;

            // Populates Form Elements
            settingsMockMode.checked = data.mock_mode;
            settingsThreshold.value = data.threshold;
            thresholdValLabel.innerText = data.threshold.toFixed(2);
            settingsModel.value = data.model_name;
            
            // Compliance & Whitelist/Blacklist
            document.getElementById("settings-safe-logging").checked = data.safe_logging_mode;
            document.getElementById("settings-whitelist").value = data.whitelist.join(", ");
            document.getElementById("settings-blacklist").value = data.blacklist.join(", ");
            
            // Context & Performance
            document.getElementById("settings-chunking-enabled").checked = data.chunking_enabled;
            document.getElementById("settings-chunk-size").value = data.chunk_size;
            document.getElementById("settings-sliding-window-enabled").checked = data.sliding_window_enabled;
            document.getElementById("settings-max-context-tokens").value = data.max_context_tokens;

            // API Keys vault
            document.getElementById("key-openai").value = data.api_keys.openai ? "********" : "";
            document.getElementById("key-anthropic").value = data.api_keys.anthropic ? "********" : "";
            document.getElementById("key-mistral").value = data.api_keys.mistral ? "********" : "";
            document.getElementById("key-gemini").value = data.api_keys.gemini ? "********" : "";
            document.getElementById("key-openrouter").value = data.api_keys.openrouter ? "********" : "";

            // Populate provider dropdown
            settingsProvider.innerHTML = "";
            data.available_providers.forEach(p => {
                const opt = document.createElement("option");
                opt.value = p;
                opt.innerText = p.toUpperCase();
                if (p === data.provider) opt.selected = true;
                settingsProvider.appendChild(opt);
            });

            // Populate active PII category check list with strategy dropdowns
            entitiesToggleContainer.innerHTML = "";
            data.all_available_entities.forEach(ent => {
                const label = document.createElement("label");
                label.className = "entity-checkbox-label";
                
                const info = document.createElement("div");
                info.className = "entity-check-info";
                
                const title = document.createElement("span");
                title.className = "entity-check-title";
                title.innerText = ent;
                
                const desc = document.createElement("span");
                desc.className = "entity-check-desc";
                desc.innerText = getEntityDescription(ent);
                
                info.appendChild(title);
                info.appendChild(desc);
                
                // Add strategy select dropdown
                const select = document.createElement("select");
                select.className = "entity-strategy-select";
                select.dataset.entity = ent;
                select.addEventListener("click", (e) => e.stopPropagation()); // prevent toggling checkbox
                
                const strategies = [
                    { value: "placeholder", label: "Platzhalter" },
                    { value: "redact", label: "Schwärzung" },
                    { value: "hash", label: "Hashing" },
                    { value: "faker", label: "Faker" }
                ];
                
                strategies.forEach(st => {
                    const opt = document.createElement("option");
                    opt.value = st.value;
                    opt.innerText = st.label;
                    if (data.entity_strategies[ent] === st.value) opt.selected = true;
                    select.appendChild(opt);
                });
                
                const cb = document.createElement("input");
                cb.type = "checkbox";
                cb.value = ent;
                cb.checked = data.active_entities.includes(ent);
                
                label.appendChild(info);
                label.appendChild(select);
                label.appendChild(cb);
                entitiesToggleContainer.appendChild(label);
            });
        } catch (err) {
            console.error("Fehler beim Abrufen der Konfiguration:", err);
        }
    }

    // Save Settings Form
    settingsForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        // Collect checked entities
        const checkedBoxes = entitiesToggleContainer.querySelectorAll("input[type=checkbox]:checked");
        const activeEntities = Array.from(checkedBoxes).map(cb => cb.value);

        // Collect strategies
        const entityStrategies = {};
        entitiesToggleContainer.querySelectorAll(".entity-strategy-select").forEach(sel => {
            entityStrategies[sel.dataset.entity] = sel.value;
        });

        // Resolve Whitelist & Blacklist Arrays
        const whitelistRaw = document.getElementById("settings-whitelist").value;
        const blacklistRaw = document.getElementById("settings-blacklist").value;
        
        const whitelist = whitelistRaw.split(",").map(s => s.trim()).filter(s => s.length > 0);
        const blacklist = blacklistRaw.split(",").map(s => s.trim()).filter(s => s.length > 0);

        // Resolve API Keys (keeping existing if masked as ********)
        const getKeyValue = (inputId, providerKey) => {
            const val = document.getElementById(inputId).value;
            if (val === "********") {
                return currentConfig && currentConfig.api_keys ? currentConfig.api_keys[providerKey] || "" : "";
            }
            return val;
        };

        const apiKeys = {
            openai: getKeyValue("key-openai", "openai"),
            anthropic: getKeyValue("key-anthropic", "anthropic"),
            mistral: getKeyValue("key-mistral", "mistral"),
            gemini: getKeyValue("key-gemini", "gemini"),
            openrouter: getKeyValue("key-openrouter", "openrouter")
        };

        const payload = {
            active_entities: activeEntities,
            threshold: parseFloat(settingsThreshold.value),
            mock_mode: settingsMockMode.checked,
            provider: settingsProvider.value,
            model_name: settingsModel.value || providerModelDefaults[settingsProvider.value],
            whitelist: whitelist,
            blacklist: blacklist,
            entity_strategies: entityStrategies,
            api_keys: apiKeys,
            safe_logging_mode: document.getElementById("settings-safe-logging").checked,
            chunking_enabled: document.getElementById("settings-chunking-enabled").checked,
            chunk_size: parseInt(document.getElementById("settings-chunk-size").value) || 4000,
            sliding_window_enabled: document.getElementById("settings-sliding-window-enabled").checked,
            max_context_tokens: parseInt(document.getElementById("settings-max-context-tokens").value) || 12000
        };

        try {
            const res = await fetch("/api/config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (data.status === "success") {
                alert("Einstellungen wurden erfolgreich gespeichert!");
                fetchConfig();
            }
        } catch (err) {
            console.error("Fehler beim Speichern der Konfiguration:", err);
            alert("Fehler beim Speichern.");
        }
    });

    // Auto-update default model name when provider changes
    settingsProvider.addEventListener("change", () => {
        const prov = settingsProvider.value;
        if (providerModelDefaults[prov]) {
            settingsModel.value = providerModelDefaults[prov];
        }
    });

    // Threshold range update listener
    settingsThreshold.addEventListener("input", () => {
        thresholdValLabel.innerText = parseFloat(settingsThreshold.value).toFixed(2);
    });

    /* ----------------------------------------------------
       PLAYGROUND: SUBMIT PROMPT & FLOW RENDERER
       ---------------------------------------------------- */
    btnSubmitPlayground.addEventListener("click", async () => {
        const text = playgroundPrompt.value.trim();
        const lang = playgroundLang.value;

        if (!text) {
            alert("Bitte gib zuerst einen Prompt ein.");
            return;
        }

        btnSubmitPlayground.innerText = "Verarbeite...";
        btnSubmitPlayground.disabled = true;

        try {
            // Step 1: Run local PII analysis
            const analyzeRes = await fetch("/api/analyze", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text, language: lang })
            });
            const entities = await analyzeRes.json();

            // Render entities live on tab 1
            renderPIIHighlights(text, entities);

            // Step 2: Query OpenAI-compatible completions endpoint
            const chatRes = await fetch("/v1/chat/completions", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    model: currentConfig ? currentConfig.model_name : "gpt-4o",
                    messages: [{ role: "user", content: text }]
                })
            });
            
            const chatData = await chatRes.json();
            
            if (chatData.error) {
                alert(`Fehler von LLM-Proxy: ${chatData.error.message}`);
                btnSubmitPlayground.innerText = "Anfrage Senden";
                btnSubmitPlayground.disabled = false;
                return;
            }

            // Successfully received response. Let's pull the latest log entry to get exact masked values.
            const logRes = await fetch("/api/logs?limit=1");
            const logs = await logRes.json();
            
            if (logs.length > 0) {
                const latestLog = logs[0];
                anonymizedTextContent.innerText = latestLog.anonymized_prompt;
                responseTextContent.innerText = latestLog.llm_response;
                deanonymizedTextContent.innerText = latestLog.deanonymized_response;
            } else {
                // Fallback
                anonymizedTextContent.innerText = "Gateway anonymized the prompt successfully.";
                responseTextContent.innerText = chatData.choices[0].message.content;
                deanonymizedTextContent.innerText = chatData.choices[0].message.content;
            }

            // Auto-switch flow tab to highlights or deanonymized
            document.querySelector(".flow-tab[data-flow='highlight']").click();

        } catch (err) {
            console.error("Playground submission failed:", err);
            alert("Verbindungsfehler zum LLM-Gateway.");
        } finally {
            btnSubmitPlayground.innerText = "Anfrage Senden";
            btnSubmitPlayground.disabled = false;
        }
    });

    // Custom Highlighter renderer
    function renderPIIHighlights(text, entities) {
        if (entities.length === 0) {
            highlightedView.innerHTML = `<span class="placeholder-text">Keine personenbezogenen Daten (PII) im Prompt erkannt!</span>`;
            legendContainer.innerHTML = "";
            return;
        }

        // Build HTML with badges
        let htmlResult = "";
        let currentIndex = 0;
        const legendTypes = new Set();

        entities.forEach(ent => {
            // Text before entity
            htmlResult += escapeHTML(text.slice(currentIndex, ent.start));
            // Wrap entity in colored badge with tooltip
            const tooltip = `${ent.entity_type} (Konfidenz: ${(ent.score * 100).toFixed(0)}%)`;
            htmlResult += `<span class="pii-badge ${ent.entity_type}" data-tooltip="${tooltip}">${escapeHTML(ent.text)}</span>`;
            
            legendTypes.add(ent.entity_type);
            currentIndex = ent.end;
        });

        // Remaining text
        htmlResult += escapeHTML(text.slice(currentIndex));
        highlightedView.innerHTML = htmlResult;

        // Render Legend Badges
        legendContainer.innerHTML = "<h4>Erkannte Kategorien:</h4>";
        legendTypes.forEach(type => {
            const badge = document.createElement("span");
            badge.className = `pii-badge ${type}`;
            badge.innerText = type;
            legendContainer.appendChild(badge);
        });
    }

    /* ----------------------------------------------------
       DASHBOARD: STATS AND STATISTICAL LOGS
       ---------------------------------------------------- */
    async function fetchStatsAndLogs() {
        try {
            const res = await fetch("/api/logs?limit=50");
            const logs = await res.json();
            
            // Calculate stats
            const totalRequests = logs.length;
            let totalPii = 0;
            let totalLatency = 0;
            let avgPrivacyScore = 0.0;
            categoryCounts = {};

            logs.forEach(log => {
                totalPii += log.entities_masked_count;
                totalLatency += log.latency_ms;
                avgPrivacyScore += log.privacy_score;
                
                // Track category frequencies
                if (log.entities_details && Array.isArray(log.entities_details)) {
                    log.entities_details.forEach(e => {
                        const t = e.entity_type;
                        categoryCounts[t] = (categoryCounts[t] || 0) + 1;
                    });
                }
            });

            const avgLat = totalRequests > 0 ? Math.round(totalLatency / totalRequests) : 0;
            const avgPrivacy = totalRequests > 0 ? Math.round((avgPrivacyScore / totalRequests) * 100) : 0;

            // Render stats
            statsTotalRequests.innerText = totalRequests;
            statsTotalPii.innerText = totalPii;
            statsAvgLatency.innerText = `${avgLat}ms`;
            statsPrivacyScore.innerText = `${avgPrivacy}%`;

            // Draw Category Progress Bars
            renderCategoryChart();

        } catch (err) {
            console.error("Fehler beim Laden der Statistiken:", err);
        }
    }

    function renderCategoryChart() {
        const sortedCategories = Object.entries(categoryCounts).sort((a,b) => b[1] - a[1]);
        if (sortedCategories.length === 0) {
            categoryChart.innerHTML = `<p class="no-data-msg">Noch keine PII-Kategorien erfasst. Bitte nutze zuerst den Playground.</p>`;
            return;
        }

        categoryChart.innerHTML = "";
        const maxCount = Math.max(...sortedCategories.map(x => x[1]));

        sortedCategories.forEach(([category, count]) => {
            const percent = (count / maxCount) * 100;
            const row = document.createElement("div");
            row.className = "chart-row";
            row.innerHTML = `
                <div class="chart-row-header">
                    <span>${category}</span>
                    <span>${count}x</span>
                </div>
                <div class="chart-bar-outer">
                    <div class="chart-bar-inner" style="width: ${percent}%"></div>
                </div>
            `;
            categoryChart.appendChild(row);
        });
    }

    /* ----------------------------------------------------
       AUDIT LOG DETAILS & LIST VIEWER
       ---------------------------------------------------- */
    async function fetchAuditLogs() {
        try {
            const res = await fetch("/api/logs?limit=50");
            const logs = await res.json();
            
            if (logs.length === 0) {
                auditLogsBody.innerHTML = `<tr><td colspan="7" class="text-center">Keine Logs vorhanden.</td></tr>`;
                return;
            }

            auditLogsBody.innerHTML = "";
            logs.forEach(log => {
                const tr = document.createElement("tr");
                const date = new Date(log.timestamp).toLocaleString("de-DE");
                const privacyClass = log.privacy_score > 0.15 ? "medium" : "high";
                const privacyText = log.privacy_score > 0 ? `${Math.round(log.privacy_score * 100)}%` : "0%";

                tr.innerHTML = `
                    <td><strong>#${log.id}</strong></td>
                    <td>${date}</td>
                    <td><span class="gateway-provider-badge">${log.provider}</span></td>
                    <td>${log.entities_masked_count} Entities</td>
                    <td><span class="score-badge ${privacyClass}">${privacyText}</span></td>
                    <td>${log.latency_ms}ms</td>
                    <td><button class="btn btn-sm btn-outline view-log-btn" data-id="${log.id}">Details</button></td>
                `;
                auditLogsBody.appendChild(tr);
            });

            // Bind click to Details buttons
            document.querySelectorAll(".view-log-btn").forEach(btn => {
                btn.addEventListener("click", () => {
                    const logId = parseInt(btn.getAttribute("data-id"));
                    const logItem = logs.find(l => l.id === logId);
                    if (logItem) showLogDetailsModal(logItem);
                });
            });

        } catch (err) {
            console.error("Fehler beim Abrufen der Logs:", err);
        }
    }

    function showLogDetailsModal(log) {
        const date = new Date(log.timestamp).toLocaleString("de-DE");
        
        let entitiesHtml = "";
        if (log.entities_details && log.entities_details.length > 0) {
            log.entities_details.forEach(e => {
                entitiesHtml += `<span class="pii-badge ${e.entity_type}">${e.entity_type}: "${escapeHTML(e.text)}" (Score: ${e.score.toFixed(2)})</span>`;
            });
        } else {
            entitiesHtml = "<span class='placeholder-text'>Keine maskierten Entitäten registriert.</span>";
        }

        logModalBody.innerHTML = `
            <div class="modal-meta-row">
                <div class="meta-field">ID: <strong>#${log.id}</strong></div>
                <div class="meta-field">Zeit: <strong>${date}</strong></div>
                <div class="meta-field">Provider: <strong>${log.provider.toUpperCase()} (${log.model_name || 'N/A'})</strong></div>
                <div class="meta-field">Latenz: <strong>${log.latency_ms}ms</strong></div>
                <div class="meta-field">Privacy Score: <strong>${Math.round(log.privacy_score * 100)}%</strong></div>
            </div>

            <div class="modal-text-block">
                <h4>Erkannte Entitäten</h4>
                <div class="modal-entities-list">
                    ${entitiesHtml}
                </div>
            </div>

            <div class="modal-grid-cols">
                <div class="modal-text-block">
                    <h4>Originaler Prompt (Client)</h4>
                    <div class="text-box">${escapeHTML(log.original_prompt)}</div>
                </div>
                <div class="modal-text-block anonymized">
                    <h4>Anonymisierter Prompt (an LLM)</h4>
                    <div class="text-box">${escapeHTML(log.anonymized_prompt)}</div>
                </div>
            </div>

            <div class="modal-grid-cols">
                <div class="modal-text-block anonymized">
                    <h4>LLM-Antwort (Maskiert)</h4>
                    <div class="text-box">${escapeHTML(log.llm_response)}</div>
                </div>
                <div class="modal-text-block deanonymized">
                    <h4>De-Anonymisierte Antwort (an Client)</h4>
                    <div class="text-box">${escapeHTML(log.deanonymized_response)}</div>
                </div>
            </div>
        `;

        logModal.classList.add("active");
    }

    // Clear Logs API call
    btnClearLogs.addEventListener("click", async () => {
        if (!confirm("Möchtest du wirklich alle Audit-Logs unwiderruflich löschen?")) return;
        try {
            const res = await fetch("/api/logs/clear", { method: "POST" });
            const data = await res.json();
            if (data.status === "success") {
                fetchAuditLogs();
            }
        } catch (err) {
            console.error("Fehler beim Löschen der Logs:", err);
        }
    });

    // Close Modal Event Handlers
    closeLogModal.addEventListener("click", () => {
        logModal.classList.remove("active");
    });

    window.addEventListener("click", (e) => {
        if (e.target === logModal) {
            logModal.classList.remove("active");
        }
    });

    /* ----------------------------------------------------
       HELPERS & DESCRIPTIONS
       ---------------------------------------------------- */
    function getEntityDescription(entity) {
        const desc = {
            "PERSON": "Vollständige Namen, Vornamen, Nachnamen",
            "EMAIL_ADDRESS": "E-Mail-Adressen (z. B. name@domain.de)",
            "PHONE_NUMBER": "Internationale und allgemeine Telefonnummern",
            "DE_PHONE_NUMBER": "Deutsche Mobilfunk- und Festnetznummern",
            "IP_ADDRESS": "IPv4 und IPv6 IP-Adressen",
            "CREDIT_CARD": "Kreditkartennummern aller großen Anbieter",
            "CRYPTO": "Kryptowährungs-Wallet-Adressen (Bitcoin, Ethereum etc.)",
            "IBAN_CODE": "Internationale Bankkontonummern (IBAN)",
            "DE_TAX_ID": "Deutsche Steueridentifikationsnummer (11 Ziffern)",
            "DE_STEUERNR": "Deutsche Steuernummern der Länderfinanzämter",
            "DE_LICENSE_PLATE": "Deutsche Kfz-Kennzeichen (z. B. B-MW 1234)",
            "DE_ID_CARD": "Deutsche Personalausweisnummern (9-stellig)",
            "LOCATION": "Städte, Länder, Straßen, Ortsangaben",
            "STREET_ADDRESS": "Straßenname und Hausnummer (z. B. Goethestraße 15)"
        };
        return desc[entity] || "Sensibler Identifikations-Informationstyp";
    }

    function escapeHTML(str) {
        return str
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Initialize UI on load
    fetchConfig();
    fetchStatsAndLogs();
});
