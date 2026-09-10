"""Shared helpers for the doc test suite.

The VCS wrappers and page writers every suite needs -- previously
copied per file (with drifting parameter names: ``repo`` vs ``cwd``).
Test data (repo histories, fixtures) stays in the test modules: it is
the spec, not boilerplate.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def put(root: Path, rel: str, text: str = "# page\n") -> None:
    """Create ``root/<rel>`` (parents as needed) with the given text."""
    page = root / rel
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(text)


def hg(repo: Path, *args: str) -> str:
    """Run hg in ``repo``; assert success; return stdout."""
    proc = subprocess.run(
        ["hg", *args], cwd=repo, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, f"hg {args} failed: {proc.stderr}"
    return proc.stdout


def git_env() -> dict[str, str]:
    """Environment with a deterministic git identity."""
    env = dict(os.environ)
    env.update(
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@example.invalid",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@example.invalid",
    )
    return env


def git(repo: Path, *args: str) -> str:
    """Run ``git -C repo``; assert success; return stdout."""
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    assert proc.returncode == 0, f"git {args} failed: {proc.stderr}"
    return proc.stdout


# The two canonical platform-versions.toml payloads: generic fc-* revs
# (checkout / active-bookmark / switcher-generator suites) and the
# production mirror-branch names (vcs-backend / release-notes suites).

# Tier-independent roots: ONE definition site instead of per-file
# parents[N] counting, where N silently means different directories
# per test tier (doc/tests/ vs doc/tests/e2e/). Naming follows the
# production tools (doc/tools/*.py DOC_ROOT).
DOC_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = DOC_ROOT.parent

TOML_FC = """\
[stable]
ver = "26.05"
rev = "fc-26.05-production"

[[prerelease]]
ver = "26.11"
rev = "fc-26.11-dev"

[[sunsetting]]
ver = "25.11"
rev = "fc-25.11-production"
"""

TOML_NEW_DOCS = """\
[stable]
ver = "26.05"
rev = "new-docs-fc-26.05-production"

[[prerelease]]
ver = "26.11"
rev = "new-docs-master"

[[sunsetting]]
ver = "25.11"
rev = "new-docs-fc-25.11-production"
"""


def versions_file(
    tmp_path: Path,
    toml: str = TOML_NEW_DOCS,
    name: str = "platform-versions.toml",
) -> Path:
    """Write ``toml`` as ``tmp_path/<name>`` and return the path.

    Defaults to the production mirror-branch payload: the suites that
    use this helper (vcs-backend, release-notes) test against that
    branch naming.
    """
    path = tmp_path / name
    path.write_text(toml)
    return path
