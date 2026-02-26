// ── Model allowlist ──────────────────────────────────────────────────────────

// ── API Key Setup Wizard ──────────────────────────────────────────────────

const WIZARD_STEPS = [
    {
        title: "Why do I need an API key?",
        body: `
            <p>LLM Grader uses OpenAI language models to grade your submissions.
            A limited number of tokens are available for free for community usage on certain models.</p>
            <p>To use the grading service when these tokens are exceeded, or on
            models not covered by the community service, you need a personal <strong>OpenAI API key</strong>.
            Your key is stored only in your browser and is <em>never</em> sent to the
            LLM Grader server.</p>
            <p>Click <strong>Next</strong> to learn how to get one.</p>
        `
    },
    {
        title: "Create an OpenAI API key",
        body: `
            <ol>
                <li>Visit <a href="https://platform.openai.com/api-keys" target="_blank">
                    https://platform.openai.com/api-keys</a>.</li>
                <li>Log in, or create a free OpenAI account.</li>
                <li>Click <strong>Create new secret key</strong>, give it a name,
                    and click <strong>Create secret key</strong>.</li>
                <li>Copy the key &mdash; it starts with <code>sk-</code>.
                    <em>You won’t be able to see it again after closing the dialog.</em></li>
            </ol>
            <p>Once you have copied the key, click <strong>Next</strong>.</p>
        `
    },
    {
        title: "Enter your key in LLM Grader",
        body: `
            <ol>
                <li>Open <strong>File &rarr; Preferences</strong> in LLM Grader.</li>
                <li>Paste your key into the <strong>OpenAI API key</strong> field.</li>
                <li>Click <strong>Save</strong>.</li>
            </ol>
            <p>Your key is stored only in your browser and is never sent to the server.</p>
        `
    },
    {
        title: "You\u2019re all set!",
        body: `
            <p>Once you have saved your API key, click <strong>Grade</strong> again
            to grade your submission.</p>
            <p>If you ever need to update your key, open
            <strong>File &rarr; Preferences</strong>.</p>
        `
    }
];

let _wizardStep = 0;
let _wizardReason = null;

function openApiKeyWizard(reason) {
    _wizardStep = 0;
    _wizardReason = (reason && reason.trim()) ? reason.trim() : null;
    _renderWizardStep();
    document.getElementById("api-key-wizard-modal").style.display = "flex";
}

function _renderWizardStep() {
    const step = WIZARD_STEPS[_wizardStep];
    document.getElementById("wizard-title").textContent = step.title;

    let bodyHtml = step.body;
    if (_wizardStep === 0 && _wizardReason) {
        bodyHtml = `<p>${_wizardReason}</p>\n` + bodyHtml;
    }
    document.getElementById("wizard-body").innerHTML = bodyHtml;

    const indicator = document.getElementById("wizard-step-indicator");
    if (indicator) indicator.textContent = `Step ${_wizardStep + 1} of ${WIZARD_STEPS.length}`;

    const backBtn = document.getElementById("wizard-back-btn");
    const nextBtn = document.getElementById("wizard-next-btn");
    backBtn.disabled = _wizardStep === 0;
    nextBtn.textContent = _wizardStep === WIZARD_STEPS.length - 1 ? "Finish" : "Next";
}

function _closeWizard() {
    document.getElementById("api-key-wizard-modal").style.display = "none";
}

function initializeApiKeyWizard() {
    const modal = document.getElementById("api-key-wizard-modal");
    if (!modal || modal.dataset.initialized === "true") return;

    document.getElementById("wizard-back-btn").addEventListener("click", () => {
        if (_wizardStep > 0) { _wizardStep--; _renderWizardStep(); }
    });

    document.getElementById("wizard-next-btn").addEventListener("click", () => {
        if (_wizardStep < WIZARD_STEPS.length - 1) {
            _wizardStep++;
            _renderWizardStep();
        } else {
            _closeWizard();
        }
    });

    document.getElementById("wizard-cancel-btn").addEventListener("click", _closeWizard);

    modal.addEventListener("click", (e) => {
        if (e.target === modal) _closeWizard();
    });

    modal.dataset.initialized = "true";
}

window.openApiKeyWizard = openApiKeyWizard;
window.initializeApiKeyWizard = initializeApiKeyWizard;

// ──────────────────────────────────────────────────────────

let adminAllowedModels = [];

