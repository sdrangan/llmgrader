function initializeMenuSystem() {
    var menuBar = document.querySelector('.top-menu-bar');
    var viewMenus = Array.prototype.slice.call(document.querySelectorAll('.view-menu'));
    var viewButtons = Array.prototype.slice.call(document.querySelectorAll('[data-view]'));
    var menuButtons = Array.prototype.slice.call(document.querySelectorAll('.menu-button'));

    function setActiveView(viewName) {
        viewMenus.forEach(function (menu) {
            var isActive = menu.getAttribute('data-view') === viewName;
            menu.classList.toggle('is-active', isActive);
        });
        if (document.body) {
            document.body.setAttribute('data-active-view', viewName);
        }
        
        // dropdown visibility updated per view
        var unitDropdowns = Array.prototype.slice.call(document.querySelectorAll('.unit-dropdown'));
        var gradeOnlyDropdowns = Array.prototype.slice.call(document.querySelectorAll('.grade-only'));
        var dashboardOnly = Array.prototype.slice.call(
            document.querySelectorAll('.dashboard-only')
        );

        if (viewName === 'dashboard') {
            // Dashboard: show unit dropdown only
            unitDropdowns.forEach(function (el) { el.style.display = ''; });
            gradeOnlyDropdowns.forEach(function (el) { el.style.display = 'none'; });
            dashboardOnly.forEach(function (el) { el.style.display = ''; });
        } else if (viewName === 'grade') {
            // Grade: show unit dropdown and all grade-only dropdowns
            unitDropdowns.forEach(function (el) { el.style.display = ''; });
            gradeOnlyDropdowns.forEach(function (el) { el.style.display = ''; });
            dashboardOnly.forEach(function (el) { el.style.display = 'none'; });
        } else {
            // Admin and Analytics: hide all dropdowns
            unitDropdowns.forEach(function (el) { el.style.display = 'none'; });
            gradeOnlyDropdowns.forEach(function (el) { el.style.display = 'none'; });
            dashboardOnly.forEach(function (el) { el.style.display = 'none'; });
        }
    }

    // Expose setActiveView globally so it can be called from loadView
    window.setActiveView = setActiveView;

    function closeMenus() {
        if (!menuBar) {
            return;
        }
        menuBar.classList.add('menu-closed');
    }

    function openMenus() {
        if (!menuBar) {
            return;
        }
        menuBar.classList.remove('menu-closed');
    }

    function isAdminView(viewName) {
        return viewName === 'admin' || viewName === 'analytics';
    }

    function isAdminLoggedIn() {
        return sessionStorage.getItem('isAdmin') === 'true';
    }

    viewButtons.forEach(function (button) {
        button.addEventListener('click', function () {
            var viewName = button.getAttribute('data-view');
            if (isAdminView(viewName) && !isAdminLoggedIn()) {
                alert('Admin login required');
                closeMenus();
                return;
            }
            setActiveView(viewName);
            // Load the view dynamically
            if (typeof loadView === 'function') {
                loadView(viewName);
            }
            closeMenus();
        });
    });

    menuButtons.forEach(function (button) {
        button.addEventListener('mouseenter', openMenus);
        button.addEventListener('focus', openMenus);
    });

    var editCutMenuItem = document.getElementById('edit-cut-menu-item');
    var editCopyMenuItem = document.getElementById('edit-copy-menu-item');
    var editPasteMenuItem = document.getElementById('edit-paste-menu-item');
    var editDeleteMenuItem = document.getElementById('edit-delete-menu-item');

    function getActiveEditableElement() {
        var el = document.activeElement;
        if (!el) {
            return null;
        }
        if (el.isContentEditable) {
            return el;
        }
        var tag = el.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA') {
            return el;
        }
        return null;
    }

    function updateEditMenuState() {
        var hasEditable = Boolean(getActiveEditableElement());

        if (editCutMenuItem) {
            editCutMenuItem.disabled = !hasEditable;
        }
        if (editCopyMenuItem) {
            editCopyMenuItem.disabled = !hasEditable;
        }
        if (editDeleteMenuItem) {
            editDeleteMenuItem.disabled = !hasEditable;
        }
        if (editPasteMenuItem) {
            editPasteMenuItem.disabled = false;
        }
    }

    window.editCut = function () {
        if (!getActiveEditableElement()) {
            return;
        }
        document.execCommand('cut');
    };

    window.editCopy = function () {
        if (!getActiveEditableElement()) {
            return;
        }
        document.execCommand('copy');
    };

    window.editPaste = function () {
        document.execCommand('paste');
    };

    window.editDelete = function () {
        if (!getActiveEditableElement()) {
            return;
        }
        document.execCommand('delete');
    };

    document.addEventListener('focusin', updateEditMenuState);
    document.addEventListener('selectionchange', updateEditMenuState);
    updateEditMenuState();

    (function setupGradeDivider() {
        var divider = document.querySelector('.grade-layout .divider');
        var topPanel = document.getElementById('grade-question-panel');
        var bottomPanel = document.getElementById('grade-solution-panel');

        if (!divider || !topPanel || !bottomPanel || divider.dataset.bound === 'true') {
            return;
        }

        divider.dataset.bound = 'true';
        var dragging = false;

        divider.addEventListener('mousedown', function () {
            dragging = true;
            document.body.style.userSelect = 'none';
        });

        document.addEventListener('mouseup', function () {
            dragging = false;
            document.body.style.userSelect = '';
        });

        document.addEventListener('mousemove', function (e) {
            if (!dragging) {
                return;
            }

            var container = divider.parentElement;
            if (!container) {
                return;
            }

            var containerHeight = container.offsetHeight;
            var newTopHeight = e.clientY - container.offsetTop;

            if (newTopHeight < 100 || newTopHeight > containerHeight - 100) {
                return;
            }

            topPanel.style.flex = '0 0 ' + newTopHeight + 'px';
            bottomPanel.style.flex = '1 1 auto';
        });
    })();

    // Preferences modal functionality
    var preferencesMenuItem = document.getElementById('preferences-menu-item');
    var settingsGearBtn = document.getElementById('settings-gear-btn');
    var preferencesModal = document.getElementById('preferences-modal');
    var preferencesSaveBtn = document.getElementById('preferences-save-btn');
    var preferencesCancelBtn = document.getElementById('preferences-cancel-btn');
    var preferencesModelSelect = document.getElementById('model-select');
    var preferencesTimeoutInput = document.getElementById('timeout-input');

    function maskKey(key) {
        if (!key) return '';
        if (key.length <= 8) return key[0] + '****' + key[key.length - 1];
        return key.slice(0, 4) + '***' + key.slice(-4);
    }

    function populateKeyFields() {
        var openaiKey = localStorage.getItem('openai_api_key') || '';
        var hfKey = localStorage.getItem('hfToken') || '';

        var okInput = document.getElementById('openai-key-input');
        var okArea  = document.getElementById('openai-key-textarea');
        var okBtn   = document.getElementById('openai-key-toggle');
        var hfInput = document.getElementById('hf-key-input');
        var hfArea  = document.getElementById('hf-key-textarea');
        var hfBtn   = document.getElementById('hf-key-toggle');

        if (okInput) { okInput.dataset.realValue = openaiKey; okInput.value = maskKey(openaiKey); }
        if (okArea)  { okArea.value = ''; okArea.classList.add('hidden'); }
        if (okBtn)   { okBtn.textContent = 'Show'; okBtn.dataset.state = 'masked'; }

        if (hfInput) { hfInput.dataset.realValue = hfKey; hfInput.value = maskKey(hfKey); }
        if (hfArea)  { hfArea.value = ''; hfArea.classList.add('hidden'); }
        if (hfBtn)   { hfBtn.textContent = 'Show'; hfBtn.dataset.state = 'masked'; }

        if (okInput) okInput.classList.remove('hidden');
        if (hfInput) hfInput.classList.remove('hidden');
    }

    function setupKeyToggle(inputId, areaId, btnId) {
        var input = document.getElementById(inputId);
        var area  = document.getElementById(areaId);
        var btn   = document.getElementById(btnId);
        if (!input || !area || !btn) return;
        btn.addEventListener('click', function () {
            var real = input.dataset.realValue || '';
            if (btn.dataset.state === 'masked') {
                area.value = real;
                input.classList.add('hidden');
                area.classList.remove('hidden');
                btn.textContent = 'Hide';
                btn.dataset.state = 'shown';
            } else {
                input.value = maskKey(real);
                area.classList.add('hidden');
                input.classList.remove('hidden');
                btn.textContent = 'Show';
                btn.dataset.state = 'masked';
            }
        });
    }

    setupKeyToggle('openai-key-input', 'openai-key-textarea', 'openai-key-toggle');
    setupKeyToggle('hf-key-input', 'hf-key-textarea', 'hf-key-toggle');

    function openPreferencesModal() {
        if (!preferencesModal) return;
        populateKeyFields();
        // Load saved model selection
        if (preferencesModelSelect) {
            var savedModel = sessionStorage.getItem('selectedModel');
            if (savedModel) preferencesModelSelect.value = savedModel;
        }
        // Load saved timeout
        if (preferencesTimeoutInput) {
            var savedTimeout = localStorage.getItem('gradeTimeout');
            if (savedTimeout) preferencesTimeoutInput.value = savedTimeout;
        }
        preferencesModal.style.display = 'flex';
        closeMenus();
    }

    function closePreferencesModal() {
        if (!preferencesModal) {
            return;
        }
        preferencesModal.style.display = 'none';
    }

    if (preferencesSaveBtn) {
        preferencesSaveBtn.addEventListener('click', function () {
            var okInput = document.getElementById('openai-key-input');
            var okArea  = document.getElementById('openai-key-textarea');
            var okBtn   = document.getElementById('openai-key-toggle');
            var hfInput = document.getElementById('hf-key-input');
            var hfArea  = document.getElementById('hf-key-textarea');
            var hfBtn   = document.getElementById('hf-key-toggle');

            var openaiKey = (okBtn && okBtn.dataset.state === 'shown')
                ? (okArea ? okArea.value : '')
                : (okInput ? okInput.dataset.realValue || '' : '');
            var hfKey = (hfBtn && hfBtn.dataset.state === 'shown')
                ? (hfArea ? hfArea.value : '')
                : (hfInput ? hfInput.dataset.realValue || '' : '');

            localStorage.setItem('openai_api_key', openaiKey);
            localStorage.setItem('hfToken', hfKey);
            // Save model selection
            if (preferencesModelSelect) {
                sessionStorage.setItem('selectedModel', preferencesModelSelect.value);
            }
            // Save timeout
            if (preferencesTimeoutInput) {
                localStorage.setItem('gradeTimeout', preferencesTimeoutInput.value);
            }
            closePreferencesModal();
        });
    }

    if (preferencesCancelBtn) {
        preferencesCancelBtn.addEventListener('click', function () {
            closePreferencesModal();
        });
    }

    if (preferencesMenuItem) {
        preferencesMenuItem.addEventListener('click', function () {
            openPreferencesModal();
        });
    }

    if (settingsGearBtn) {
        settingsGearBtn.addEventListener('click', function () {
            openPreferencesModal();
        });
    }

    // Close modal when clicking overlay
    if (preferencesModal) {
        preferencesModal.addEventListener('click', function (e) {
            if (e.target === preferencesModal) {
                closePreferencesModal();
            }
        });
    }

    var adminLoginMenuItem = document.getElementById('admin-login-menu-item');
    var adminLoginModal = document.getElementById('admin-login-modal');
    var adminLoginPassword = document.getElementById('admin-login-password');
    var adminLoginSubmit = document.getElementById('admin-login-submit');
    var adminLoginCancel = document.getElementById('admin-login-cancel');
    var adminMenuButton = document.querySelector('.menu-group[data-view="admin"] .menu-button');
    var analyticsMenuButton = document.querySelector('.menu-group[data-view="analytics"] .menu-button');
    var adminViewButtons = Array.prototype.slice.call(document.querySelectorAll('[data-view="admin"]'));
    var analyticsViewButtons = Array.prototype.slice.call(document.querySelectorAll('[data-view="analytics"]'));

    function showAdminLoginDialog() {
        if (!adminLoginModal) {
            return;
        }
        if (adminLoginPassword) {
            adminLoginPassword.value = '';
            adminLoginPassword.focus();
        }
        adminLoginModal.style.display = 'flex';
        closeMenus();
    }

    function hideAdminLoginDialog() {
        if (!adminLoginModal) {
            return;
        }
        adminLoginModal.style.display = 'none';
    }

    function enableAdminMenuItems() {
        if (adminMenuButton) {
            adminMenuButton.disabled = false;
            adminMenuButton.setAttribute('aria-disabled', 'false');
        }
        if (analyticsMenuButton) {
            analyticsMenuButton.disabled = false;
            analyticsMenuButton.setAttribute('aria-disabled', 'false');
        }
        adminViewButtons.forEach(function (button) {
            button.disabled = false;
            button.setAttribute('aria-disabled', 'false');
        });
        analyticsViewButtons.forEach(function (button) {
            button.disabled = false;
            button.setAttribute('aria-disabled', 'false');
        });
    }

    function disableAdminMenuItems() {
        if (adminMenuButton) {
            adminMenuButton.disabled = true;
            adminMenuButton.setAttribute('aria-disabled', 'true');
        }
        if (analyticsMenuButton) {
            analyticsMenuButton.disabled = true;
            analyticsMenuButton.setAttribute('aria-disabled', 'true');
        }
        adminViewButtons.forEach(function (button) {
            button.disabled = true;
            button.setAttribute('aria-disabled', 'true');
        });
        analyticsViewButtons.forEach(function (button) {
            button.disabled = true;
            button.setAttribute('aria-disabled', 'true');
        });
    }

    async function adminLogin(password) {
        try {
            var response = await fetch('/api/admin-login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ password: password })
            });

            if (!response.ok) {
                return false;
            }

            sessionStorage.setItem('isAdmin', 'true');
            return true;
        } catch (error) {
            return false;
        }
    }

    window.showAdminLoginDialog = showAdminLoginDialog;
    window.hideAdminLoginDialog = hideAdminLoginDialog;
    window.enableAdminMenuItems = enableAdminMenuItems;
    window.disableAdminMenuItems = disableAdminMenuItems;
    window.adminLogin = adminLogin;

    if (adminLoginMenuItem) {
        adminLoginMenuItem.addEventListener('click', function () {
            showAdminLoginDialog();
        });
    }

    if (adminLoginCancel) {
        adminLoginCancel.addEventListener('click', function () {
            hideAdminLoginDialog();
        });
    }

    if (adminLoginModal) {
        adminLoginModal.addEventListener('click', function (e) {
            if (e.target === adminLoginModal) {
                hideAdminLoginDialog();
            }
        });
    }

    if (adminLoginSubmit) {
        adminLoginSubmit.addEventListener('click', async function () {
            if (!adminLoginPassword) {
                return;
            }
            var success = await adminLogin(adminLoginPassword.value);
            if (success) {
                enableAdminMenuItems();
                hideAdminLoginDialog();
            } else {
                alert('Admin login failed');
            }
        });
    }

    if (isAdminLoggedIn()) {
        enableAdminMenuItems();
    } else {
        disableAdminMenuItems();
    }

    // Load Course Package modal and upload workflow added
    var loadCourseMenuItem = document.getElementById('load-course-menu-item');
    var loadCourseModal = document.getElementById('load-course-modal');
    var coursePackageFileInput = document.getElementById('course-package-file');
    var loadCourseBtn = document.getElementById('load-course-btn');
    var loadCourseCancelBtn = document.getElementById('load-course-cancel-btn');

    function openLoadCourseModal() {
        if (!loadCourseModal || !coursePackageFileInput) {
            return;
        }
        coursePackageFileInput.value = '';
        loadCourseModal.style.display = 'flex';
        closeMenus();
    }

    function closeLoadCourseModal() {
        if (!loadCourseModal) {
            return;
        }
        loadCourseModal.style.display = 'none';
    }

    if (loadCourseMenuItem) {
        loadCourseMenuItem.addEventListener('click', function () {
            openLoadCourseModal();
        });
    }

    if (loadCourseBtn) {
        loadCourseBtn.addEventListener('click', async function () {
            if (!coursePackageFileInput) {
                return;
            }
            
            var file = coursePackageFileInput.files[0];
            if (!file) {
                alert('Please select a ZIP file');
                return;
            }

            var formData = new FormData();
            formData.append('file', file);

            try {
                loadCourseBtn.disabled = true;
                loadCourseBtn.textContent = 'Loading...';

                var response = await fetch('/admin/upload', {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    var errorData = await response.json();
                    throw new Error(errorData.error || 'Upload failed');
                }

                closeLoadCourseModal();
                
                // Refresh the unit list by calling the existing loadUnits function
                if (typeof loadUnits === 'function') {
                    await loadUnits();
                }
            } catch (error) {
                alert('Error uploading course package: ' + error.message);
            } finally {
                loadCourseBtn.disabled = false;
                loadCourseBtn.textContent = 'Load';
            }
        });
    }

    if (loadCourseCancelBtn) {
        loadCourseCancelBtn.addEventListener('click', function () {
            closeLoadCourseModal();
        });
    }

    // Close modal when clicking overlay
    if (loadCourseModal) {
        loadCourseModal.addEventListener('click', function (e) {
            if (e.target === loadCourseModal) {
                closeLoadCourseModal();
            }
        });
    }
}
