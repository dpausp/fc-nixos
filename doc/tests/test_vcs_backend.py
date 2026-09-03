"""Unit and integration tests for ``tools/vcs_backend.py``.

The contract suite drives both TOOLS end-to-end with full dual-VCS
fixtures; these tests pin the seam itself: backend auto-detection at
the repo path, ref resolution per backend (with the exact remediation
hints), the ``git ls-tree`` subtree check, prefix-stripped export on
both backends, and the matched-entry selection order
(``--matched`` > ACTIVE bookmark | ``GITHUB_REF_NAME`` > loud failure).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from structlog.testing import capture_logs
from tools import checkout_versioned_docs as cot
from tools import vcs_backend as vcs
from tools.gen_platform_versions import load_versions

TOML = """\
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

MISSING_BRANCH = "no-such-mirror-branch"


def put(root: Path, rel: str, text: str = "# page\n") -> None:
    page = root / rel
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(text)


def hg(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["hg", *args], cwd=repo, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, f"hg {args} failed: {proc.stderr}"
    return proc.stdout


def git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@example.invalid",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@example.invalid",
    )
    return env


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    assert proc.returncode == 0, f"git {args} failed: {proc.stderr}"
    return proc.stdout


def versions_file(tmp_path: Path, name: str = "platform-versions.toml") -> Path:
    path = tmp_path / name
    path.write_text(TOML)
    return path


@pytest.fixture
def hg_repo(tmp_path: Path) -> Path:
    """hg repo with the three TOML bookmarks, integration ACTIVE.

    The ACTIVE integration bookmark makes later commits advance it --
    the normal local workflow the tools assume.
    """
    repo = tmp_path / "hg-repo"
    repo.mkdir()
    hg(repo, "init")
    (repo / ".hg" / "hgrc").write_text("[ui]\nusername = T <t@x>\n")
    put(repo / "doc" / "src", "index.md")
    hg(repo, "addremove")
    hg(repo, "commit", "-m", "integration")
    hg(repo, "bookmark", "-r", "0", "new-docs-master")
    hg(repo, "bookmark", "-r", "0", "new-docs-fc-26.05-production")
    hg(repo, "bookmark", "-r", "0", "new-docs-fc-25.11-production")
    hg(repo, "up", "new-docs-master")
    return repo


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """git clone (file:// remote) with every branch as origin/<branch>.

    The stable/sunsetting branches carry their namespaced
    ``doc/src/<ver>/`` trees (the sunset-move shape).
    """
    remote = tmp_path / "git-remote"
    remote.mkdir()
    git(remote, "init", "-q", "-b", "new-docs-master")
    put(remote / "doc" / "src", "index.md")
    git(remote, "add", "-A", "doc")
    git(remote, "commit", "-q", "-m", "integration")
    for branch, ver in (
        ("new-docs-fc-26.05-production", "26.05"),
        ("new-docs-fc-25.11-production", "25.11"),
    ):
        git(remote, "checkout", "-q", "-b", branch)
        put(remote / "doc" / "src" / ver, "index.md")
        git(remote, "add", "-A", "doc")
        git(remote, "commit", "-q", "-m", f"{branch}: namespaced tree")
    clone = tmp_path / "git-clone"
    git(tmp_path, "clone", "-q", f"file://{remote}", str(clone))
    return clone


def test_detect_selects_hg_by_dot_hg(hg_repo: Path) -> None:
    """A .hg/ dir makes the hg backend, by path only."""
    backend = vcs.detect_backend(hg_repo)
    assert isinstance(backend, vcs.HgBackend)
    assert backend.name == "hg"


def test_detect_selects_git_by_dot_git(git_repo: Path) -> None:
    """A .git/ dir makes the git backend, by path only."""
    backend = vcs.detect_backend(git_repo)
    assert isinstance(backend, vcs.GitBackend)
    assert backend.name == "git"


def test_detect_accepts_dot_git_worktree_file(tmp_path: Path) -> None:
    """A .git FILE (worktrees/submodules) also selects the git backend."""
    repo = tmp_path / "worktree-style"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: /somewhere/else\n")
    assert isinstance(vcs.detect_backend(repo), vcs.GitBackend)


def test_detect_without_vcs_fails_loudly(tmp_path: Path) -> None:
    """Neither .hg nor .git: NoVcsBackendError naming the repo path."""
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(vcs.NoVcsBackendError) as excinfo:
        vcs.detect_backend(bare)
    assert str(bare) in str(excinfo.value)
    assert ".hg" in str(excinfo.value) and ".git" in str(excinfo.value)


def test_hg_resolve_ref_returns_the_node(hg_repo: Path) -> None:
    """A known bookmark resolves to the full node hash."""
    backend = vcs.HgBackend(repo=hg_repo)
    node = backend.resolve_ref("new-docs-master")
    assert node == hg(hg_repo, "log", "-r", ".", "-T", "{node}").strip()


