"""Demo code in Manage Courses: ``plans/demo_code_admin.md``.

The admin endpoints that show which commit of a course's demo repo the MCP
serves, check GitHub for a newer one, and start an update.  Offline: the demo
repo is the local one ``test_course_code.py`` builds.  The test that matters
most is the time limit -- on Render one sync worker serves every student, so
no admin request may wait on git.
"""

from __future__ import annotations

import json
import os
import threading
import time

import pytest

import llmgrader.coursemcp.code as code_module
from test_course_code import commit_all, make_app
from test_course_mcp import within

CODE_ROUTES = [
    ("get", "/api/admin/courses/{id}/code"),
    ("post", "/api/admin/courses/{id}/code/check"),
    ("post", "/api/admin/courses/{id}/code/update"),
]


@pytest.fixture()
def app(tmp_path, monkeypatch):
    return make_app(tmp_path, monkeypatch)


@pytest.fixture()
def client(app):
    return app.test_client()


def courses(client) -> dict:
    response = client.get("/api/admin/courses")
    assert response.status_code == 200
    return {course["id"]: course for course in response.get_json()["courses"]}


def code_of(client, course_id="alpha"):
    response = client.get(f"/api/admin/courses/{course_id}/code")
    assert response.status_code == 200
    return response.get_json()["code"]


