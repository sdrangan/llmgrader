(function () {
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
        
        if (viewName === 'dashboard') {
            // Dashboard: show unit dropdown only
            unitDropdowns.forEach(function (el) { el.style.display = ''; });
            gradeOnlyDropdowns.forEach(function (el) { el.style.display = 'none'; });
        } else if (viewName === 'grade') {
            // Grade: show unit dropdown and all grade-only dropdowns
            unitDropdowns.forEach(function (el) { el.style.display = ''; });
            gradeOnlyDropdowns.forEach(function (el) { el.style.display = ''; });
        } else {
            // Admin and Analytics: hide all dropdowns
            unitDropdowns.forEach(function (el) { el.style.display = 'none'; });
            gradeOnlyDropdowns.forEach(function (el) { el.style.display = 'none'; });
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

    viewButtons.forEach(function (button) {
        button.addEventListener('click', function () {
            var viewName = button.getAttribute('data-view');
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
    var preferencesModal = document.getElementById('preferences-modal');
    var preferencesApiKeyInput = document.getElementById('preferences-api-key');
    var preferencesSaveBtn = document.getElementById('preferences-save-btn');
    var preferencesCancelBtn = document.getElementById('preferences-cancel-btn');

    function openPreferencesModal() {
        if (!preferencesModal || !preferencesApiKeyInput) {
            return;
        }
        // Load current API key from localStorage
        var currentKey = localStorage.getItem('openai_api_key') || '';
        preferencesApiKeyInput.value = currentKey;
        preferencesModal.style.display = 'flex';
        closeMenus();
    }

    function closePreferencesModal() {
        if (!preferencesModal) {
            return;
        }
        preferencesModal.style.display = 'none';
    }

    if (preferencesMenuItem) {
        preferencesMenuItem.addEventListener('click', function () {
            openPreferencesModal();
        });
    }

    if (preferencesSaveBtn) {
        preferencesSaveBtn.addEventListener('click', function () {
            if (!preferencesApiKeyInput) {
                return;
            }
            var apiKey = preferencesApiKeyInput.value.trim();
            localStorage.setItem('openai_api_key', apiKey);
            closePreferencesModal();
        });
    }

    if (preferencesCancelBtn) {
        preferencesCancelBtn.addEventListener('click', function () {
            closePreferencesModal();
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
})();
