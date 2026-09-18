"""Course in the URL: /c/<course_id>/ is the only thing that says which course.

``plans/multicourse.md`` decisions 5 and 6.  Two properties matter here and
both fail silently if they regress:

* an unknown course is a 404, never a quiet fall back to the default -- being
  graded against the wrong course is worse than an error page;
* ``/pkg_assets`` resolves against the course in the path, so course A's
  question cannot pull a figure out of course B's package.  That failure is a
  wrong picture, not an exception, so nothing downstream would report it.

The session's remembered course is tested here too, for what it is *not*: it
decides where a bare ``/`` lands and nothing else.
"""

import json
from pathlib import Path

import pytest

from llmgrader.app import create_app

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"only-in-one-course"

UNIT_XML = """<unit id="{unit_id}" title="{unit_title}" version="1.0">
  <question qtag="{qtag}">
    <question_text><![CDATA[<p>{question}</p><img src="/pkg_assets/{image}">]]></question_text>
    <solution><![CDATA[<p>{answer}</p>]]></solution>
    <grading_notes><![CDATA[Accept it.]]></grading_notes>
    <parts>
      <part>
        <part_label>all</part_label>
        <points>1</points>
      </part>
    </parts>
  </question>
</unit>
"""

CONFIG_XML = """<llmgrader>
  <course>
    <course_id>{course_id}</course_id>
    <name>{name}</name>
    <term>{term}</term>
  </course>
  <units>
    <unit>
      <name>{unit_title}</name>
      <source>{unit_file}</source>
      <destination>{unit_file}</destination>
    </unit>
  </units>
</llmgrader>
"""

COURSES = {
    "alpha": {
        "name": "Alpha Course", "term": "Spring 2026",
        "unit_title": "Alpha Unit", "unit_file": "alpha_unit.xml", "unit_id": "alpha_unit",
        "qtag": "a1", "question": "Alpha question", "answer": "Alpha answer",
        "image": "alpha_images/figure.png",
    },
    "beta": {
        "name": "Beta Course", "term": "Fall 2026",
        "unit_title": "Beta Unit", "unit_file": "beta_unit.xml", "unit_id": "beta_unit",
        "qtag": "b1", "question": "Beta question", "answer": "Beta answer",
        "image": "beta_images/figure.png",
    },
}


def write_package(root: Path, course_id: str) -> None:
    spec = COURSES[course_id]
    root.mkdir(parents=True, exist_ok=True)
    (root / "llmgrader_config.xml").write_text(
        CONFIG_XML.format(course_id=course_id, **spec), encoding="utf-8"
    )
    (root / spec["unit_file"]).write_text(UNIT_XML.format(**spec), encoding="utf-8")
    image = root / spec["image"]
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(PNG_BYTES)


@pytest.fixture()
def two_course_app(tmp_path: Path, monkeypatch):
    """A portal serving two registered courses, alpha (default) and beta."""
    storage = tmp_path / "storage"
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(storage))
    monkeypatch.setenv("LLMGRADER_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LLMGRADER_AUTH_MODE", "dev-open")

    courses_root = storage / "courses"
    courses_root.mkdir(parents=True)
    for course_id in COURSES:
        write_package(courses_root / course_id / "soln_pkg", course_id)

    courses_root.joinpath("courses.json").write_text(json.dumps({
        "courses": [
            {"id": cid, "name": spec["name"], "semester": spec["term"],
             "created_at": "2026-01-01T00:00:00+00:00", "id_source": "authored"}
            for cid, spec in COURSES.items()
        ],
        "default": "alpha",
    }), encoding="utf-8")

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    app = create_app(scratch_dir=str(scratch), soln_pkg=None)
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(two_course_app):
    return two_course_app.test_client()


# ---------------------------------------------------------------------------
# Each course serves its own content
# ---------------------------------------------------------------------------


def test_both_courses_are_registered(two_course_app) -> None:
    assert {entry.id for entry in two_course_app.registry.courses()} == {"alpha", "beta"}
    assert two_course_app.registry.default_course_id == "alpha"


@pytest.mark.parametrize("course_id", ["alpha", "beta"])
def test_units_come_from_the_course_in_the_path(client, course_id) -> None:
    payload = client.get(f"/c/{course_id}/units").get_json()

    names = [item["name"] for item in payload["items"]]
    assert names == [COURSES[course_id]["unit_title"]]
    assert payload["course"]["course_id"] == course_id


@pytest.mark.parametrize("course_id", ["alpha", "beta"])
def test_a_question_comes_from_the_course_in_the_path(client, course_id) -> None:
    spec = COURSES[course_id]
    payload = client.get(f"/c/{course_id}/unit/{spec['unit_title']}").get_json()

    assert list(payload["items"]) == [spec["qtag"]]
    assert spec["question"] in payload["items"][spec["qtag"]]["question_text"]


def test_one_courses_unit_is_not_served_by_the_other(client) -> None:
    resp = client.get(f"/c/alpha/unit/{COURSES['beta']['unit_title']}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# An unknown course is an error, not a fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [
    "/c/gamma/units",
    "/c/gamma/",
    "/c/gamma/unit/Alpha%20Unit",
    "/c/gamma/pkg_assets/alpha_images/figure.png",
])
def test_an_unknown_course_is_404(client, path) -> None:
    """Never the default course's content under another course's name."""
    resp = client.get(path)
    assert resp.status_code == 404


