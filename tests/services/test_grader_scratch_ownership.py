"""Who owns -- and may therefore delete -- a Grader's scratch directory.

``Grader.__init__`` used to rmtree ``scratch_dir`` unconditionally.  That is
correct for one Grader per process and destructive the moment there are two:
constructing the second course's Grader wiped the first course's staged
package.  Ownership is now decided in one place (``claim_scratch_dir``), which
is what lets several Graders exist at all (``plans/multicourse.md``, phase 1).
"""

from pathlib import Path

import pytest

from llmgrader.services.grader import Grader
from llmgrader.services.portal_storage import PortalStorage


@pytest.fixture()
def isolated_storage(tmp_path: Path, monkeypatch):
    """Keep the database and scratch trees out of the instructor's local_data."""
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr(Grader, "load_unit_pkg", lambda self: None)


def test_first_grader_clears_its_scratch_dir(tmp_path: Path, isolated_storage) -> None:
    """The single-course behaviour is unchanged: a fresh Grader starts clean."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    stale = scratch / "left_over.zip"
    stale.write_text("from the last run")

    grader = Grader(scratch_dir=str(scratch))

    assert grader.owns_scratch is True
    assert not stale.exists()
    assert scratch.is_dir()


def test_second_grader_on_the_same_scratch_dir_does_not_wipe_it(
    tmp_path: Path, isolated_storage
) -> None:
    """The bug that blocked multiple Graders: instance two erasing instance one."""
    scratch = tmp_path / "scratch"

    first = Grader(scratch_dir=str(scratch))
    staged = scratch / "staged_package.zip"
    staged.write_text("course A")

    second = Grader(scratch_dir=str(scratch))

    assert first.owns_scratch is True
    assert second.owns_scratch is False
    assert staged.read_text() == "course A"


def test_owns_scratch_can_be_forced_off(tmp_path: Path, isolated_storage) -> None:
    """A caller that knows it is a guest can say so explicitly."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    keep = scratch / "keep_me.txt"
    keep.write_text("not mine to delete")

    grader = Grader(scratch_dir=str(scratch), owns_scratch=False)

    assert grader.owns_scratch is False
    assert keep.exists()


def test_graders_can_share_one_portal_storage(tmp_path: Path, isolated_storage) -> None:
    """The seam phase 2 needs: one database opened once, not once per course."""
    storage = PortalStorage()

    first = Grader(scratch_dir=str(tmp_path / "a"), storage=storage)
    second = Grader(scratch_dir=str(tmp_path / "b"), storage=storage)

    assert first.storage is storage
    assert second.storage is storage
    # The delegating shim still answers for callers that have not moved yet.
    assert first.db_path == storage.db_path == second.db_path
