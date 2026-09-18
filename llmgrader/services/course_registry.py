"""The registry of courses served by one portal, and where each one lives.

Phase 1 split the portal-wide half out of ``Grader`` so that several of them
could exist (``services/portal_storage.py``).  This is the other half of that
seam: something that knows *which* courses exist, what each one is called, and
which directory under ``<storage>/courses/`` belongs to it.  One
:class:`~llmgrader.services.portal_storage.PortalStorage` is shared by every
course, so the database is opened and migrated once per process rather than
once per course.

Exactly one course is registered today.  The registry is what makes a second
one possible later (``plans/multicourse.md``, phase 5) without another
storage-layout migration.

Layout::

    <storage>/
      db/ pref/ soln_images/      # global, PortalStorage's
      courses/
        courses.json              # the registry file
        <course_id>/
          soln_pkg/               # the extracted package that is served
          uploads/                # the archives as uploaded, newest three
          scratch/pid-<pid>/      # per course *and* per process

**The id is resolved once and then read, never re-derived.**  A course's id
comes from the package's ``<course_id>`` when it is authored (decision 3) and
otherwise from a slug of ``<name>`` + ``<semester>``.  Either way it is written
to ``courses.json`` at registration, and every later boot reads it from there.
That is what stops an instructor's typo fix in ``<name>`` from silently
orphaning a course's submissions, storage directory and saved student state;
``id_source`` records which of the two rules produced it.

**Scratch is per course and per process.**  ``claim_scratch_dir`` (phase 1) is
a process-global set, which is the right scope for several ``Grader``s in one
process and no protection at all across gunicorn workers -- both would rmtree
the same tree on boot.  Putting the pid in the path makes the two workers
disjoint by construction; the claim stays as the in-process guard.  Scratch
directories left behind by processes that are no longer running are pruned when
a course's grader is built.
"""

import json
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

from llmgrader.services.grader import Grader
from llmgrader.services.portal_storage import PortalStorage

# The registry file, relative to <storage>/courses/.
REGISTRY_FILENAME = "courses.json"

# Mirrors the <course_id> pattern in llmgrader_config.xsd.  Anything this
# rejects must never reach the filesystem: the id is a directory name, and
# later a URL path segment.
COURSE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
COURSE_ID_MAX_LEN = 64

# Used when there is no package to read an identity from -- a portal booting
# for the very first time, with nothing uploaded yet.  It is a real registered
# course so that an upload has somewhere to land, exactly as <storage>/soln_pkg
# did before this change.
FALLBACK_COURSE_ID = "default"

# One-time escape hatch for an existing portal being upgraded.  Its package
# predates <course_id>, so without this the id is slugged from <name> and
# <semester> -- and that slug is then permanent, in the URL, in
# submissions.course_id and in every student's localStorage key.  Setting this
# once at the upgrade deploy names the course properly instead.  It is read
# only when a course is first registered; afterwards courses.json wins and the
# variable can be removed.
MIGRATE_COURSE_ID_ENV = "LLMGRADER_MIGRATE_COURSE_ID"

# How the id in courses.json was arrived at.
ID_SOURCE_AUTHORED = "authored"   # <course_id> in the package
ID_SOURCE_ENV = "env"             # LLMGRADER_MIGRATE_COURSE_ID at first boot
ID_SOURCE_DERIVED = "derived"     # slug of <name> + <semester>
ID_SOURCE_FALLBACK = "fallback"   # no readable package at registration
ID_SOURCE_RECOVERED = "recovered"  # read back off <storage>/courses/ after a lost registry


def slugify_course_id(*parts: str) -> str:
    """Build a course id out of display text, or "" if there is none.

    Lowercased, runs of anything outside ``[a-z0-9_-]`` collapsed to a single
    dash, trimmed to a leading alphanumeric and capped at 64 characters so the
    result satisfies COURSE_ID_PATTERN.
    """
    joined = " ".join(part for part in parts if part)
    slug = re.sub(r"[^a-z0-9_-]+", "-", joined.lower())
    slug = slug.strip("-_")
    # A leading non-alphanumeric is possible only if the text began with an
    # underscore run, which strip above already removed; keep the guard anyway.
    slug = re.sub(r"^[^a-z0-9]+", "", slug)
    slug = slug[:COURSE_ID_MAX_LEN].rstrip("-_")
    return slug if COURSE_ID_PATTERN.match(slug) else ""