def test_course_content_is_not_served_unprefixed(client) -> None:
    """There is no unprefixed /units left to fall back to a course.

    This is the half of the change that is easy to leave half-done: adding the
    prefixed route while the old one still answers means the leak is still
    reachable, just not linked to.
    """
    for path in ("/units", "/unit/Alpha%20Unit", "/pkg_assets/alpha_images/figure.png"):
        assert client.get(path).status_code == 404, path


# ---------------------------------------------------------------------------
# /pkg_assets, the sharpest hazard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("course_id", ["alpha", "beta"])
def test_pkg_assets_serves_its_own_courses_package(client, course_id) -> None:
    resp = client.get(f"/c/{course_id}/pkg_assets/{COURSES[course_id]['image']}")

    assert resp.status_code == 200
    assert resp.data == PNG_BYTES


def test_pkg_assets_does_not_reach_into_another_course(client) -> None:
    """The cross-course content leak decision 6 exists to prevent.

    It fails as a wrong figure rather than an error, so there is nothing to
    notice at runtime -- only this test.
    """
    resp = client.get(f"/c/alpha/pkg_assets/{COURSES['beta']['image']}")
    assert resp.status_code == 404


def test_pkg_assets_still_blocks_traversal(client) -> None:
    resp = client.get("/c/alpha/pkg_assets/../../../etc/passwd")
    assert resp.status_code in (400, 404)


def test_question_html_carries_course_scoped_asset_urls(client) -> None:
    """The served HTML is self-contained: the parser prefixes the URLs.

    If it did not, the browser would request /pkg_assets/... unprefixed, which
    no longer resolves at all -- so a missing prefix is a broken image for
    every question that has one.
    """
    spec = COURSES["alpha"]
    payload = client.get(f"/c/alpha/unit/{spec['unit_title']}").get_json()
    html = payload["items"][spec["qtag"]]["question_text"]

    assert f'/c/alpha/pkg_assets/{spec["image"]}' in html
    assert 'src="/pkg_assets/' not in html


# ---------------------------------------------------------------------------
# "/" and the remembered course
# ---------------------------------------------------------------------------


def test_root_redirects_to_the_default_course(client) -> None:
    resp = client.get("/")

    assert resp.status_code in (301, 302, 308)
    assert resp.headers["Location"].endswith("/c/alpha/")


def test_root_redirects_to_the_course_last_visited(client) -> None:
    client.get("/c/beta/")

    resp = client.get("/")
    assert resp.headers["Location"].endswith("/c/beta/")


def test_dashboard_redirects_into_a_course(client) -> None:
    resp = client.get("/dashboard")

    assert resp.status_code in (301, 302, 308)
    assert resp.headers["Location"].endswith("/c/alpha/dashboard")


def test_a_remembered_course_that_no_longer_exists_falls_back(two_course_app) -> None:
    """A stale session value must not strand someone on a 404."""
    client = two_course_app.test_client()
    with client.session_transaction() as sess:
        sess["course_id"] = "deleted-course"

    resp = client.get("/")
    assert resp.headers["Location"].endswith("/c/alpha/")


def test_the_session_is_not_the_authority_for_a_request(client) -> None:
    """The path wins over the remembered course, always.

    session["course_id"] exists for the "/" redirect.  If it ever became the
    authority, a stale cookie would silently grade someone against the wrong
    course -- which is the whole reason the id is in the path.
    """
    client.get("/c/beta/")  # remembers beta

    payload = client.get("/c/alpha/units").get_json()
    assert [item["name"] for item in payload["items"]] == [COURSES["alpha"]["unit_title"]]
    assert payload["course"]["course_id"] == "alpha"


# ---------------------------------------------------------------------------
# /api/courses, for the picker
# ---------------------------------------------------------------------------


def test_api_courses_lists_every_course(client) -> None:
    payload = client.get("/api/courses").get_json()

    by_id = {course["id"]: course for course in payload["courses"]}
    assert set(by_id) == {"alpha", "beta"}
    assert by_id["alpha"]["name"] == "Alpha Course"
    assert by_id["alpha"]["semester"] == "Spring 2026"
    assert by_id["beta"]["name"] == "Beta Course"
    assert payload["default"] == "alpha"


def test_api_courses_reports_whether_a_package_is_loaded(client) -> None:
    payload = client.get("/api/courses").get_json()

    assert all(course["loaded"] for course in payload["courses"])


def test_api_courses_names_the_current_course(client) -> None:
    """Off a course route it reports the default; the picker ticks `current`."""
    assert client.get("/api/courses").get_json()["current"] == "alpha"


# ---------------------------------------------------------------------------
# Admin and analytics stay global
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/admin", "/admin/dbviewer/schema", "/api/models", "/api/auth/session"])
def test_portal_wide_routes_stay_unprefixed(client, path) -> None:
    """The admin list, the preferences file and the database are portal-wide."""
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/c/alpha/admin", "/c/alpha/api/models"])
def test_portal_wide_routes_are_not_also_mounted_under_a_course(client, path) -> None:
    assert client.get(path).status_code == 404
