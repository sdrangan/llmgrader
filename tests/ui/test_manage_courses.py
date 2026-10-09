"""The Manage Courses dialog in the Admin view.

Read-only on purpose. ``live_server`` is session-scoped and shared with every
other UI test, so archiving a course here would pull the second course out from
under ``test_course_picker.py``. What the dialog *does* -- adding, archiving,
refusing a package for the wrong course -- is covered against the real routes in
``tests/services/test_manage_courses.py``; what is worth checking in a browser
is that the dialog reaches those routes and renders what comes back.
"""

import pytest

from pages.view_ready import switch_to_view

COURSE1_ID = "ui_test_course"
COURSE2_ID = "course2"


def open_admin_dialog(page, live_server, menu_item_id: str, modal_id: str):
    page.goto(live_server)
    switch_to_view(page, "admin")
    page.wait_for_selector("#admin-view", state="visible", timeout=8_000)

    # In dev-open mode /api/auth/session reports is_admin false, so the client
    # leaves the Admin menu group aria-disabled even though the server lets
    # every /admin route through. The rest of the suite sidesteps the menu
    # entirely by calling loadView; a dialog can only be reached through it, so
    # enable it the way the app does for a real admin. (That client/server
    # disagreement is older than this change and is not fixed here.)
    page.evaluate("window.enableAdminMenuItems && window.enableAdminMenuItems()")

    # The Admin dropdown opens on :hover / :focus-within (style.css), and the
    # group itself only shows in the admin view.
    page.locator('.menu-group[data-view="admin"] .menu-button').first.hover()
    page.wait_for_selector(f"#{menu_item_id}", state="visible", timeout=5_000)
    page.click(f"#{menu_item_id}")
    page.wait_for_selector(f"#{modal_id}", state="visible", timeout=5_000)


@pytest.fixture()
def manage_courses(page, live_server):
    open_admin_dialog(page, live_server, "manage-courses-menu-item", "manage-courses-modal")
    page.wait_for_function(
        "document.querySelectorAll('#manage-courses-body tr').length > 0",
        timeout=5_000,
    )
    return page


