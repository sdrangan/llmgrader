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