def read_course_block(soln_pkg_path: str) -> dict:
    """Read ``<course>`` out of a package directory's llmgrader_config.xml.

    Deliberately tolerant and schema-free: this runs before any ``Grader``
    exists, on packages that may be half-uploaded or predate the current
    schema, and a course that cannot be identified falls back rather than
    failing the boot.  Returns ``{}`` when there is nothing readable.
    """
    config_path = os.path.join(soln_pkg_path, "llmgrader_config.xml")
    if not os.path.exists(config_path):
        return {}

    try:
        config_root = ET.parse(config_path).getroot()
    except Exception as exc:  # noqa: BLE001 -- any parse failure means "unknown"
        print(f"[CourseRegistry] Could not parse {config_path}: {exc}")
        return {}

    course_elem = config_root.find("course")
    if course_elem is None:
        return {}

    def text(tag: str) -> str:
        return (course_elem.findtext(tag) or "").strip()

    return {
        "course_id": text("course_id"),
        "name": text("name"),
        "semester": text("semester") or text("term"),
    }


def course_id_from_env() -> str | None:
    """A valid ``LLMGRADER_MIGRATE_COURSE_ID``, or None.

    An invalid value is ignored with a warning rather than raising: this is
    read on the boot path of a live portal, and a typo in an env var must not
    be the reason a course fails to come back up.
    """
    value = (os.environ.get(MIGRATE_COURSE_ID_ENV) or "").strip()
    if not value:
        return None
    if not COURSE_ID_PATTERN.match(value):
        print(
            f"[CourseRegistry] Ignoring {MIGRATE_COURSE_ID_ENV}={value!r}: "
            f"must match {COURSE_ID_PATTERN.pattern}"
        )
        return None
    return value


def resolve_course_id(course_block: dict) -> tuple[str, str]:
    """Return ``(course_id, id_source)`` for a package's ``<course>`` block.

    Authored ``<course_id>`` first, then ``LLMGRADER_MIGRATE_COURSE_ID``, then
    a slug of ``<name>`` + ``<semester>``, then the fallback id.  Callers use
    this exactly once per course -- at registration -- and read
    ``courses.json`` afterwards.

    The env var sits *below* an authored id on purpose.  A package that names
    itself is the authority (decision 3); the env var exists for the packages
    that predate ``<course_id>`` and so have no way to say what they are.
    """
    authored = (course_block or {}).get("course_id", "").strip()
    if authored and COURSE_ID_PATTERN.match(authored):
        return authored, ID_SOURCE_AUTHORED

    from_env = course_id_from_env()
    if from_env:
        return from_env, ID_SOURCE_ENV

    derived = slugify_course_id(
        (course_block or {}).get("name", ""),
        (course_block or {}).get("semester", ""),
    )
    if derived:
        return derived, ID_SOURCE_DERIVED

    return FALLBACK_COURSE_ID, ID_SOURCE_FALLBACK


# Win32 constants for the liveness probe below.
_WIN_ERROR_ACCESS_DENIED = 5
_WIN_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _pid_is_running_windows(pid: int) -> bool:
    """Whether *pid* exists, via OpenProcess.

    ``os.kill(pid, 0)`` is not a liveness probe on Windows.  For a pid that no
    longer exists it raises ``OSError(WinError 87)`` rather than
    ``ProcessLookupError``, so the POSIX branch below reads every dead process
    as alive and nothing is ever pruned.  Worse, ``os.kill`` on Windows is
    implemented with ``TerminateProcess``, so it is the wrong tool to reach for
    here even when it appears to work.
    """
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(
        _WIN_PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if handle:
        kernel32.CloseHandle(handle)
        return True

    # Access denied means the process exists and belongs to someone else --
    # alive, and not ours to clean up after.  Anything else (87, "invalid
    # parameter") means there is no such process.
    return ctypes.get_last_error() == _WIN_ERROR_ACCESS_DENIED


def _pid_is_running(pid: int) -> bool:
    """Whether *pid* still exists, for pruning abandoned scratch trees.

    Errs towards "alive" when it cannot tell: leaving a stale scratch tree
    behind costs disk, deleting a live one corrupts a running worker.
    """
    if pid <= 0:
        return False

    if sys.platform == "win32":
        return _pid_is_running_windows(pid)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Someone else's process: alive, and not ours to clean up after.
        return True
    except OSError:
        return True
    return True


@dataclass
class CourseEntry:
    """One row of ``courses.json``."""

    id: str
    name: str
    semester: str
    created_at: str
    id_source: str

    @classmethod
    def from_dict(cls, data: dict) -> "CourseEntry":
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            semester=str(data.get("semester", "")),
            created_at=str(data.get("created_at", "")),
            id_source=str(data.get("id_source", "")),
        )

    def to_dict(self) -> dict:
        return asdict(self)


