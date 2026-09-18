"""One in-flight grading job per session, not per app instance.

``start_grade_job`` used to hold a single ``active_grade_job_id`` for the whole
process, so one student grading returned 409 ``already_running`` to every other
student.  That was already tight for one course and becomes the binding
constraint once a portal serves several (``plans/multicourse.md``, phase 4).

The property worth keeping is the narrow one: a *student* cannot start two jobs
at once, so a double-click or an impatient retry does not pay for two gradings.
The property being dropped is that nobody else can grade meanwhile.

Two ``test_client()``s mean two cookie jars, which means two sessions -- the
same thing two students in a browser are.
"""

import threading
import time
from pathlib import Path

import pytest

from llmgrader.app import create_app
from llmgrader.routes.api import APIController
from llmgrader.services.grader import Grader

GRADE_BODY = {
    "unit": "unit1",
    "qtag": "q1",
    "student_solution": "My answer",
    "provider": "openai",
    "api_key": "test-key",
}


def fake_load_unit_pkg(self):
    self.units = {
        "unit1": {
            "q1": {
                "question_text": "Question",
                "solution": "Solution",
                "grading_notes": "Notes",
            }
        }
    }
    self.units_order = []


class Gate:
    """A grade call that blocks until released, so a job can be held in flight."""

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self._lock = threading.Lock()

    # Patched onto Grader as an already-bound method, so `self` is this Gate
    # and the Grader instance is never passed: run_grade_job calls grade()
    # with keyword arguments only.
    def grade(self, **kwargs):
        with self._lock:
            self.calls += 1
        self.started.set()
        self.release.wait(timeout=5)
        return {"result": "pass", "full_explanation": "ok", "feedback": "ok"}


@pytest.fixture()
def controller_spy(monkeypatch) -> list:
    """Capture the APIController the app builds, for the locked helpers."""
    made: list[APIController] = []
    original = APIController.register

    def spy(self, app):
        made.append(self)
        return original(self, app)

    monkeypatch.setattr(APIController, "register", spy)
    return made


@pytest.fixture()
def app(tmp_path: Path, monkeypatch, controller_spy):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setenv("LLMGRADER_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LLMGRADER_AUTH_MODE", "dev-open")
    monkeypatch.setattr(Grader, "load_unit_pkg", fake_load_unit_pkg)

    flask_app = create_app(scratch_dir=str(scratch), soln_pkg=None)
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture()
def controller(app, controller_spy) -> APIController:
    assert controller_spy, "the app did not build an APIController"
    return controller_spy[-1]


@pytest.fixture()
def prefix(app) -> str:
    """``/c/<course_id>``: course content moved under the course blueprint in
    phase 5 (``plans/multicourse.md``, decision 5), and grading is course
    content -- it is the course's units and rubrics being graded against."""
    return f"/c/{app.registry.default_course_id}"


@pytest.fixture()
def gate(monkeypatch, controller):
    blocker = Gate()
    monkeypatch.setattr(Grader, "grade", blocker.grade)
    yield blocker

    # Let every worker out before monkeypatch undoes the patch.  A thread still
    # queued when the real Grader.grade comes back would make a live OpenAI
    # call with a fake key -- which shows up as a 401 logged after the test
    # summary, long after the test that caused it.
    blocker.release.set()
    deadline = time.time() + 5.0
    while time.time() < deadline:
        with controller.grade_job_lock:
            busy = any(
                job["status"] in controller.ACTIVE_GRADE_JOB_STATES
                for job in controller.grade_jobs.values()
            )
        if not busy:
            return
        time.sleep(0.01)
    raise AssertionError("a grading worker was still in flight at teardown")