def test_hg_resolve_missing_bookmark_hints_pull(hg_repo: Path) -> None:
    """An unknown rev fails loudly with the pull remediation."""
    backend = vcs.HgBackend(repo=hg_repo)
    with pytest.raises(vcs.RefResolutionError) as excinfo:
        backend.resolve_ref("no-such-bookmark")
    msg = str(excinfo.value)
    assert "no-such-bookmark" in msg
    assert "pull" in msg


def test_git_resolve_ref_returns_the_sha(git_repo: Path) -> None:
    """A mirror branch resolves to the commit of refs/remotes/origin/<b>."""
    backend = vcs.GitBackend(repo=git_repo)
    sha = backend.resolve_ref("new-docs-fc-26.05-production")
    expected = git(
        git_repo,
        "rev-parse",
        "refs/remotes/origin/new-docs-fc-26.05-production^{commit}",
    ).strip()
    assert sha == expected


def test_git_resolve_missing_branch_hints_fetch_depth(git_repo: Path) -> None:
    """A branch absent from the clone fails with the fetch-depth hint."""
    backend = vcs.GitBackend(repo=git_repo)
    with pytest.raises(vcs.RefResolutionError) as excinfo:
        backend.resolve_ref(MISSING_BRANCH)
    msg = str(excinfo.value)
    assert MISSING_BRANCH in msg
    assert "fetch-depth" in msg
    assert "refs/remotes/origin" in msg


def test_hg_has_subtree_answers_directly(hg_repo: Path) -> None:
    """hg files path: says yes for doc/src, no for a missing tree."""
    backend = vcs.HgBackend(repo=hg_repo)
    node = backend.resolve_ref("new-docs-master")
    assert backend.has_subtree(node, "doc/src")
    assert not backend.has_subtree(node, "doc/src/25.11")


def test_git_has_subtree_answers_directly(git_repo: Path) -> None:
    """git ls-tree says yes for an existing tree, no for a missing one."""
    backend = vcs.GitBackend(repo=git_repo)
    sha = backend.resolve_ref("new-docs-master")
    assert backend.has_subtree(sha, "doc/src")
    assert not backend.has_subtree(sha, "doc/src/26.05")


def test_hg_export_lands_pages_at_dest_top(
    hg_repo: Path, tmp_path: Path
) -> None:
    """hg export moves the subtree's files to the top of dest."""
    put(hg_repo / "doc" / "src", "26.05/components/postgresql.md")
    hg(hg_repo, "addremove")
    hg(hg_repo, "commit", "-m", "namespaced 26.05")
    backend = vcs.HgBackend(repo=hg_repo)
    node = backend.resolve_ref("new-docs-master")

    dest = tmp_path / "out" / "26.05"
    backend.export_tree(node, Path("doc/src/26.05"), dest)

    assert (dest / "components" / "postgresql.md").is_file()
    assert not (dest / "doc").exists()
    assert not (dest / "26.05").exists()


def test_git_export_strips_the_archive_prefix(
    git_repo: Path, tmp_path: Path
) -> None:
    """git archive | tar --strip-components lands pages at dest top."""
    git(git_repo, "checkout", "-q", "new-docs-fc-26.05-production")
    put(git_repo / "doc" / "src" / "26.05", "components/postgresql.md")
    git(git_repo, "add", "-A", "doc")
    git(git_repo, "commit", "-q", "-m", "namespaced 26.05")
    # The backend resolves REMOTE refs: the commit must reach origin.
    git(git_repo, "push", "-q", "origin", "new-docs-fc-26.05-production")
    git(git_repo, "checkout", "-q", "new-docs-master")
    backend = vcs.GitBackend(repo=git_repo)
    sha = backend.resolve_ref("new-docs-fc-26.05-production")

    dest = tmp_path / "out" / "26.05"
    backend.export_tree(sha, Path("doc/src/26.05"), dest)

    assert (dest / "components" / "postgresql.md").is_file()
    assert not (dest / "doc").exists()
    assert not (dest / "src").exists()
    assert not (dest / "26.05").exists()


def test_git_export_whole_subtree_strips_two_components(
    git_repo: Path, tmp_path: Path
) -> None:
    """doc/src export (prerelease shape) strips doc/ and src/ only."""
    backend = vcs.GitBackend(repo=git_repo)
    sha = backend.resolve_ref("new-docs-master")

    dest = tmp_path / "out" / "master"
    backend.export_tree(sha, Path("doc/src"), dest)

    assert (dest / "index.md").is_file()
    assert not (dest / "doc").exists()