class CourseRegistry:
    """The courses this portal serves, and one ``Grader`` for each.

    Two modes, because ``run.py --soln_pkg`` must keep meaning what it means
    today:

    * **registry mode** (the deployed portal).  ``courses.json`` under
      ``<storage>/courses/`` is the record; the legacy single-course layout is
      migrated into it on first boot.
    * **single-package mode** (``--soln_pkg``, and every test that passes a
      package path).  The given directory is registered as the sole course,
      in memory, with the caller's scratch directory used verbatim.  Nothing
      is written to ``<storage>/courses/``.
    """

    def __init__(
        self,
        *,
        storage: PortalStorage | None = None,
        soln_pkg: str | None = None,
        scratch_dir: str | None = None,
    ):
        """
        Parameters
        ----------
        storage: PortalStorage | None
            The portal-wide storage service every course shares.  Omitted, one
            is built here -- which opens and migrates the database once.
        soln_pkg: str | None
            A package directory to serve as the sole course (single-package
            mode).  Omitted, the registry file governs.
        scratch_dir: str | None
            Scratch directory for single-package mode.  Ignored in registry
            mode, where scratch lives under the course.
        """
        self.storage = PortalStorage() if storage is None else storage
        self.soln_pkg = soln_pkg
        self.scratch_dir = scratch_dir

        self._entries: dict[str, CourseEntry] = {}
        self._default_id: str | None = None
        self._graders: dict[str, Grader] = {}

        self._load()

        # Submission rows written before submissions.course_id existed belong
        # to whichever single course this portal was serving, which is the one
        # _load has just settled on.  PortalStorage cannot work that out for
        # itself -- it knows nothing about courses, deliberately -- so the id
        # is handed down from here.  The call is a no-op on every boot after
        # the first; see PortalStorage.backfill_course_id.
        if self._default_id:
            self.storage.backfill_course_id(self._default_id)

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    @property
    def uses_registry_file(self) -> bool:
        """False in single-package mode, where nothing is persisted."""
        return self.soln_pkg is None

    def courses_root(self) -> str:
        """``<storage>/courses``, created if missing."""
        root = os.path.join(self.storage.get_storage_path(), "courses")
        os.makedirs(root, exist_ok=True)
        return root

    def registry_path(self) -> str:
        return os.path.join(self.courses_root(), REGISTRY_FILENAME)

    def legacy_soln_pkg_path(self) -> str:
        """``<storage>/soln_pkg`` -- the pre-registry location, if it survives."""
        return os.path.join(self.storage.get_storage_path(), "soln_pkg")

    def course_dir(self, course_id: str) -> str:
        return os.path.join(self.courses_root(), course_id)

    def soln_pkg_path(self, course_id: str) -> str:
        """The extracted package served for *course_id*."""
        if not self.uses_registry_file:
            return self.soln_pkg
        return os.path.join(self.course_dir(course_id), "soln_pkg")

    def uploads_path(self, course_id: str) -> str | None:
        """Where the archives land as uploaded; grader.prune_uploads keeps the newest."""
        if not self.uses_registry_file:
            return None
        path = os.path.join(self.course_dir(course_id), "uploads")
        os.makedirs(path, exist_ok=True)
        return path

    def scratch_root(self, course_id: str) -> str:
        return os.path.join(self.course_dir(course_id), "scratch")

    def scratch_path(self, course_id: str) -> str:
        """This process's scratch directory for *course_id*.

        Per course so one course's Grader cannot rmtree another's, and per
        process so two gunicorn workers cannot rmtree each other's.
        """
        if not self.uses_registry_file:
            # The caller's path, verbatim -- "scratch" is Grader's own default,
            # kept here so single-package mode never has to pass one.
            return self.scratch_dir or "scratch"
        return os.path.join(self.scratch_root(course_id), f"pid-{os.getpid()}")

    # ------------------------------------------------------------------
    # The registry file
    # ------------------------------------------------------------------

    def courses(self) -> list[CourseEntry]:
        """Registered courses, in registration order."""
        return list(self._entries.values())

    def get(self, course_id: str) -> CourseEntry | None:
        return self._entries.get(course_id)

    @property
    def default_course_id(self) -> str | None:
        return self._default_id

    def _read_registry_file(self) -> bool:
        """Populate entries from ``courses.json``; False if there is none."""
        path = self.registry_path()
        if not os.path.exists(path):
            return False

        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            entries = [CourseEntry.from_dict(row) for row in data.get("courses", [])]
            entries = [entry for entry in entries if entry.id]
        except Exception as exc:  # noqa: BLE001 -- a corrupt file must not brick the portal
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            damaged = f"{path}.bad-{stamp}"
            print(f"[CourseRegistry] {path} is unreadable ({exc}); moving it to {damaged}")
            shutil.move(path, damaged)
            return False

        if not entries:
            return False

        self._entries = {entry.id: entry for entry in entries}
        default_id = data.get("default")
        self._default_id = default_id if default_id in self._entries else entries[0].id
        return True

    def _write_registry_file(self) -> None:
        """Write ``courses.json`` atomically (a torn registry is unrecoverable)."""
        if not self.uses_registry_file:
            return

        path = self.registry_path()
        payload = {
            "courses": [entry.to_dict() for entry in self._entries.values()],
            "default": self._default_id,
        }
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_path, path)

    def register(
        self,
        *,
        course_id: str,
        name: str,
        semester: str,
        id_source: str,
        make_default: bool = False,
    ) -> CourseEntry:
        """Record a course and persist the registry.

        The id is the caller's to resolve (see :func:`resolve_course_id`); this
        method is where it stops being derivable and starts being *recorded*.
        """
        entry = CourseEntry(
            id=course_id,
            name=name,
            semester=semester,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            id_source=id_source,
        )
        self._entries[course_id] = entry
        if make_default or self._default_id is None:
            self._default_id = course_id
        self._write_registry_file()
        return entry

    def register_package(self, soln_pkg_path: str, *, make_default: bool = False) -> CourseEntry:
        """Register the course described by an extracted package directory."""
        block = read_course_block(soln_pkg_path)
        course_id, id_source = resolve_course_id(block)
        return self.register(
            course_id=course_id,
            name=block.get("name", ""),
            semester=block.get("semester", ""),
            id_source=id_source,
            make_default=make_default,
        )

    # ------------------------------------------------------------------
    # Boot
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self.uses_registry_file:
            # Single-package mode: an in-memory entry so the rest of the code
            # can talk about "the course" uniformly, and no registry file.
            block = read_course_block(self.soln_pkg)
            course_id, id_source = resolve_course_id(block)
            entry = CourseEntry(
                id=course_id,
                name=block.get("name", ""),
                semester=block.get("semester", ""),
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                id_source=id_source,
            )
            self._entries = {course_id: entry}
            self._default_id = course_id
            return

        self.migrate_legacy_layout()

        if self._read_registry_file():
            return

        if self._recover_from_course_dirs():
            return

        # Nothing to migrate, nothing to recover: a portal booting empty.  It
        # still gets one course, so that an upload has somewhere to land --
        # exactly what <storage>/soln_pkg was before this change.  A fresh
        # portal can name that course up front with the same env var an
        # upgrading one uses, rather than living with "default" forever.
        from_env = course_id_from_env()
        self.register(
            course_id=from_env or FALLBACK_COURSE_ID,
            name="",
            semester="",
            id_source=ID_SOURCE_ENV if from_env else ID_SOURCE_FALLBACK,
            make_default=True,
        )

    def _recover_from_course_dirs(self) -> bool:
        """Rebuild entries from the course directories that exist on disk.

        Only reached when ``courses.json`` is missing or was set aside as
        corrupt.  **The directory name is the id** -- it is where the package
        is actually served from, and re-deriving an id from the package's
        ``<course>`` block here would move the course out from under its own
        files, which is the hazard the registry exists to prevent.  Names and
        semesters are read back from the packages for display.
        """
        recovered = False
        for name in sorted(os.listdir(self.courses_root())):
            package = os.path.join(self.course_dir(name), "soln_pkg")
            if not os.path.isdir(package) or not COURSE_ID_PATTERN.match(name):
                continue
            block = read_course_block(package)
            print(f"[CourseRegistry] Recovered course '{name}' from {package}")
            self.register(
                course_id=name,
                name=block.get("name", ""),
                semester=block.get("semester", ""),
                id_source=ID_SOURCE_RECOVERED,
            )
            recovered = True
        return recovered

    def migrate_legacy_layout(self) -> CourseEntry | None:
        """Move a pre-registry ``<storage>/soln_pkg`` under ``courses/<id>/``.

        The deployed portal has exactly this tree and must come back up with
        its course intact and no admin action.  Its package predates
        ``<course_id>`` by definition, so the id comes from
        ``LLMGRADER_MIGRATE_COURSE_ID`` when it is set and otherwise from a
        slug of ``<name>`` + ``<semester>`` -- and is then recorded, after
        which it is never derived again.  This is the only moment at which
        that env var has any effect, which is why an upgrade is the time to
        set it.

        Returns the migrated entry, or None when there was nothing to migrate.
        """
        legacy_pkg = self.legacy_soln_pkg_path()
        if not os.path.isdir(legacy_pkg):
            return None
        if os.path.exists(self.registry_path()):
            # Already migrated; a leftover directory is not ours to move on top
            # of a live registry.
            return None

        block = read_course_block(legacy_pkg)
        course_id, id_source = resolve_course_id(block)

        target_dir = self.course_dir(course_id)
        target_pkg = os.path.join(target_dir, "soln_pkg")
        if os.path.exists(target_pkg):
            print(
                f"[CourseRegistry] {target_pkg} already exists; leaving {legacy_pkg} "
                "in place rather than merging two packages."
            )
            return None

        os.makedirs(target_dir, exist_ok=True)
        try:
            shutil.move(legacy_pkg, target_pkg)
        except OSError as exc:
            # Two workers booting at once: whichever loses the race finds the
            # package already moved and the registry already written, and
            # reads it like any other boot.
            print(f"[CourseRegistry] Could not move {legacy_pkg} to {target_pkg}: {exc}")
            return None
        print(f"[CourseRegistry] Migrated {legacy_pkg} to {target_pkg}")

        entry = self.register(
            course_id=course_id,
            name=block.get("name", ""),
            semester=block.get("semester", ""),
            id_source=id_source,
            make_default=True,
        )
        return entry

    # ------------------------------------------------------------------
    # Graders
    # ------------------------------------------------------------------

    def prune_stale_scratch(self, course_id: str) -> list[str]:
        """Delete this course's scratch trees whose owning process is gone.

        Without this, every restart of a worker leaves a ``pid-<n>`` directory
        behind for good: the per-process path that makes two workers safe also
        means nothing else will ever claim and clear that tree.
        """
        root = self.scratch_root(course_id)
        removed: list[str] = []
        if not os.path.isdir(root):
            return removed

        for name in os.listdir(root):
            if not name.startswith("pid-"):
                continue
            try:
                pid = int(name[len("pid-"):])
            except ValueError:
                continue
            if pid == os.getpid() or _pid_is_running(pid):
                continue
            path = os.path.join(root, name)
            try:
                shutil.rmtree(path)
                removed.append(path)
            except OSError as exc:
                print(f"[CourseRegistry] Could not remove stale scratch {path}: {exc}")
        return removed

    def grader_for(self, course_id: str) -> Grader:
        """The ``Grader`` serving *course_id*, built once and cached.

        Every grader shares this registry's PortalStorage, which is the whole
        point of the phase 1 split: one database, opened and migrated once.
        """
        grader = self._graders.get(course_id)
        if grader is not None:
            return grader

        if self.uses_registry_file:
            self.prune_stale_scratch(course_id)

        grader = Grader(
            scratch_dir=self.scratch_path(course_id),
            soln_pkg=self.soln_pkg_path(course_id),
            storage=self.storage,
            course_id=course_id,
            uploads_dir=self.uploads_path(course_id),
        )
        self._graders[course_id] = grader
        return grader

    def default_grader(self) -> Grader:
        """The one course's grader, until there is a picker to choose another."""
        if self._default_id is None:
            raise RuntimeError("CourseRegistry has no default course")
        return self.grader_for(self._default_id)
