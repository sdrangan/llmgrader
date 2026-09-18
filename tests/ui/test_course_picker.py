"""Two courses on one portal: the picker, the URLs, and students' saved work.

``plans/multicourse.md`` decisions 5 and 7.  The live server registers two
fixture courses (``tests/ui/conftest.py``): ``ui_test_course``, the default, and
``course2``.

The storage tests here are the ones to take seriously.  Students have real
graded work in ``localStorage["llmgrader_session"]``, and losing it on deploy
day is the most visible way this whole plan can fail -- for people with no way
to diagnose it and no copy anywhere else.
"""

import json

import pytest

from pages.grader_page import GraderPage
from pages.view_ready import switch_to_view

COURSE1_ID = "ui_test_course"
COURSE2_ID = "course2"

LEGACY_SESSION = {
    "Test Unit": {
        "q1": {
            "student_solution": "work from before the upgrade",
            "selected_part": "all",
            "result": "pass",
            "points": 1,
        }
    }
}


def open_course_picker(page):
    page.wait_for_selector('body[data-active-view="grade"]', timeout=8_000)
    # The File dropdown opens on :hover / :focus-within (style.css), so the
    # item is not clickable until its group is hovered.
    page.locator(".menu-button", has_text="File").first.hover()
    page.wait_for_selector("#select-course-menu-item", state="visible", timeout=5_000)
    page.click("#select-course-menu-item")
    page.wait_for_selector("#select-course-modal", state="visible", timeout=5_000)
    # The list is filled from /api/courses, so wait for a row rather than
    # reading an empty container.
    page.wait_for_function(
        "document.querySelectorAll('#select-course-list button').length > 0",
        timeout=5_000,
    )


def course_buttons(page) -> list[dict]:
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('#select-course-list button'))
                .map(b => ({id: b.dataset.courseId, text: b.textContent, disabled: b.disabled}))"""
    )


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------


def test_the_root_lands_on_the_default_course(page, live_server):
    page.goto(live_server)
    assert page.url.rstrip("/").endswith(f"/c/{COURSE1_ID}")


def test_each_course_serves_its_own_units(page, live_server):
    page.goto(f"{live_server}/c/{COURSE2_ID}/")
    gp = GraderPage(page)
    gp.wait_for_grade_view()
    gp.wait_for_units_loaded()

    units = page.evaluate(
        "Array.from(document.getElementById('unit-select').options).map(o => o.textContent)"
    )
    assert any("Second Unit" in name for name in units), units
    assert not any("Test Unit" in name for name in units), units


def test_an_unknown_course_is_not_the_default_course(page, live_server):
    response = page.goto(f"{live_server}/c/no-such-course/")
    assert response.status == 404


# ---------------------------------------------------------------------------
# The picker
# ---------------------------------------------------------------------------


def test_the_picker_lists_every_course(page, live_server):
    page.goto(live_server)
    open_course_picker(page)

    listed = {row["id"] for row in course_buttons(page)}
    assert listed == {COURSE1_ID, COURSE2_ID}


def test_the_picker_marks_the_course_being_served(page, live_server):
    page.goto(live_server)
    open_course_picker(page)

    rows = {row["id"]: row for row in course_buttons(page)}
    assert rows[COURSE1_ID]["disabled"] is True
    assert rows[COURSE2_ID]["disabled"] is False


def test_the_picker_shows_names_not_ids(page, live_server):
    page.goto(live_server)
    open_course_picker(page)

    text = " ".join(row["text"] for row in course_buttons(page))
    assert "UI Test Course" in text
    assert "Second Test Course" in text
    assert "Fall 2026" in text


def test_choosing_a_course_navigates_into_it(page, live_server):
    page.goto(live_server)
    open_course_picker(page)

    page.click(f'#select-course-list button[data-course-id="{COURSE2_ID}"]')
    page.wait_for_url(f"**/c/{COURSE2_ID}/**", timeout=8_000)

    gp = GraderPage(page)
    gp.wait_for_grade_view()
    gp.wait_for_units_loaded()
    units = page.evaluate(
        "Array.from(document.getElementById('unit-select').options).map(o => o.textContent)"
    )
    assert any("Second Unit" in name for name in units), units


# ---------------------------------------------------------------------------
# Saved work is namespaced per course
# ---------------------------------------------------------------------------


def test_saved_work_lands_under_a_per_course_key(page, live_server):
    gp = GraderPage(page)
    gp.navigate(live_server)
    gp.set_api_key("test-key-ui")
    gp.wait_for_grade_view()
    gp.wait_for_units_loaded()
    gp.wait_for_questions_loaded()

    gp.submit_answer("The answer is 4.")
    gp.wait_for_result(timeout=20_000)

    keys = page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('llmgrader_session'))")
    assert f"llmgrader_session:{COURSE1_ID}" in keys


def test_two_courses_keep_separate_keys(page, live_server):
    """Separate keys, not a third level of nesting: one course's state can be
    cleared without touching another's."""
    for course_id in (COURSE1_ID, COURSE2_ID):
        page.goto(f"{live_server}/c/{course_id}/")
        gp = GraderPage(page)
        gp.wait_for_grade_view()
        gp.wait_for_units_loaded()
        gp.wait_for_questions_loaded()
        page.evaluate(
            """(id) => {
                const key = `llmgrader_session:${id}`;
                localStorage.setItem(key, JSON.stringify({marker: id}));
            }""",
            course_id,
        )

    stored = page.evaluate(
        """() => ({
            one: localStorage.getItem('llmgrader_session:ui_test_course'),
            two: localStorage.getItem('llmgrader_session:course2'),
        })"""
    )
    assert json.loads(stored["one"])["marker"] == COURSE1_ID
    assert json.loads(stored["two"])["marker"] == COURSE2_ID