def code_dir(tmp_path, course_id="alpha"):
    path = tmp_path / "storage" / "courses" / course_id / "code"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write(path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def sync_of(app, course_id="alpha"):
    return app.course_mcp.code.sync_for(course_id)


def join(sync) -> None:
    for thread in (sync._thread, sync._check_thread):
        if thread is not None:
            thread.join(30)


# ---------------------------------------------------------------------------
# The code object
# ---------------------------------------------------------------------------


def test_a_course_with_code_gets_a_code_object(client) -> None:
    code = courses(client)["alpha"]["code"]
    assert code["enabled"] is True
    assert code["repo"] == "https://github.com/test/hwdesign" and code["branch"] == "main"
    assert code["served"] is None and code["status"] == "never_synced"
    assert code_of(client) == code


def test_a_course_without_code_gets_null(client) -> None:
    assert courses(client)["beta"]["code"] is None
    assert code_of(client, "beta") is None


def test_code_disabled_on_the_portal(tmp_path, monkeypatch) -> None:
    client = make_app(tmp_path, monkeypatch, code_switch=False).test_client()
    listed = courses(client)
    assert listed["alpha"]["code"] == {"enabled": False}
    assert listed["beta"]["code"] == {"enabled": False}
    response = client.post("/api/admin/courses/alpha/code/update")
    assert response.status_code == 409 and "LLMGRADER_MCP_CODE" in response.get_json()["error"]


def test_an_archived_course_has_no_code_object_and_404s(client) -> None:
    assert client.delete("/api/admin/courses/alpha").status_code == 200
    assert "code" not in courses(client)["alpha"]
    for method, route in CODE_ROUTES:
        assert getattr(client, method)(route.format(id="alpha")).status_code == 404


def test_a_course_without_code_refuses_check_and_update(client) -> None:
    for method, route in CODE_ROUTES[1:]:
        assert getattr(client, method)(route.format(id="beta")).status_code == 404


SERVED = "a" * 40
NEWER = "b" * 40


@pytest.mark.parametrize("files, status", [
    ({}, "never_synced"),
    ({"state": {"commit": SERVED, "synced_at": 1.0}}, "unknown"),
    ({"state": {"commit": SERVED}, "remote": {"head": SERVED, "checked_at": 2.0, "error": None}},
     "up_to_date"),
    ({"state": {"commit": SERVED}, "remote": {"head": NEWER, "checked_at": 2.0, "error": None}},
     "update_available"),
    ({"state": {"commit": SERVED, "last_error": "git fetch failed"},
      "remote": {"head": SERVED, "checked_at": 2.0, "error": None}}, "error"),
    ({"state": {"commit": SERVED}, "remote": {"head": None, "checked_at": 2.0,
                                              "error": "git ls-remote timed out"}}, "error"),
    ({"state": {"commit": SERVED}, "remote": {"head": NEWER, "checked_at": 2.0, "error": None},
      "progress": "fresh"}, "syncing"),
    ({"state": {"commit": SERVED}, "remote": {"head": NEWER, "checked_at": 2.0, "error": None},
      "progress": "abandoned"}, "update_available"),
])
def test_each_status_from_the_files_on_disk(client, tmp_path, files, status) -> None:
    directory = code_dir(tmp_path)
    if "state" in files:
        write(directory / "state.json", files["state"])
    if "remote" in files:
        write(directory / "remote.json", files["remote"])
    if "progress" in files:
        age = 1 if files["progress"] == "fresh" else code_module.PROGRESS_STALE_S + 60
        now = time.time()
        write(directory / "progress.json", {"stage": "fetching", "started_at": now - age,
                                            "updated_at": now - age, "pid": os.getpid() + 1})
    code = code_of(client)
    assert code["status"] == status
    assert courses(client)["alpha"]["code"]["status"] == status
    if "progress" in files:
        assert code["progress"]["stage"] == "fetching"
        assert code["progress"]["stale"] is (files["progress"] == "abandoned")


def test_the_served_commit_carries_its_date_and_subject(client, tmp_path) -> None:
    write(code_dir(tmp_path) / "state.json",
          {"commit": SERVED, "committed_at": "2026-10-08T21:14:03-04:00",
           "subject": "Rebuild the streaming demos", "synced_at": 5.0, "last_attempt": 5.0,
           "last_error": None})
    code = code_of(client)
    assert code["served"] == {"commit": SERVED, "committed_at": "2026-10-08T21:14:03-04:00",
                              "subject": "Rebuild the streaming demos"}
    assert code["synced_at"] == 5.0 and code["last_error"] is None


# ---------------------------------------------------------------------------
# Check and update
# ---------------------------------------------------------------------------


def test_check_then_update_brings_in_a_new_commit(app, client, tmp_path) -> None:
    response = client.post("/api/admin/courses/alpha/code/update")
    assert response.status_code == 202 and response.get_json() == {"started": True}
    join(sync_of(app))
    first = code_of(client)
    assert first["status"] == "up_to_date" and first["served"]["subject"] == "demos"

    repo = tmp_path / "hwdesign"
    (repo / "demos/fsm/counter.sv").write_text("module counter;\n// v2\nendmodule\n",
                                               encoding="utf-8")
    new = commit_all(repo, "Second demo commit")
    response = client.post("/api/admin/courses/alpha/code/check")
    assert response.status_code == 202 and response.get_json() == {"started": True}
    join(sync_of(app))
    checked = code_of(client)
    assert checked["status"] == "update_available" and checked["remote"]["head"] == new

    client.post("/api/admin/courses/alpha/code/update")
    join(sync_of(app))
    updated = code_of(client)
    assert updated["status"] == "up_to_date"
    assert updated["served"]["commit"] == new
    assert updated["served"]["subject"] == "Second demo commit"
    assert updated["progress"] is None
    assert sync_of(app).snapshot.commit == new        # and the MCP serves it


def hang_git(monkeypatch, release: threading.Event, calls: list) -> None:
    """run_git that blocks on *every* command until *release* is set."""
    real = code_module.run_git

    def run(args, **kwargs):
        calls.append(args[0])
        release.wait(60)
        return real(args, **kwargs)

    monkeypatch.setattr(code_module, "run_git", run)


def test_every_endpoint_answers_while_git_hangs(app, client, monkeypatch) -> None:
    """The Render constraint: one sync worker, so no admin request may wait
    on git.  Every call here must return in under a second while git hangs."""
    # A real copy on disk first, so a request that ran git anywhere -- even a
    # local rev-parse in the mirror -- would hang below, not return early.
    sync = sync_of(app)
    assert sync.sync_now() is True
    courses(client)                          # build the graders: not what is timed
    release, calls = threading.Event(), []
    hang_git(monkeypatch, release, calls)
    try:
        listed = within(1, lambda: client.get("/api/admin/courses"))
        assert listed.status_code == 200
        update = within(1, lambda: client.post("/api/admin/courses/alpha/code/update"))
        assert update.status_code == 202 and update.get_json()["started"] is True
        check = within(1, lambda: client.post("/api/admin/courses/alpha/code/check"))
        assert check.status_code == 202 and check.get_json()["started"] is True
        polled = within(1, lambda: client.get("/api/admin/courses/alpha/code"))
        assert polled.status_code == 200
        # Both threads really are stuck in git.
        deadline = time.monotonic() + 10
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert sync._thread.is_alive() and sync._check_thread.is_alive()
        # A second click while the sync runs starts nothing, and still returns.
        again = within(1, lambda: client.post("/api/admin/courses/alpha/code/update"))
        assert again.status_code == 202 and again.get_json() == {"started": False}
        recheck = within(1, lambda: client.post("/api/admin/courses/alpha/code/check"))
        assert recheck.get_json() == {"started": False}
        assert within(1, lambda: client.get("/api/admin/courses")).status_code == 200
    finally:
        release.set()
        join(sync)


def test_each_endpoint_refuses_a_non_admin(client, monkeypatch) -> None:
    monkeypatch.setenv("LLMGRADER_AUTH_MODE", "normal")
    assert client.get("/api/admin/courses").status_code == 403
    for method, route in CODE_ROUTES:
        assert getattr(client, method)(route.format(id="alpha")).status_code == 403


def test_each_endpoint_404s_an_unknown_course(client) -> None:
    for method, route in CODE_ROUTES:
        response = getattr(client, method)(route.format(id="nosuch"))
        assert response.status_code == 404, route