def course_rows(page) -> list[dict]:
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('#manage-courses-body tr'))
                .map(tr => ({
                    id: tr.dataset.courseId,
                    text: tr.textContent,
                    archivable: !!tr.querySelector('button[data-archive-course-id]:not([disabled])'),
                }))"""
    )


def test_the_dialog_lists_every_course(manage_courses) -> None:
    listed = {row["id"] for row in course_rows(manage_courses)}
    assert listed == {COURSE1_ID, COURSE2_ID}


def test_each_course_shows_its_name_and_grade_count(manage_courses) -> None:
    """The grade count is the reason archiving is safe to offer: it says what
    is being kept."""
    text = " ".join(row["text"] for row in course_rows(manage_courses))

    assert "UI Test Course" in text
    assert "Second Test Course" in text
    assert "graded" in text


def test_the_default_course_is_marked(manage_courses) -> None:
    rows = {row["id"]: row for row in course_rows(manage_courses)}
    assert "default" in rows[COURSE1_ID]["text"]


def test_archiving_is_offered_while_more_than_one_course_is_live(manage_courses) -> None:
    """With two courses either can go; the control disables itself at one."""
    assert all(row["archivable"] for row in course_rows(manage_courses))


def test_the_dialog_says_grades_are_kept(manage_courses) -> None:
    """An admin should not have to guess whether Archive destroys grades."""
    message = manage_courses.locator("#manage-courses-message").inner_text()
    assert "kept" in message.lower()


def test_adding_without_a_file_reports_it_inline(manage_courses) -> None:
    manage_courses.click("#add-course-btn")

    error = manage_courses.locator("#manage-courses-error")
    error.wait_for(state="visible", timeout=3_000)
    assert "package" in error.inner_text().lower()


def test_add_course_asks_for_a_package_not_a_name(manage_courses) -> None:
    """Decision 10: no typed identity anywhere in this dialog.

    A text input for the course name is exactly what recreates the
    two-identities ambiguity the authored id removes.
    """
    inputs = manage_courses.evaluate(
        """() => Array.from(document.querySelectorAll('#manage-courses-modal input'))
                .map(i => i.type)"""
    )
    assert inputs == ["file"]


# ---------------------------------------------------------------------------
# Load Course Package gained a target
# ---------------------------------------------------------------------------


@pytest.fixture()
def load_course(page, live_server):
    open_admin_dialog(page, live_server, "load-course-menu-item", "load-course-modal")
    page.wait_for_function(
        "document.querySelectorAll('#load-course-target option').length > 0",
        timeout=5_000,
    )
    return page


def test_the_upload_dialog_offers_a_target_course(load_course) -> None:
    options = load_course.evaluate(
        """() => Array.from(document.getElementById('load-course-target').options)
                .map(o => o.value)"""
    )
    assert set(options) == {COURSE1_ID, COURSE2_ID}


def test_the_target_defaults_to_the_course_being_viewed(load_course) -> None:
    assert load_course.locator("#load-course-target").input_value() == COURSE1_ID


def test_the_dialog_warns_that_a_wrong_package_is_refused(load_course) -> None:
    """Every archive is called soln_package.zip; say so before the upload."""
    text = load_course.locator("#load-course-modal").inner_text().lower()
    assert "soln_package.zip" in text
    assert "refused" in text


# ---------------------------------------------------------------------------
# Demo code (plans/demo_code_admin.md)
# ---------------------------------------------------------------------------
#
# The live server runs without the course MCP, so its courses report demo code
# as off.  These tests stub the course list and the /code routes through route
# interception: what is checked is the browser side -- the column, the dialog
# and the progress display -- against payloads of the shape the server sends.
# The routes themselves are tested in tests/coursemcp/test_code_admin.py.

import time  # noqa: E402

SERVED = "a1b2c3d4e5f6" + "0" * 28
NEWER = "9e8d7c6b5a43" + "1" * 28
REPO = "https://github.com/sdrangan/hwdesign"


def code_object(status, *, served=SERVED, head=NEWER, progress=None, last_attempt=100.0,
                last_error=None, subject="Rebuild the streaming demos as build DAGs"):
    return {
        "enabled": True, "repo": REPO, "branch": "main",
        "served": {"commit": served, "committed_at": "2026-10-08T21:14:03-04:00",
                   "subject": subject},
        "synced_at": last_attempt, "last_attempt": last_attempt, "last_error": last_error,
        "remote": {"head": head, "checked_at": time.time() - 12, "error": None},
        "progress": progress, "status": status,
    }


class CodeStub:
    """Answers /api/admin/courses and the /code routes for COURSE1_ID.

    Before Update now, /code answers with an update available; after it, with
    each stage of a sync in turn, then the new commit.
    """

    def __init__(self):
        self.updates = 0
        self.after_update = [
            code_object("syncing", progress={"stage": stage, "started_at": 200.0, "stale": False})
            for stage in ("checking", "fetching", "building", "validating")
        ] + [code_object("up_to_date", served=NEWER, head=NEWER, last_attempt=200.0,
                         subject="Second commit")]

    def current(self):
        if not self.updates:
            return code_object("update_available")
        if len(self.after_update) > 1:
            return self.after_update.pop(0)
        return self.after_update[0]

    def handle(self, route):
        request = route.request
        path = request.url.split("?", 1)[0]
        if path.endswith("/api/admin/courses") and request.method == "GET":
            response = route.fetch()
            data = response.json()
            for course in data["courses"]:
                course["code"] = code_object("update_available") if course["id"] == COURSE1_ID else None
            route.fulfill(response=response, json=data)
        elif path.endswith(f"/{COURSE1_ID}/code/check"):
            route.fulfill(status=202, json={"started": True})
        elif path.endswith(f"/{COURSE1_ID}/code/update"):
            self.updates += 1
            route.fulfill(status=202, json={"started": True})
        elif path.endswith(f"/{COURSE1_ID}/code"):
            route.fulfill(json={"code": self.current()})
        else:
            route.continue_()


@pytest.fixture()
def demo_code(page, live_server):
    stub = CodeStub()
    page.route("**/api/admin/courses**", stub.handle)
    open_admin_dialog(page, live_server, "manage-courses-menu-item", "manage-courses-modal")
    page.wait_for_function(
        "document.querySelectorAll('#manage-courses-body .course-demo-code .demo-code-sha').length > 0",
        timeout=5_000,
    )
    return page, stub


def demo_cell(page, course_id):
    return page.locator(f'#manage-courses-body tr[data-course-id="{course_id}"] .course-demo-code')


def test_the_column_shows_the_served_commit_and_its_status(demo_code) -> None:
    page, _ = demo_code
    cell = demo_cell(page, COURSE1_ID)
    assert cell.locator(".demo-code-sha").inner_text() == SERVED[:12]
    assert cell.locator(".demo-code-status").inner_text() == "Update available"
    assert demo_cell(page, COURSE2_ID).inner_text() == "—"     # no <code>


def test_the_dialog_compares_the_served_commit_with_github(demo_code) -> None:
    page, _ = demo_code
    demo_cell(page, COURSE1_ID).click()
    page.wait_for_selector("#demo-code-modal", state="visible", timeout=3_000)
    served = page.locator("#demo-code-served").inner_text()
    assert SERVED[:12] in served and "Rebuild the streaming demos" in served
    remote = page.locator("#demo-code-remote").inner_text()
    assert NEWER[:12] in remote and "s ago" in remote
    compare = page.locator("#demo-code-compare a").get_attribute("href")
    assert compare == f"{REPO}/compare/{SERVED}...{NEWER}"
    assert page.locator("#demo-code-served a").get_attribute("href") == f"{REPO}/commit/{SERVED}"
    assert page.locator("#demo-code-update-btn").is_enabled()


def test_update_now_shows_the_stages_then_the_new_commit(demo_code) -> None:
    page, stub = demo_code
    demo_cell(page, COURSE1_ID).click()
    page.wait_for_selector("#demo-code-modal", state="visible", timeout=3_000)
    page.click("#demo-code-update-btn")

    page.wait_for_selector("#demo-code-progress", state="visible", timeout=3_000)
    assert page.locator("#demo-code-update-btn").is_disabled()
    page.wait_for_selector('#demo-code-progress li[data-stage="validating"].is-current',
                           timeout=10_000)
    done = page.locator("#demo-code-progress li.is-done").evaluate_all(
        "items => items.map(li => li.dataset.stage)")
    assert done == ["checking", "fetching", "building"]

    result = page.locator("#demo-code-result")
    result.wait_for(state="visible", timeout=10_000)
    assert f"Now serving {NEWER[:12]}" in result.inner_text()
    assert page.locator("#demo-code-progress").is_hidden()
    assert stub.updates == 1
    # The row behind the dialog follows.
    cell = demo_cell(page, COURSE1_ID)
    assert cell.locator(".demo-code-sha").inner_text() == NEWER[:12]
    assert cell.locator(".demo-code-status").inner_text() == "Up to date"
