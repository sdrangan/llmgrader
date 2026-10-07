"""The version of a course package: written by create_soln_pkg, read by Grader.

``plans/mcp_usage.md``, decision 4.  Every course package carries a version so
a grade, or a course MCP call, can be traced to the exact rubric, solution and
slides that produced it.

``create_soln_pkg`` writes ``package_info.json`` into the package::

    {
      "version": "2026-10-07.3f9c2a1",
      "built_at": "2026-10-07T21:40:12Z",
      "content_sha256": "3f9c2a1e...",
      "sources": {"hwdesign-soln": "54cc4a3 (clean)"}
    }

The version is the build date and the head of a hash over the package's files.
It is never typed by hand: a hand-set version is forgotten, and two packages
under one version are worse than none.  A package without the file -- built
before it existed, or by hand -- is given a version computed from its contents
when it is loaded, so every grade has one.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PACKAGE_INFO_FILE = "package_info.json"

# Prefix of a version computed at load time rather than written at build time.
# There is no build date to put in its place, and the prefix says so.
COMPUTED_PREFIX = "computed"

_HASH_HEAD = 7


def content_sha256(pkg_dir: str | Path) -> str:
    """A hash over every file in *pkg_dir*, sorted by path.

    Each file contributes its path relative to the package and the hash of its
    bytes, so a renamed file changes the result as surely as an edited one.
    ``package_info.json`` itself is left out: it holds the result.
    """
    pkg_dir = Path(pkg_dir)
    files = sorted(
        (path.relative_to(pkg_dir).as_posix(), path)
        for path in pkg_dir.rglob("*")
        if path.is_file()
    )
    digest = hashlib.sha256()
    for rel, path in files:
        if rel == PACKAGE_INFO_FILE:
            continue
        file_digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                file_digest.update(chunk)
        digest.update(rel.encode("utf-8") + b"\0" + file_digest.digest())
    return digest.hexdigest()


def git_sources(inputs) -> dict[str, str]:
    """``{repo name: "<commit> (<state>)"}`` for the repositories *inputs* live in.

    *inputs* are the files and directories the package was built from.  The
    state is ``clean`` or counts what the commit alone would not reproduce,
    looking **only at those inputs** -- a stray file elsewhere in the
    repository does not touch the package and is not counted:

    * uncommitted changes to tracked inputs;
    * inputs not in git at all, untracked or ignored.

    An input outside any git repository, or with git not installed,
    contributes nothing.
    """
    def git(cwd, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
        ).stdout

    # Grouped by directory so each group is one git call with names relative
    # to it -- comparing absolute paths against git's toplevel goes wrong on
    # Windows over drive-letter case.
    by_dir: dict[Path, list[str]] = {}
    for path in inputs:
        path = Path(path).resolve()
        if path.exists():
            by_dir.setdefault(path.parent, []).append(path.name)

    repos: dict[str, dict] = {}
    for directory, names in by_dir.items():
        try:
            toplevel, commit = git(
                directory, "rev-parse", "--show-toplevel", "--short", "HEAD").split()
            # Porcelain paths are relative to the repository root whatever the
            # cwd, so a set of lines dedupes inputs reached from two directories.
            status = git(directory, "status", "--porcelain", "--untracked-files=all",
                         "--ignored", "--", *names).splitlines()
        except (OSError, ValueError, subprocess.CalledProcessError):
            continue
        repo = repos.setdefault(Path(toplevel).name, {"commit": commit, "lines": set()})
        repo["lines"].update(status)

    sources = {}
    for name, repo in repos.items():
        lines = repo["lines"]
        outside = sum(1 for line in lines if line.startswith(("??", "!!")))
        changed = len(lines) - outside
        notes = []
        if changed:
            notes.append(f"{changed} uncommitted change{'s' if changed != 1 else ''}")
        if outside:
            notes.append(f"{outside} file{'s' if outside != 1 else ''} not in git")
        sources[name] = f"{repo['commit']} ({', '.join(notes) or 'clean'})"
    return sources


def build_package_info(pkg_dir: str | Path, inputs=(), *, now: datetime | None = None) -> dict:
    """The ``package_info.json`` contents for the package built in *pkg_dir*.

    *inputs* are the files and directories it was built from; see
    :func:`git_sources`.
    """
    now = now or datetime.now(timezone.utc)
    sha = content_sha256(pkg_dir)
    return {
        "version": f"{now:%Y-%m-%d}.{sha[:_HASH_HEAD]}",
        "built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "content_sha256": sha,
        "sources": git_sources(inputs),
    }


def write_package_info(pkg_dir: str | Path, inputs=(), *, now: datetime | None = None) -> dict:
    """Write ``package_info.json`` into *pkg_dir* and return what was written."""
    info = build_package_info(pkg_dir, inputs, now=now)
    (Path(pkg_dir) / PACKAGE_INFO_FILE).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info


def package_version(pkg_dir: str | Path | None) -> str | None:
    """The version of the package in *pkg_dir*.

    Read from ``package_info.json`` when the package has one, else computed
    from its contents as ``computed.<hash head>``.  None when there is no
    package there at all -- a course that has never had one uploaded.
    """
    if not pkg_dir:
        return None
    pkg_dir = Path(pkg_dir)
    if not (pkg_dir / "llmgrader_config.xml").is_file():
        return None
    try:
        info = json.loads((pkg_dir / PACKAGE_INFO_FILE).read_text(encoding="utf-8"))
        version = info.get("version") if isinstance(info, dict) else None
        if isinstance(version, str) and version.strip():
            return version.strip()
    except (OSError, ValueError):
        pass
    return f"{COMPUTED_PREFIX}.{content_sha256(pkg_dir)[:_HASH_HEAD]}"
