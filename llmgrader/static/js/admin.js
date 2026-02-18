function initializeAdminPreferencesModal() {
    const adminPreferencesMenuItem = document.getElementById("admin-preferences-menu-item");
    const adminPreferencesModal = document.getElementById("admin-preferences-modal");
    const adminPreferencesCancelBtn = document.getElementById("admin-preferences-cancel-btn");
    const adminPreferencesSaveBtn = document.getElementById("admin-preferences-save-btn");
    const adminHfTokenInput = document.getElementById("admin-hf-token");


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
        if (adminHfTokenInput) {
            const resp = await fetch("/api/admin/hf-token");
            const data = await resp.json();
            adminHfTokenInput.value = data.token || "";
        }

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
        adminPreferencesSaveBtn.addEventListener("click", async () => {
            const token = adminHfTokenInput ? adminHfTokenInput.value : "";
            await fetch("/api/admin/hf-token", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ token })
            });

            closeAdminPreferencesModal();
        });
    }
}

window.initializeAdminPreferencesModal = initializeAdminPreferencesModal;