def wait_for_status(client, prefix: str, job_id: str, wanted: set[str], timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    payload = None
    while time.time() < deadline:
        response = client.get(f"{prefix}/grade/jobs/{job_id}")
        assert response.status_code == 200, response.get_json()
        payload = response.get_json()
        if payload["status"] in wanted:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never reached {wanted}; last was {payload!r}")


# ---------------------------------------------------------------------------
# The change
# ---------------------------------------------------------------------------


def test_two_sessions_can_grade_at_the_same_time(app, prefix, gate: Gate) -> None:
    """The whole point of the phase: one student no longer blocks another."""
    alice, bob = app.test_client(), app.test_client()
    first = alice.post(f"{prefix}/grade/jobs", json=GRADE_BODY)
    assert first.status_code == 202
    assert gate.started.wait(timeout=2.0)

    # Alice's job is in flight and deliberately not released.
    second = bob.post(f"{prefix}/grade/jobs", json=GRADE_BODY)
    assert second.status_code == 202, second.get_json()
    assert second.get_json()["job_id"] != first.get_json()["job_id"]

    gate.release.set()

    for client, response in ((alice, first), (bob, second)):
        payload = wait_for_status(client, prefix, response.get_json()["job_id"], {"done"})
        assert payload["result"] == "pass"

    assert gate.calls == 2, "both sessions should have reached the grader"


def test_one_session_still_cannot_start_two(app, prefix, gate: Gate) -> None:
    """A double-click must not pay for two gradings."""
    alice = app.test_client()
    first = alice.post(f"{prefix}/grade/jobs", json=GRADE_BODY)
    assert first.status_code == 202
    assert gate.started.wait(timeout=2.0)

    second = alice.post(f"{prefix}/grade/jobs", json=GRADE_BODY)
    assert second.status_code == 409
    payload = second.get_json()
    assert payload["status"] == "already_running"
    assert "already in progress" in payload["message"]
    # The 409 describes the job that is actually running, not the refused one.
    assert payload["job_id"] == first.get_json()["job_id"]

    gate.release.set()
    wait_for_status(alice, prefix, first.get_json()["job_id"], {"done"})

    assert gate.calls == 1


def test_a_session_can_grade_again_once_its_job_finishes(app, prefix, gate: Gate) -> None:
    alice = app.test_client()
    first = alice.post(f"{prefix}/grade/jobs", json=GRADE_BODY)
    assert first.status_code == 202
    gate.release.set()
    wait_for_status(alice, prefix, first.get_json()["job_id"], {"done"})

    second = alice.post(f"{prefix}/grade/jobs", json=GRADE_BODY)
    assert second.status_code == 202, second.get_json()


def test_a_failed_job_frees_its_sessions_slot(app, prefix, monkeypatch) -> None:
    """An exception in the worker must not wedge that student out of grading."""
    def exploding_grade(self, **kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(Grader, "grade", exploding_grade)

    alice = app.test_client()
    first = alice.post(f"{prefix}/grade/jobs", json=GRADE_BODY)
    assert first.status_code == 202
    wait_for_status(alice, prefix, first.get_json()["job_id"], {"error"})

    second = alice.post(f"{prefix}/grade/jobs", json=GRADE_BODY)
    assert second.status_code == 202, second.get_json()

    # Wait for the retry to settle too.  Leaving a worker in flight lets
    # monkeypatch restore the real Grader.grade underneath it, which then makes
    # a live OpenAI call with the fake key in GRADE_BODY.
    wait_for_status(alice, prefix, second.get_json()["job_id"], {"error"})


# ---------------------------------------------------------------------------
# What must survive the change: expiry, pruning, timeout
# ---------------------------------------------------------------------------


def test_a_stale_job_is_expired_and_frees_the_slot(app, prefix, controller, gate: Gate) -> None:
    """A student who closed the tab mid-grade must not hold their slot for good.

    The deadline is pushed into the past directly rather than waited out, so
    the test exercises the sweep instead of the clock.
    """
    alice = app.test_client()
    first = alice.post(f"{prefix}/grade/jobs", json=GRADE_BODY)
    assert first.status_code == 202
    assert gate.started.wait(timeout=2.0)
    job_id = first.get_json()["job_id"]

    with controller.grade_job_lock:
        controller.grade_jobs[job_id]["deadline_ts"] = time.time() - 1.0

    second = alice.post(f"{prefix}/grade/jobs", json=GRADE_BODY)
    assert second.status_code == 202, second.get_json()

    assert controller.grade_jobs[job_id]["status"] == "timed_out"
    gate.release.set()


def test_one_sessions_stale_job_does_not_disturb_another(app, prefix, controller, gate: Gate) -> None:
    """The sweep visits every session, and must time out only the late one."""
    alice, bob = app.test_client(), app.test_client()
    first = alice.post(f"{prefix}/grade/jobs", json=GRADE_BODY)
    assert first.status_code == 202
    assert gate.started.wait(timeout=2.0)
    second = bob.post(f"{prefix}/grade/jobs", json=GRADE_BODY)
    assert second.status_code == 202

    stale_id = first.get_json()["job_id"]
    healthy_id = second.get_json()["job_id"]
    with controller.grade_job_lock:
        controller.grade_jobs[stale_id]["deadline_ts"] = time.time() - 1.0
        controller.expire_stale_active_jobs_locked()

        assert controller.grade_jobs[stale_id]["status"] == "timed_out"
        assert controller.grade_jobs[healthy_id]["status"] in controller.ACTIVE_GRADE_JOB_STATES
        assert healthy_id in controller.active_job_ids_locked()
        assert stale_id not in controller.active_job_ids_locked()

    gate.release.set()


def test_retention_pruning_spares_every_sessions_active_job(controller) -> None:
    """Pruning used to spare one job id; it must now spare one per session."""
    now = time.time()
    controller.grade_jobs = {
        "running-alice": {"job_id": "running-alice", "session_id": "alice", "status": "running"},
        "running-bob": {"job_id": "running-bob", "session_id": "bob", "status": "running"},
        "old-alice": {
            "job_id": "old-alice",
            "session_id": "alice",
            "status": "done",
            "finished_at_ts": now - controller.GRADE_JOB_RETENTION_SECONDS - 60,
        },
        "recent-bob": {
            "job_id": "recent-bob",
            "session_id": "bob",
            "status": "done",
            "finished_at_ts": now,
        },
    }
    controller.active_job_by_session = {"alice": "running-alice", "bob": "running-bob"}

    with controller.grade_job_lock:
        controller.prune_old_grade_jobs_locked()

    assert set(controller.grade_jobs) == {"running-alice", "running-bob", "recent-bob"}


def test_releasing_a_slot_does_not_clobber_a_newer_job(controller) -> None:
    """A late worker finishing must not free the slot its session has since refilled.

    The timed-out job's thread is still running when the student starts
    another; if its completion released the slot by session alone, that
    student would hold two concurrent slots from then on.
    """
    stale = {"job_id": "stale", "session_id": "alice", "status": "timed_out"}
    current = {"job_id": "current", "session_id": "alice", "status": "running"}
    controller.grade_jobs = {"stale": stale, "current": current}
    controller.active_job_by_session = {"alice": "current"}

    with controller.grade_job_lock:
        controller.release_active_job_locked(stale)

    assert controller.active_job_by_session == {"alice": "current"}


def test_a_session_key_is_never_none(controller) -> None:
    """A cookie-less request falls into one shared slot rather than a None key."""
    assert controller.grade_job_session_key(None) == APIController.ANONYMOUS_SESSION_KEY
    assert controller.grade_job_session_key("") == APIController.ANONYMOUS_SESSION_KEY
    assert controller.grade_job_session_key("a1b2c3d4") == "a1b2c3d4"
