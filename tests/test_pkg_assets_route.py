"""Tests for the /pkg_assets/<path> Flask route that serves solution-package images."""

import os
from pathlib import Path

import pytest

from llmgrader.app import create_app


@pytest.fixture()
def pkg_dir(tmp_path: Path) -> Path:
    """Create a minimal solution package with an image."""
    pkg = tmp_path / "soln_pkg"
    pkg.mkdir()

    images = pkg / "unit1_good_images"
    images.mkdir()
    (images / "circuit.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    # Minimal config so UnitParser doesn't raise on missing config
    (pkg / "llmgrader_config.xml").write_text(
        "<llmgrader><units></units></llmgrader>", encoding="utf-8"
    )

    return pkg


@pytest.fixture()
def client(tmp_path: Path, pkg_dir: Path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    # Redirect Grader storage so the DB is isolated to this test's tmp_path
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    app = create_app(scratch_dir=str(scratch), soln_pkg=str(pkg_dir))
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_pkg_assets_returns_image(client, pkg_dir: Path) -> None:
    resp = client.get("/pkg_assets/unit1_good_images/circuit.png")
    assert resp.status_code == 200
    assert resp.data.startswith(b"\x89PNG")


def test_pkg_assets_returns_404_for_missing_file(client) -> None:
    resp = client.get("/pkg_assets/unit1_good_images/nonexistent.png")
    assert resp.status_code == 404


def test_pkg_assets_blocks_directory_traversal(client) -> None:
    # Flask's send_from_directory raises 404 (or 400) for path traversal
    resp = client.get("/pkg_assets/../../../etc/passwd")
    assert resp.status_code in (400, 404)