function renderAdminModelList(allowedModels) {
    const container = document.getElementById("admin-model-list");
    if (!container) return;
    container.innerHTML = "";

    Object.keys(MODEL_PROVIDER).forEach(modelName => {
        const row = document.createElement("div");
        row.className = "model-row";
        row.style.cssText = "display:flex; align-items:center; gap:8px; margin:4px 0;";

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "model-allowed-checkbox";
        checkbox.dataset.model = modelName;
        checkbox.checked = allowedModels.includes(modelName);
        checkbox.addEventListener("change", () => {
            if (checkbox.checked) {
                if (!adminAllowedModels.includes(modelName)) {
                    adminAllowedModels.push(modelName);
                }
            } else {
                adminAllowedModels = adminAllowedModels.filter(m => m !== modelName);
            }
        });

        const lbl = document.createElement("label");
        lbl.textContent = modelName;
        lbl.style.fontWeight = "normal";

        row.appendChild(checkbox);
        row.appendChild(lbl);
        container.appendChild(row);
    });
}

// ── Admin Preferences Modal ───────────────────────────────────────────────────

async function saveAdminPreferences(closeModal) {
    const openaiKey = (document.getElementById("admin-openai-token")?.value ?? "").trim();
    const hfToken   = (document.getElementById("admin-hf-token")?.value ?? "").trim();

    const checkboxes = document.querySelectorAll("#admin-model-list .model-allowed-checkbox");
    const allowedModels = Array.from(checkboxes)
        .filter(cb => cb.checked)
        .map(cb => cb.dataset.model);

    const limitRaw  = document.getElementById("admin-token-limit")?.value;
    const period    = document.getElementById("admin-token-period")?.value ?? "hour";

    const prefs = {
        openaiApiKey:  openaiKey,
        hfToken:       hfToken,
        allowedModels: allowedModels,
        tokenLimit: {
            limit:  limitRaw !== undefined && limitRaw !== "" ? Number(limitRaw) : 0,
            period: period
        }
    };

    await fetch("/api/admin/preferences", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(prefs)
    });

    closeModal();
}

function initializeAdminPreferencesModal() {
    const adminPreferencesMenuItem = document.getElementById("admin-preferences-menu-item");
    const adminPreferencesModal = document.getElementById("admin-preferences-modal");
    const adminPreferencesCancelBtn = document.getElementById("admin-preferences-cancel-btn");
    const adminPreferencesSaveBtn = document.getElementById("admin-preferences-save-btn");

    if (!adminPreferencesMenuItem || !adminPreferencesModal) {
        return;
    }

    if (adminPreferencesModal.dataset.initialized === "true") {
        return;
    }

    const closeAdminPreferencesModal = () => {
        adminPreferencesModal.style.display = "none";
    };

    adminPreferencesMenuItem.addEventListener("click", async () => {
        try {
            const resp = await fetch("/api/admin/preferences");
            const prefs = await resp.json();

            const openaiInput = document.getElementById("admin-openai-token");
            if (openaiInput) openaiInput.value = prefs.openaiApiKey ?? "";

            const hfInput = document.getElementById("admin-hf-token");
            if (hfInput) hfInput.value = prefs.hfToken ?? "";

            const limitInput = document.getElementById("admin-token-limit");
            if (limitInput) limitInput.value = prefs.tokenLimit?.limit ?? 0;

            const periodSelect = document.getElementById("admin-token-period");
            if (periodSelect) periodSelect.value = prefs.tokenLimit?.period ?? "per_hour";

            adminAllowedModels = Array.isArray(prefs.allowedModels) ? prefs.allowedModels : [];
        } catch (e) {
            adminAllowedModels = [];
        }

        renderAdminModelList(adminAllowedModels);
        adminPreferencesModal.style.display = "flex";
    });

    if (adminPreferencesCancelBtn) {
        adminPreferencesCancelBtn.addEventListener("click", () => {
            closeAdminPreferencesModal();
        });
    }

    adminPreferencesModal.addEventListener("click", (event) => {
        if (event.target === adminPreferencesModal) {
            closeAdminPreferencesModal();
        }
    });

    adminPreferencesModal.dataset.initialized = "true";

    if (adminPreferencesSaveBtn) {
        adminPreferencesSaveBtn.addEventListener("click", () => {
            saveAdminPreferences(closeAdminPreferencesModal);
        });
    }
}

window.initializeAdminPreferencesModal = initializeAdminPreferencesModal;
