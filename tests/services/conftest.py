"""Shared helpers for the service-level tests.

Course content is served under ``/c/<course_id>/`` (``plans/multicourse.md``,
decision 5).  These tests build an app from a single package, so the course id
is whatever that package authored -- or, with no ``<course_id>``, a slug of its
name and semester.  Read it off the registry rather than spelling it out per
fixture: a fixture that renames its course should not also have to renumber its
URLs.
"""

import pytest


def course_path(client, path: str) -> str:
    """``/c/<course_id>`` + *path*, for the course the app under *client* serves."""
    return f"/c/{client.application.registry.default_course_id}{path}"


@pytest.fixture()
def cpath():
    """The helper above, for tests that build their clients inline."""
    return course_path


@pytest.fixture()
def prefix(client) -> str:
    """``/c/<course_id>`` for the module-local ``client`` fixture."""
    return f"/c/{client.application.registry.default_course_id}"