@pytest.fixture()
def page_with_legacy_state(page, live_server):
    """A browser holding pre-namespacing saved work, as a returning student's is."""
    page.add_init_script(
        "window.localStorage.setItem('llmgrader_session', %s);"
        "window.sessionStorage.setItem('selectedUnit', 'Test Unit');"
        % json.dumps(json.dumps(LEGACY_SESSION))
    )
    return page


def test_legacy_saved_work_is_adopted_into_the_course_key(page_with_legacy_state, live_server):
    """The migration decision 7 calls for, and the reason it is not optional.

    Compared field by field rather than as a whole object: getSessionData
    fills defaults (parts, tools, solution_images) onto an entry as it reads
    it, so the stored value is the adopted work plus those keys.  What must
    survive is the work itself.
    """
    page = page_with_legacy_state
    gp = GraderPage(page)
    gp.navigate(live_server)
    gp.wait_for_grade_view()
    gp.wait_for_units_loaded()

    migrated = page.evaluate(f"localStorage.getItem('llmgrader_session:{COURSE1_ID}')")
    assert migrated is not None, "pre-upgrade work was not carried into the course key"

    entry = json.loads(migrated)["Test Unit"]["q1"]
    for field, value in LEGACY_SESSION["Test Unit"]["q1"].items():
        assert entry[field] == value, f"{field} did not survive the migration"


def test_the_legacy_key_is_left_in_place(page_with_legacy_state, live_server):
    """Kept for one release: a student who loads a cached old build, or who is
    served a rollback, still finds their work where that build looks for it."""
    page = page_with_legacy_state
    gp = GraderPage(page)
    gp.navigate(live_server)
    gp.wait_for_grade_view()
    gp.wait_for_units_loaded()

    legacy = page.evaluate("localStorage.getItem('llmgrader_session')")
    assert legacy is not None
    assert json.loads(legacy) == LEGACY_SESSION


def test_the_migration_does_not_overwrite_newer_per_course_work(page, live_server):
    """Only ever runs when the course key is absent."""
    page.add_init_script(
        "window.localStorage.setItem('llmgrader_session', %s);"
        "window.localStorage.setItem('llmgrader_session:%s', %s);"
        % (
            json.dumps(json.dumps(LEGACY_SESSION)),
            COURSE1_ID,
            json.dumps(json.dumps({"Test Unit": {"q1": {"student_solution": "newer"}}})),
        )
    )
    gp = GraderPage(page)
    gp.navigate(live_server)
    gp.wait_for_grade_view()
    gp.wait_for_units_loaded()

    kept = json.loads(page.evaluate(f"localStorage.getItem('llmgrader_session:{COURSE1_ID}')"))
    assert kept["Test Unit"]["q1"]["student_solution"] == "newer"


def test_the_selected_unit_is_namespaced_and_migrated(page_with_legacy_state, live_server):
    page = page_with_legacy_state
    gp = GraderPage(page)
    gp.navigate(live_server)
    gp.wait_for_grade_view()
    gp.wait_for_units_loaded()

    assert page.evaluate(f"sessionStorage.getItem('selectedUnit:{COURSE1_ID}')") == "Test Unit"
    assert page.evaluate("sessionStorage.getItem('selectedUnit')") == "Test Unit"


def test_user_preferences_are_not_namespaced(page, live_server):
    """selectedModel, gradeTimeout and the API key follow the user across
    courses -- they are preferences, not course work."""
    gp = GraderPage(page)
    gp.navigate(live_server)
    gp.set_api_key("test-key-ui")
    gp.wait_for_grade_view()

    page.goto(f"{live_server}/c/{COURSE2_ID}/")
    GraderPage(page).wait_for_grade_view()

    assert page.evaluate("localStorage.getItem('openai_api_key')") == "test-key-ui"
    scoped = page.evaluate(
        """() => Object.keys(localStorage)
                .filter(k => k.startsWith('openai_api_key:')
                          || k.startsWith('selectedModel:')
                          || k.startsWith('gradeTimeout:'))"""
    )
    assert scoped == []


# ---------------------------------------------------------------------------
# Portal-wide views still work under a course
# ---------------------------------------------------------------------------


def test_analytics_still_loads_from_inside_a_course(page, live_server):
    page.goto(f"{live_server}/c/{COURSE2_ID}/")
    switch_to_view(page, "analytics")
    page.wait_for_selector("#analytics-view", state="visible", timeout=8_000)

    sql = page.locator("#analytics-sql-input").input_value()
    assert f"WHERE course_id = '{COURSE2_ID}'" in sql