def test_matched_entry_hg_without_flag_uses_active_bookmark(
    hg_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """hg mode, no --matched, no GITHUB_REF_NAME: ACTIVE bookmark wins."""
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    vset = load_versions(versions_file(tmp_path))
    with capture_logs() as logs:
        matched = vcs.matched_entry(vset, hg_repo, None)
    assert matched.rev == "new-docs-master"
    event = next(e for e in logs if e["event"] == "matched-ref")
    assert event["backend"] == "hg"
    assert event["source"] == "active-bookmark"
    assert event["ver"] == "26.11"
    assert event["status"] == "prerelease"


def test_matched_flag_wins_over_active_bookmark_and_env(
    hg_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--matched beats the ACTIVE bookmark AND GITHUB_REF_NAME."""
    monkeypatch.setenv("GITHUB_REF_NAME", "new-docs-master")
    vset = load_versions(versions_file(tmp_path))
    with capture_logs() as logs:
        matched = vcs.matched_entry(
            vset, hg_repo, "new-docs-fc-26.05-production"
        )
    assert matched.rev == "new-docs-fc-26.05-production"
    event = next(e for e in logs if e["event"] == "matched-ref")
    assert event["source"] == "--matched"
    assert event["status"] == "stable"


def test_matched_flag_works_on_git_too(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit --matched selects the entry regardless of backend."""
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    vset = load_versions(versions_file(tmp_path))
    matched = vcs.matched_entry(vset, git_repo, "new-docs-master")
    assert matched.rev == "new-docs-master"


def test_git_falls_back_to_github_ref_name(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """git mode without --matched reads GITHUB_REF_NAME."""
    monkeypatch.setenv("GITHUB_REF_NAME", "new-docs-fc-25.11-production")
    vset = load_versions(versions_file(tmp_path))
    with capture_logs() as logs:
        matched = vcs.matched_entry(vset, git_repo, None)
    assert matched.rev == "new-docs-fc-25.11-production"
    event = next(e for e in logs if e["event"] == "matched-ref")
    assert event["source"] == "GITHUB_REF_NAME"
    assert event["ver"] == "25.11"


def test_git_without_any_matched_ref_fails_loudly(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """git mode, no --matched, no GITHUB_REF_NAME: MatchedRefError."""
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    vset = load_versions(versions_file(tmp_path))
    with pytest.raises(vcs.MatchedRefError) as excinfo:
        vcs.matched_entry(vset, git_repo, None)
    msg = str(excinfo.value)
    assert "--matched" in msg and "GITHUB_REF_NAME" in msg
    assert str(git_repo) in msg


def test_matched_rev_unknown_to_the_toml_fails_loudly(
    hg_repo: Path, tmp_path: Path
) -> None:
    """--matched naming an undeclared rev: error lists the known revs."""
    vset = load_versions(versions_file(tmp_path))
    with pytest.raises(vcs.MatchedRefError) as excinfo:
        vcs.matched_entry(vset, hg_repo, "feature-x")
    msg = str(excinfo.value)
    assert "feature-x" in msg
    for rev in (
        "new-docs-fc-26.05-production",
        "new-docs-master",
        "new-docs-fc-25.11-production",
    ):
        assert rev in msg


def test_seam_errors_form_one_family() -> None:
    """Every seam failure is a VcsError -- one catch at the CLI boundary."""
    for exc in (
        vcs.NoVcsBackendError,
        vcs.MatchedRefError,
        vcs.ActiveBookmarkError,
        vcs.RefResolutionError,
        vcs.NamespacedTreeError,
        vcs.ExportError,
    ):
        assert issubclass(exc, vcs.VcsError)


def test_checkout_tool_places_git_mirror_snapshots(
    git_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI in git mode: --matched selects the manual, mirror branches
    land as snapshots, and the stderr log tells the whole story.
    (main() reconfigures structlog, so capsys -- not capture_logs.)"""
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    doc = tmp_path / "git-doc"
    put(doc / "src", "index.md")
    put(doc / "src", "components/postgresql.md")
    versions = versions_file(doc)

    code = cot.main(
        [
            "--versions",
            str(versions),
            "--src",
            str(doc / "src"),
            "--repo",
            str(git_repo),
            "--matched",
            "new-docs-master",
        ]
    )

    assert code == 0
    err = capsys.readouterr().err
    assert "vcs-backend-detected" in err and "backend=git" in err
    assert "matched-ref" in err
    assert "source=--matched" in err and "ver=26.11" in err
    assert "checkout-placed" in err and "ver=26.05" in err
    assert "ver=25.11" in err
    assert (doc / "src" / "26.05" / "index.md").is_file()
    assert (doc / "src" / "25.11" / "index.md").is_file()
    assert not (doc / "src" / "26.11").exists()
