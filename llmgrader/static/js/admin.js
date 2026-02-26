// ── Model allowlist ──────────────────────────────────────────────────────────

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
