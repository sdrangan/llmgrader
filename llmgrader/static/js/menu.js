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

    var authState = {
        authenticated: false,
        is_admin: false,
        user: null,
        oauth_enabled: false
    };

    function isAdminLoggedIn() {
        return authState.is_admin === true;
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
        button.addEventListener('click', function (e) {
            openMenus();
            var group = button.closest('.menu-group');
            var isAlreadyOpen = group && group.classList.contains('is-open');
            // Close all open groups
            document.querySelectorAll('.menu-group.is-open').forEach(function (g) {
                g.classList.remove('is-open');
            });
            if (!isAlreadyOpen && group) {
                group.classList.add('is-open');
                e.stopPropagation();
            }
        });
    });

    // Close open menus when clicking outside
    document.addEventListener('click', function () {
        document.querySelectorAll('.menu-group.is-open').forEach(function (g) {
            g.classList.remove('is-open');
        });
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

    // ---------------------------------------------------------------
    //  Course picker
    // ---------------------------------------------------------------
    //
    // Switching course is a navigation, not a setting: it goes to /c/<id>/, so
    // the URL is shareable and two tabs can hold two courses.  The list comes
    // from /api/courses, which is portal-wide and therefore unprefixed.
    var selectCourseMenuItem = document.getElementById('select-course-menu-item');
    var selectCourseModal = document.getElementById('select-course-modal');
    var selectCourseList = document.getElementById('select-course-list');
    var selectCourseMessage = document.getElementById('select-course-message');
    var selectCourseCancelBtn = document.getElementById('select-course-cancel-btn');

    function renderCourseList(payload) {
        var courses = (payload && payload.courses) || [];
        selectCourseList.innerHTML = '';

        if (!courses.length) {
            selectCourseMessage.textContent = 'No courses are registered on this portal.';
            return;
        }

        selectCourseMessage.textContent = courses.length === 1
            ? 'This portal serves one course.'
            : 'Choose a course. The page will reload into it.';

        // Which course this page is, from the page itself.  /api/courses is a
        // portal route with no <course_id> in its path, so the server has no
        // request-bound course to report and its `current` is the registry
        // default -- which marked the default course as current wherever you
        // actually were, and left it permanently disabled in the list, so you
        // could never switch back to it.
        var currentId = (window.LLMGRADER_COURSE_ID || '').trim();

        courses.forEach(function (course) {
            var isCurrent = course.id === currentId;
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'menu-item';
            button.setAttribute('role', 'listitem');
            button.dataset.courseId = course.id;
            button.style.display = 'block';
            button.style.width = '100%';
            button.style.textAlign = 'left';

            var label = course.name || course.id;
            if (!course.loaded) label += '  (no package loaded)';
            if (isCurrent) label = '✓ ' + label;
            button.textContent = label;

            if (isCurrent) {
                button.disabled = true;
                button.setAttribute('aria-current', 'true');
            } else {
                button.addEventListener('click', function () {
                    // A full navigation, not a fetch: the course in the path is
                    // what every subsequent request is scoped by, and the page
                    // reads it back out of window.LLMGRADER_COURSE_ID.
                    window.location.href = '/c/' + encodeURIComponent(course.id) + '/';
                });
            }
            selectCourseList.appendChild(button);
        });
    }

    function openCoursePicker() {
        if (!selectCourseModal) return;
        selectCourseList.innerHTML = '';
        selectCourseMessage.textContent = 'Loading courses…';
        selectCourseModal.style.display = 'flex';

        fetch('/api/courses')
            .then(function (resp) {
                if (!resp.ok) throw new Error('GET /api/courses failed: ' + resp.status);
                return resp.json();
            })
            .then(renderCourseList)
            .catch(function (err) {
                console.error('Could not load the course list:', err);
                selectCourseMessage.textContent = 'Could not load the course list.';
            });
    }

    if (selectCourseMenuItem) {
        selectCourseMenuItem.addEventListener('click', function () {
            openCoursePicker();
        });
    }
    if (selectCourseCancelBtn) {
        selectCourseCancelBtn.addEventListener('click', function () {
            selectCourseModal.style.display = 'none';
        });
    }

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

        var okInput = document.getElementById('openai-key-input');
        var okArea  = document.getElementById('openai-key-textarea');
        var okBtn   = document.getElementById('openai-key-toggle');

        if (okInput) { okInput.dataset.realValue = openaiKey; okInput.value = maskKey(openaiKey); }
        if (okArea)  { okArea.value = ''; okArea.classList.add('hidden'); }
        if (okBtn)   { okBtn.textContent = 'Show'; okBtn.dataset.state = 'masked'; }

        if (okInput) okInput.classList.remove('hidden');
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

            // If shown: read the textarea. If masked: check whether the user
            // typed a new value (differs from the masked display) — if so use
            // what they typed, otherwise keep the stored real value unchanged.
            var openaiKey;
            if (okBtn && okBtn.dataset.state === 'shown') {
                openaiKey = okArea ? okArea.value : '';
            } else {
                var storedOk = okInput ? (okInput.dataset.realValue || '') : '';
                var typedOk  = okInput ? okInput.value : '';
                openaiKey = (typedOk !== maskKey(storedOk)) ? typedOk : storedOk;
            }

            localStorage.setItem('openai_api_key', openaiKey);
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

    var adminMenuButton = document.querySelector('.menu-group[data-view="admin"] .menu-button');
    var analyticsMenuButton = document.querySelector('.menu-group[data-view="analytics"] .menu-button');
    var adminViewButtons = Array.prototype.slice.call(document.querySelectorAll('[data-view="admin"]'));
    var analyticsViewButtons = Array.prototype.slice.call(document.querySelectorAll('[data-view="analytics"]'));
    var analyticsMenuGroup = document.getElementById('analytics-menu-group');
    var analyticsSwitchViewItem = document.getElementById('switch-view-analytics-item');
    var accountName = document.getElementById('account-user-name');
    var signInLink = document.getElementById('sign-in-link');
    var signOutLink = document.getElementById('sign-out-link');

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

    function setAnalyticsVisible(visible) {
        if (analyticsMenuGroup) {
            analyticsMenuGroup.style.display = visible ? '' : 'none';
        }
        if (analyticsSwitchViewItem) {
            analyticsSwitchViewItem.style.display = visible ? '' : 'none';
        }
    }

    function updateAccountArea() {
        if (!signInLink || !signOutLink || !accountName) {
            return;
        }
        if (!authState.authenticated) {
            signInLink.classList.remove('hidden');
            signOutLink.classList.add('hidden');
            accountName.classList.add('hidden');
            accountName.textContent = '';
            signInLink.style.display = authState.oauth_enabled ? '' : 'none';
            return;
        }

        signInLink.classList.add('hidden');
        signOutLink.classList.remove('hidden');
        accountName.classList.remove('hidden');
        accountName.textContent = authState.user && authState.user.email ? authState.user.email : 'Signed in';
    }

    function updateRoleVisibility() {
        if (isAdminLoggedIn()) {
            enableAdminMenuItems();
            setAnalyticsVisible(true);
            return;
        }

        disableAdminMenuItems();
        setAnalyticsVisible(false);
        var currentView = document.body && document.body.getAttribute('data-active-view');
        if (currentView === 'admin' || currentView === 'analytics') {
            setActiveView('grade');
            if (typeof loadView === 'function') {
                loadView('grade');
            }
        }
    }

    async function refreshAuthState() {
        try {
            var response = await fetch('/api/auth/session');
            if (!response.ok) {
                throw new Error('auth state unavailable');
            }
            authState = await response.json();
        } catch (error) {
            authState = {
                authenticated: false,
                is_admin: false,
                user: null,
                oauth_enabled: false
            };
        } finally {
            updateAccountArea();
            updateRoleVisibility();
        }
    }

    window.enableAdminMenuItems = enableAdminMenuItems;
    window.disableAdminMenuItems = disableAdminMenuItems;
    window.refreshAuthState = refreshAuthState;
    refreshAuthState();

    // ---------------------------------------------------------------
    //  Manage Courses
    // ---------------------------------------------------------------
    //
    // Add is an upload: the server reads <course> out of the package and mints
    // the id from it, so an admin never types a name that could disagree with
    // the XML (plans/multicourse.md, decision 10).  Delete archives -- the
    // package and every grade stay -- because grades are the one thing on this
    // portal that cannot be reconstructed.
    var manageCoursesMenuItem = document.getElementById('manage-courses-menu-item');
    var manageCoursesModal = document.getElementById('manage-courses-modal');
    var manageCoursesBody = document.getElementById('manage-courses-body');
    var manageCoursesMessage = document.getElementById('manage-courses-message');
    var manageCoursesError = document.getElementById('manage-courses-error');
    var manageCoursesCloseBtn = document.getElementById('manage-courses-close-btn');
    var addCourseFile = document.getElementById('add-course-file');
    var addCourseBtn = document.getElementById('add-course-btn');

    function showManageCoursesError(message) {
        if (!manageCoursesError) return;
        manageCoursesError.textContent = message || '';
        manageCoursesError.style.display = message ? 'block' : 'none';
    }

    function courseRowLabel(course) {
        var label = course.name || course.id;
        if (course.semester) label += ' \u2014 ' + course.semester;
        label += ' (' + course.id + ')';
        if (course.is_default) label += '  \u2605 default';
        if (!course.loaded && !course.deleted_at) label += '  \u2014 no package loaded';
        if (course.deleted_at) label += '  \u2014 archived';
        return label;
    }

    function renderManageCourses(payload) {
        var courses = (payload && payload.courses) || [];
        manageCoursesBody.innerHTML = '';
        manageCoursesMessage.textContent = courses.length
            ? 'Archiving a course stops serving it. Its package and its grades are kept.'
            : 'No courses are registered on this portal.';

        var liveCount = courses.filter(function (c) { return !c.deleted_at; }).length;

        courses.forEach(function (course) {
            var row = document.createElement('tr');
            row.dataset.courseId = course.id;

            var label = document.createElement('td');
            label.textContent = courseRowLabel(course);
            label.style.padding = '4px 8px 4px 0';
            if (course.deleted_at) label.style.opacity = '0.6';
            row.appendChild(label);

            var count = document.createElement('td');
            count.textContent = course.submissions + ' graded';
            count.style.padding = '4px 8px';
            count.style.whiteSpace = 'nowrap';
            count.style.opacity = '0.8';
            row.appendChild(count);

            var actions = document.createElement('td');
            actions.style.textAlign = 'right';
            if (!course.deleted_at) {
                var archiveBtn = document.createElement('button');
                archiveBtn.type = 'button';
                archiveBtn.className = 'modal-btn';
                archiveBtn.textContent = 'Archive';
                archiveBtn.dataset.archiveCourseId = course.id;
                // The last live course cannot be archived: there would be no
                // default left, and every student would meet a 404 at "/".
                archiveBtn.disabled = liveCount <= 1;
                archiveBtn.addEventListener('click', function () {
                    archiveCourse(course);
                });
                actions.appendChild(archiveBtn);
            }
            row.appendChild(actions);

            manageCoursesBody.appendChild(row);
        });
    }

    async function refreshManageCourses() {
        if (!manageCoursesBody) return;
        manageCoursesBody.innerHTML = '';
        manageCoursesMessage.textContent = 'Loading courses...';
        try {
            var resp = await fetch('/api/admin/courses');
            if (!resp.ok) throw new Error('GET /api/admin/courses failed: ' + resp.status);
            renderManageCourses(await resp.json());
        } catch (err) {
            console.error('Could not load the course list:', err);
            manageCoursesMessage.textContent = 'Could not load the course list.';
        }
    }

    async function archiveCourse(course) {
        var name = course.name || course.id;
        var confirmed = window.confirm(
            'Archive ' + name + '?'
            + '\n\nIt stops being served and leaves the course picker. '
            + 'Its package and its ' + course.submissions + ' graded submission(s) are kept, '
            + 'so this can be undone by hand.'
        );
        if (!confirmed) return;

        showManageCoursesError('');
        try {
            var resp = await fetch('/api/admin/courses/' + encodeURIComponent(course.id), {
                method: 'DELETE'
            });
            if (!resp.ok) {
                var err = await resp.json().catch(function () { return {}; });
                throw new Error(err.error || 'Archiving failed');
            }
            await refreshManageCourses();
        } catch (err) {
            showManageCoursesError(err.message);
        }
    }

    if (manageCoursesMenuItem) {
        manageCoursesMenuItem.addEventListener('click', function () {
            if (!manageCoursesModal) return;
            showManageCoursesError('');
            if (addCourseFile) addCourseFile.value = '';
            manageCoursesModal.style.display = 'flex';
            closeMenus();
            refreshManageCourses();
        });
    }

    if (addCourseBtn) {
        addCourseBtn.addEventListener('click', async function () {
            var file = addCourseFile && addCourseFile.files[0];
            if (!file) {
                showManageCoursesError('Choose a course package (.zip) to add.');
                return;
            }

            var formData = new FormData();
            formData.append('file', file);

            showManageCoursesError('');
            addCourseBtn.disabled = true;
            addCourseBtn.textContent = 'Adding...';
            try {
                var resp = await fetch('/api/admin/courses', { method: 'POST', body: formData });
                if (!resp.ok) {
                    var err = await resp.json().catch(function () { return {}; });
                    throw new Error(err.error || 'Could not add the course');
                }
                addCourseFile.value = '';
                await refreshManageCourses();
            } catch (err) {
                showManageCoursesError(err.message);
            } finally {
                addCourseBtn.disabled = false;
                addCourseBtn.textContent = 'Add Course';
            }
        });
    }

    if (manageCoursesCloseBtn) {
        manageCoursesCloseBtn.addEventListener('click', function () {
            manageCoursesModal.style.display = 'none';
        });
    }

    // Load Course Package modal and upload workflow added
    var loadCourseMenuItem = document.getElementById('load-course-menu-item');
    var loadCourseModal = document.getElementById('load-course-modal');
    var coursePackageFileInput = document.getElementById('course-package-file');
    var loadCourseBtn = document.getElementById('load-course-btn');
    var loadCourseCancelBtn = document.getElementById('load-course-cancel-btn');

    var loadCourseTarget = document.getElementById('load-course-target');
    var loadCourseError = document.getElementById('load-course-error');

    function showLoadCourseError(message) {
        if (!loadCourseError) return;
        loadCourseError.textContent = message || '';
        loadCourseError.style.display = message ? 'block' : 'none';
    }

    // Filled from the admin course list, which unlike /api/courses also
    // reports archived courses -- filtered out here, since a package cannot be
    // loaded into a course that is no longer served.
    async function populateLoadCourseTarget() {
        if (!loadCourseTarget) return;
        loadCourseTarget.innerHTML = '';
        try {
            var resp = await fetch('/api/admin/courses');
            if (!resp.ok) throw new Error('GET /api/admin/courses failed: ' + resp.status);
            var data = await resp.json();
            (data.courses || [])
                .filter(function (course) { return !course.deleted_at; })
                .forEach(function (course) {
                    var option = document.createElement('option');
                    option.value = course.id;
                    option.textContent = (course.name || course.id)
                        + (course.semester ? ' \u2014 ' + course.semester : '')
                        + ' (' + course.id + ')';
                    if (course.id === (window.LLMGRADER_COURSE_ID || '')) {
                        option.selected = true;
                    }
                    loadCourseTarget.appendChild(option);
                });
        } catch (err) {
            console.error('Could not load the course list:', err);
            showLoadCourseError('Could not load the course list.');
        }
    }

    function openLoadCourseModal() {
        if (!loadCourseModal || !coursePackageFileInput) {
            return;
        }
        coursePackageFileInput.value = '';
        showLoadCourseError('');
        populateLoadCourseTarget();
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
            if (loadCourseTarget && loadCourseTarget.value) {
                formData.append('course_id', loadCourseTarget.value);
            }

            try {
                loadCourseBtn.disabled = true;
                loadCourseBtn.textContent = 'Loading...';
                showLoadCourseError('');

                var response = await fetch('/admin/upload', {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    var errorData = await response.json();
                    throw new Error(errorData.error || 'Upload failed');
                }

                var loaded = await response.json();
                closeLoadCourseModal();
                
                // Loading into the course being viewed refreshes the unit list;
                // loading into another one changes nothing on screen.
                if (loaded.course_id && loaded.course_id !== (window.LLMGRADER_COURSE_ID || '')) {
                    alert('Package loaded into ' + loaded.course_id
                          + '. Switch to that course to see it.');
                } else if (typeof loadUnits === 'function') {
                    await loadUnits();
                }
            } catch (error) {
                // Inline rather than an alert: a refused upload names two
                // courses and says nothing was changed, which is more than a
                // dialog box should be asked to carry.
                showLoadCourseError(error.message);
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
