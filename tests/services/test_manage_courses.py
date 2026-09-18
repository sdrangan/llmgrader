"""Adding, archiving and re-loading courses from the admin surface.

``plans/multicourse.md`` decision 10.  Three things here are worth more than
the rest, because each one destroys something that cannot be got back:

* a bad upload must not take a live course down -- extraction is staged and
  parsed before anything is swapped;
* an archive for the wrong course must be refused, not loaded, because every
  archive on disk is called ``soln_package.zip``;
* archiving a course must keep its grades.
"""

import io
import json
import zipfile
from pathlib import Path

import pytest

from llmgrader.app import create_app
from llmgrader.services.course_registry import CourseRegistry, ID_SOURCE_FALLBACK
from llmgrader.services.portal_storage import PortalStorage

UNIT_XML = """<unit id="{unit_id}" title="{unit_title}" version="1.0">
  <question qtag="{qtag}">
    <question_text><![CDATA[<p>{question}</p>]]></question_text>
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
{course_id_element}    <name>{name}</name>
    <semester>{semester}</semester>
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

PACKAGES = {
    "alpha": dict(
        name="Alpha Course", semester="Spring 2026", unit_title="Alpha Unit",
        unit_file="alpha_unit.xml", unit_id="alpha_unit", qtag="a1",
        question="Alpha question", answer="Alpha answer",
    ),
    "beta": dict(
        name="Beta Course", semester="Fall 2026", unit_title="Beta Unit",
        unit_file="beta_unit.xml", unit_id="beta_unit", qtag="b1",
        question="Beta question", answer="Beta answer",
    ),
}


def package_bytes(course_id: str | None, **overrides) -> bytes:
    """A course package zip, in memory, as an admin would upload one."""
    spec = dict(PACKAGES.get(course_id or "alpha", PACKAGES["alpha"]))
    spec.update(overrides)
    element = f"    <course_id>{course_id}</course_id>\n" if course_id else ""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "llmgrader_config.xml",
            CONFIG_XML.format(course_id_element=element, **spec),
        )
        archive.writestr(spec["unit_file"], UNIT_XML.format(**spec))
    return buffer.getvalue()


def upload(client, data: bytes, *, name: str = "soln_package.zip", course_id: str | None = None):
    """POST an archive to Load Course Package, optionally naming a target."""
    payload = {"file": (io.BytesIO(data), name)}
    if course_id is not None:
        payload["course_id"] = course_id
    return client.post("/admin/upload", data=payload, content_type="multipart/form-data")


def add_course(client, data: bytes, *, name: str = "soln_package.zip"):
    return client.post(
        "/api/admin/courses",
        data={"file": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )


def write_package(root: Path, course_id: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(package_bytes(course_id))) as archive:
        archive.extractall(root)


@pytest.fixture()
def storage_root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "storage"
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(root))
    monkeypatch.setenv("LLMGRADER_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LLMGRADER_AUTH_MODE", "dev-open")
    monkeypatch.delenv("LLMGRADER_MIGRATE_COURSE_ID", raising=False)
    return root


@pytest.fixture()
def make_app(tmp_path: Path, storage_root: Path):
    counter = {"n": 0}

    def _make():
        counter["n"] += 1
        scratch = tmp_path / f"scratch{counter['n']}"
        scratch.mkdir()
        app = create_app(scratch_dir=str(scratch), soln_pkg=None)
        app.config["TESTING"] = True
        return app

    return _make


@pytest.fixture()
def one_course_app(storage_root: Path, make_app):
    """A portal already serving 'alpha'."""
    write_package(storage_root / "courses" / "alpha" / "soln_pkg", "alpha")
    (storage_root / "courses" / "courses.json").write_text(json.dumps({
        "courses": [{"id": "alpha", "name": "Alpha Course", "semester": "Spring 2026",
                     "created_at": "2026-01-01T00:00:00+00:00", "id_source": "authored"}],
        "default": "alpha",
    }), encoding="utf-8")
    return make_app()


# ---------------------------------------------------------------------------
# Validate, then swap
# ---------------------------------------------------------------------------


def test_a_corrupt_zip_leaves_the_course_serving(one_course_app) -> None:
    """The failure decision 10 calls out: rmtree first, discover the problem later."""
    client = one_course_app.test_client()
    before = client.get("/c/alpha/units").get_json()

    response = upload(client, b"this is not a zip at all", course_id="alpha")

    assert response.status_code == 400
    assert "not a valid zip" in response.get_json()["error"]
    assert client.get("/c/alpha/units").get_json() == before

    # And the package is still on disk, not a directory that was emptied and
    # never refilled.
    served = Path(one_course_app.registry.soln_pkg_path("alpha"))
    assert (served / "llmgrader_config.xml").exists()


def test_a_package_that_does_not_parse_leaves_the_course_serving(one_course_app) -> None:
    """Unzipping is not the only way an upload can fail."""
    client = one_course_app.test_client()
    before = client.get("/c/alpha/units").get_json()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("llmgrader_config.xml", "<llmgrader><this is not xml")
    response = upload(client, buffer.getvalue(), course_id="alpha")

    assert response.status_code == 400
    assert client.get("/c/alpha/units").get_json() == before


def test_a_good_package_replaces_the_old_one(one_course_app) -> None:
    client = one_course_app.test_client()

    response = upload(
        client,
        package_bytes("alpha", unit_title="Alpha Unit Revised"),
        course_id="alpha",
    )

    assert response.status_code == 200, response.get_json()
    names = [item["name"] for item in client.get("/c/alpha/units").get_json()["items"]]
    assert names == ["Alpha Unit Revised"]


def test_the_swap_leaves_no_staging_directory_behind(one_course_app) -> None:
    client = one_course_app.test_client()
    upload(client, package_bytes("alpha"), course_id="alpha")

    scratch = Path(one_course_app.registry.scratch_path("alpha"))
    leftovers = [p.name for p in scratch.glob("upload-staging-*")]
    assert leftovers == []


# ---------------------------------------------------------------------------
# The id-mismatch guard
# ---------------------------------------------------------------------------


def test_a_package_for_another_course_is_refused(one_course_app) -> None:
    """The likelier mistake: right course chosen, wrong soln_package.zip picked."""
    client = one_course_app.test_client()
    before = client.get("/c/alpha/units").get_json()

    response = upload(client, package_bytes("beta"), course_id="alpha")

    assert response.status_code == 409
    payload = response.get_json()
    assert payload["archive_course_id"] == "beta"
    assert payload["target_course_id"] == "alpha"
    # Both courses named, so the admin can see which file they grabbed.
    assert "Beta Course" in payload["error"]
    assert "alpha" in payload["error"]
    assert "Nothing was changed" in payload["error"]

    assert client.get("/c/alpha/units").get_json() == before


def test_a_refused_upload_is_not_offered_a_rename(one_course_app) -> None:
    """Renaming is a three-store migration and is deliberately not built.

    The message has to send the admin somewhere real instead of implying a
    confirmation step that does not exist.
    """
    client = one_course_app.test_client()
    message = upload(client, package_bytes("beta"), course_id="alpha").get_json()["error"]

    assert "rename" not in message.lower()
    assert "add it as a new course" in message.lower()


def test_an_unknown_target_course_is_404(one_course_app) -> None:
    client = one_course_app.test_client()
    response = upload(client, package_bytes("alpha"), course_id="nonexistent")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Add Course
# ---------------------------------------------------------------------------


def test_add_course_reads_its_identity_from_the_package(one_course_app) -> None:
    """No name is typed anywhere: the package is the only source of identity."""
    client = one_course_app.test_client()

    response = add_course(client, package_bytes("beta"))

    assert response.status_code == 201, response.get_json()
    course = response.get_json()["course"]
    assert course["id"] == "beta"
    assert course["name"] == "Beta Course"
    assert course["semester"] == "Fall 2026"
    assert course["loaded"] is True


def test_an_added_course_is_served_immediately(one_course_app) -> None:
    client = one_course_app.test_client()
    add_course(client, package_bytes("beta"))

    payload = client.get("/c/beta/units").get_json()
    assert [item["name"] for item in payload["items"]] == ["Beta Unit"]


def test_adding_a_course_that_already_exists_is_refused_and_names_it(one_course_app) -> None:
    client = one_course_app.test_client()

    response = add_course(client, package_bytes("alpha"))

    assert response.status_code == 409
    payload = response.get_json()
    assert payload["course_id"] == "alpha"
    assert "Alpha Course" in payload["error"]
    assert "Load Course Package" in payload["error"]


def test_a_package_without_a_course_id_gets_a_derived_one(one_course_app) -> None:
    """Packages predating <course_id> still have to become courses."""
    client = one_course_app.test_client()

    response = add_course(
        client,
        package_bytes(None, name="Signals and Systems", semester="Fall 2027"),
    )

    assert response.status_code == 201, response.get_json()
    assert response.get_json()["course"]["id"] == "signals-and-systems-fall-2027"


def test_a_corrupt_archive_does_not_create_a_course(one_course_app) -> None:
    client = one_course_app.test_client()

    response = add_course(client, b"not a zip")

    assert response.status_code == 400
    listed = [c["id"] for c in client.get("/api/admin/courses").get_json()["courses"]]
    assert listed == ["alpha"]


# ---------------------------------------------------------------------------
# Archiving keeps the grades
# ---------------------------------------------------------------------------


@pytest.fixture()
def two_course_app(one_course_app):
    add_course(one_course_app.test_client(), package_bytes("beta"))
    return one_course_app


def test_archiving_keeps_the_submission_rows(two_course_app) -> None:
    """Grades are the one thing here that cannot be reconstructed."""
    storage = two_course_app.registry.storage
    for _ in range(3):
        storage.insert_submission(
            timestamp="2026-09-01T12:00:00+00:00",
            course_id="beta",
            unit_name="Beta Unit",
            qtag="b1",
            student_soln="an answer",
            points=1.0,
            max_points=1.0,
        )

    client = two_course_app.test_client()
    response = client.delete("/api/admin/courses/beta")

    assert response.status_code == 200
    assert storage.count_submissions_for_course("beta") == 3


def test_an_archived_course_stops_being_served(two_course_app) -> None:
    client = two_course_app.test_client()
    client.delete("/api/admin/courses/beta")

    assert client.get("/c/beta/units").status_code == 404
    assert client.get("/c/beta/").status_code == 404


def test_an_archived_course_leaves_the_picker(two_course_app) -> None:
    client = two_course_app.test_client()
    client.delete("/api/admin/courses/beta")

    listed = [c["id"] for c in client.get("/api/courses").get_json()["courses"]]
    assert listed == ["alpha"]


def test_an_archived_course_is_still_in_the_admin_list(two_course_app) -> None:
    """The point of archiving rather than deleting is that it is still there."""
    client = two_course_app.test_client()
    client.delete("/api/admin/courses/beta")

    courses = {c["id"]: c for c in client.get("/api/admin/courses").get_json()["courses"]}
    assert set(courses) == {"alpha", "beta"}
    assert courses["beta"]["deleted_at"]
    assert courses["alpha"]["deleted_at"] is None


def test_archiving_the_default_course_moves_the_default(two_course_app) -> None:
    client = two_course_app.test_client()

    response = client.delete("/api/admin/courses/alpha")

    assert response.status_code == 200
    assert response.get_json()["default"] == "beta"
    assert client.get("/").headers["Location"].endswith("/c/beta/")


def test_the_last_course_cannot_be_archived(one_course_app) -> None:
    """Archiving it would leave "/" with nowhere to go for every student."""
    client = one_course_app.test_client()

    response = client.delete("/api/admin/courses/alpha")

    assert response.status_code == 409
    assert "only course" in response.get_json()["error"]
    assert client.get("/c/alpha/units").status_code == 200


def test_archiving_twice_is_refused(two_course_app) -> None:
    client = two_course_app.test_client()
    client.delete("/api/admin/courses/beta")

    response = client.delete("/api/admin/courses/beta")
    assert response.status_code == 409


def test_archiving_survives_a_restart(two_course_app, make_app) -> None:
    two_course_app.test_client().delete("/api/admin/courses/beta")

    rebooted = make_app()
    assert rebooted.registry.get("beta") is None
    assert rebooted.registry.get("beta", include_deleted=True).deleted


def test_there_is_no_hard_delete(two_course_app) -> None:
    """Hard deletion is a separate, explicitly-worded action that does not exist.

    Nothing should let an admin reach it by adding a query parameter to the
    archive call.
    """
    client = two_course_app.test_client()
    client.delete("/api/admin/courses/beta?hard=true&purge=1")

    assert two_course_app.registry.storage.count_submissions_for_course("beta") == 0
    package = Path(two_course_app.registry.course_dir("beta")) / "soln_pkg"
    assert package.exists(), "archiving must not remove the package from disk"


# ---------------------------------------------------------------------------
# Adopting an authored id over a placeholder
# ---------------------------------------------------------------------------


@pytest.fixture()
def empty_portal_app(storage_root: Path, make_app):
    """A portal that booted with nothing uploaded: one placeholder course."""
    app = make_app()
    entry = app.registry.get("default")
    assert entry is not None and entry.id_source == ID_SOURCE_FALLBACK
    return app


def test_the_first_upload_adopts_the_packages_own_id(empty_portal_app) -> None:
    """Otherwise "default" becomes permanent for the first real course.

    The id is never re-derived, so a placeholder that survives the first upload
    would be in the URL, in submissions.course_id and in every student's
    localStorage key for the life of the portal.
    """
    client = empty_portal_app.test_client()

    response = upload(client, package_bytes("alpha"), course_id="default")

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["course_id"] == "alpha"
    assert empty_portal_app.registry.get("default") is None
    assert empty_portal_app.registry.default_course_id == "alpha"
    assert client.get("/c/alpha/units").status_code == 200


def test_the_adopted_course_owns_the_storage_directory(empty_portal_app) -> None:
    client = empty_portal_app.test_client()
    upload(client, package_bytes("alpha"), course_id="default")

    registry = empty_portal_app.registry
    assert Path(registry.soln_pkg_path("alpha"), "llmgrader_config.xml").exists()
    assert not Path(registry.course_dir("default")).exists()


def test_adoption_survives_a_restart(empty_portal_app, make_app) -> None:
    upload(empty_portal_app.test_client(), package_bytes("alpha"), course_id="default")

    rebooted = make_app()
    assert rebooted.registry.default_course_id == "alpha"
    assert rebooted.registry.get("default", include_deleted=True) is None


def test_adoption_is_refused_when_the_placeholder_has_graded_work(empty_portal_app) -> None:
    """Safe by construction, and checked rather than assumed.

    A placeholder has no package, so it cannot have graded anything -- which is
    exactly what makes re-keying it safe. If a row ever did exist under the old
    id, re-keying would orphan that grade silently, so the id stays put.

    The upload is then refused by the ordinary mismatch guard, since the
    package names a course the target is not. That is the right end state: the
    alternative is a course whose id says "default" and whose package says
    "alpha", which is the two-identities ambiguity the whole scheme exists to
    remove. The message points at Add Course, which does work here.
    """
    empty_portal_app.registry.storage.insert_submission(
        timestamp="2026-09-01T12:00:00+00:00",
        course_id="default",
        unit_name="somehow",
        qtag="q1",
        student_soln="an answer",
    )

    client = empty_portal_app.test_client()
    response = upload(client, package_bytes("alpha"), course_id="default")

    assert response.status_code == 409
    assert "add it as a new course" in response.get_json()["error"].lower()
    assert empty_portal_app.registry.get("default") is not None
    assert empty_portal_app.registry.get("alpha") is None
    assert empty_portal_app.registry.storage.count_submissions_for_course("default") == 1


def test_a_real_course_never_adopts_a_new_id(one_course_app) -> None:
    """Only a fallback placeholder is re-keyed; a registered course is refused."""
    client = one_course_app.test_client()

    response = upload(client, package_bytes("beta"), course_id="alpha")

    assert response.status_code == 409
    assert one_course_app.registry.get("alpha") is not None
    assert one_course_app.registry.get("beta") is None


# ---------------------------------------------------------------------------
# The registry object on its own
# ---------------------------------------------------------------------------


def test_courses_hides_archived_entries_by_default(storage_root: Path, make_app) -> None:
    app = make_app()
    client = app.test_client()
    add_course(client, package_bytes("alpha"))
    add_course(client, package_bytes("beta"))
    client.delete("/api/admin/courses/beta")

    registry = app.registry
    assert "beta" not in [entry.id for entry in registry.courses()]
    assert "beta" in [entry.id for entry in registry.courses(include_deleted=True)]


def test_single_package_mode_refuses_to_add_courses(tmp_path: Path, storage_root: Path) -> None:
    """`run.py --soln_pkg` writes no registry file, so there is nowhere to add to."""
    package = tmp_path / "pkg"
    write_package(package, "alpha")
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    app = create_app(scratch_dir=str(scratch), soln_pkg=str(package))
    app.config["TESTING"] = True

    response = add_course(app.test_client(), package_bytes("beta"))
    assert response.status_code == 409
    assert "--soln_pkg" in response.get_json()["error"]
