"""Dual-VCS seam (hg | git) for the docs pipeline tools.

Both repo-reading tools (:mod:`tools.gen_platform_versions`,
:mod:`tools.checkout_versioned_docs`) speak ONE interface: the backend
auto-detected at the ``--repo`` path -- ``.hg/`` selects hg, ``.git/``
selects git, neither fails loudly (:class:`NoVcsBackendError`).

hg is the LOCAL backend: the repo's ACTIVE bookmark selects the
matched entry -- the manual built at ``/`` -- exactly as ``hg su``
reports it. Revs resolve strictly locally (``hg log``, no pull), the
namespaced check asks ``hg files`` directly, and export is
``hg archive`` into a staging dir.

git is the CI backend: GitHub mirror branches. The TOML ``rev`` IS the
branch name, resolved as the fully-qualified
``refs/remotes/origin/<branch>`` of a full clone (the workflow's
``fetch-depth: 0`` -- a shallow clone only carries the built branch),
checked via ``git ls-tree`` and exported via
``git archive <sha> <path> | tar -x --strip-components`` with the
archive prefix stripped. In git mode the matched ref is REQUIRED: the
``--matched`` flag wins over ``GITHUB_REF_NAME`` (the ref GitHub
Actions built); neither set fails loudly.

Both backends serve the same pipeline: identical payloads and
snapshot trees from content-identical repositories.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from tools.gen_platform_versions import VersionEntry, VersionSet

log = structlog.get_logger()


class VcsError(RuntimeError):
    """A VCS seam operation failed -- loud, with remediation."""


class NoVcsBackendError(VcsError):
    """The repo path carries neither ``.hg/`` nor ``.git/``."""


class MatchedRefError(VcsError):
    """The matched ref (``--matched``/``GITHUB_REF_NAME``) is missing
    or unknown to the TOML."""


class ActiveBookmarkError(VcsError):
    """The repo's active bookmark cannot identify the local manual."""


class RefResolutionError(VcsError):
    """A rev/mirror branch cannot be resolved locally."""


class NamespacedTreeError(VcsError):
    """A non-prerelease revision lacks its ``doc/src/<ver>/`` tree."""


class ExportError(VcsError):
    """A revision's docs tree could not be exported."""


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """One captured VCS subprocess -- never checked, never silent."""
    return subprocess.run(
        argv, cwd=cwd, capture_output=True, text=True, check=False
    )


@dataclass(frozen=True, slots=True)
class HgBackend:
    """hg working directory: ACTIVE bookmark + local archive export."""

    repo: Path

    @property
    def name(self) -> str:
        return "hg"

    def resolve_ref(self, rev: str) -> str:
        """Resolve ``rev`` to a node hash, strictly locally.

        Missing bookmarks raise :class:`RefResolutionError` with the
        remediation -- the caller must surface it, the user must pull.
        This backend never touches the network.
        """
        proc = _run(["hg", "log", "-r", rev, "-T", "{node}"], self.repo)
        if proc.returncode != 0:
            msg = (
                f"cannot resolve rev {rev!r} locally "
                f"({proc.stderr.strip()}) -- pull the bookmark into your "
                "clone yourself; this tool never pulls"
            )
            raise RefResolutionError(msg)
        return proc.stdout.strip()

    def has_subtree(self, ref: str, path: str) -> bool:
        """Ask hg directly whether *ref* carries the *path* tree.

        ``hg files`` with an explicit ``path:`` kind; empty output
        means the tree does not exist at *ref*.
        """
        proc = _run(["hg", "files", "-r", ref, f"path:{path}"], self.repo)
        return proc.returncode == 0 and bool(proc.stdout.strip())

    def export_tree(self, ref: str, subtree: Path, dest: Path) -> None:
        """Export *subtree* of *ref* so its files land directly in *dest*.

        ``hg archive`` with an include pattern extracts into a staging
        dir; the subtree is moved out (the archive bookkeeping file at
        the staging root stays behind).
        """
        path = subtree.as_posix()
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run(
                ["hg", "archive", "-r", ref, "-I", f"{path}/**", tmp],
                self.repo,
            )
            if proc.returncode != 0:
                msg = (
                    f"hg archive failed for {ref[:12]} ({path}): "
                    f"{proc.stderr.strip()}"
                )
                raise ExportError(msg)
            exported = Path(tmp) / subtree
            if not exported.is_dir():
                msg = (
                    f"revision {ref[:12]} has no {path} tree -- "
                    "nothing to place"
                )
                raise ExportError(msg)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(exported), str(dest))


@dataclass(frozen=True, slots=True)
class GitBackend:
    """git clone of a GitHub mirror: ``refs/remotes/origin/<branch>``."""

    repo: Path

    @property
    def name(self) -> str:
        return "git"

    def resolve_ref(self, rev: str) -> str:
        """Resolve the mirror branch *rev* to a commit sha.

        The TOML ``rev`` IS the branch name, resolved fully-qualified
        as ``refs/remotes/origin/<rev>``. A missing branch raises
        :class:`RefResolutionError` with the ``fetch-depth`` hint: a
        shallow CI clone only fetches the built branch, the workflow
        needs ``fetch-depth: 0`` to carry ALL mirror branches.
        """
        qualified = f"refs/remotes/origin/{rev}"
        proc = _run(
            [
                "git",
                "rev-parse",
                "--verify",
                "--quiet",
                f"{qualified}^{{commit}}",
            ],
            self.repo,
        )
        if proc.returncode != 0:
            msg = (
                f"cannot resolve mirror branch {rev!r} as {qualified} "
                f"in {self.repo} ({proc.stderr.strip()}) -- a mirror "
                "clone must carry ALL declared branches: the CI "
                "checkout needs fetch-depth: 0 (a shallow clone only "
                "fetches the built branch); fetch the branch into your "
                "clone yourself, this tool never fetches"
            )
            raise RefResolutionError(msg)
        return proc.stdout.strip()

    def has_subtree(self, ref: str, path: str) -> bool:
        """Ask git directly whether *ref* carries the *path* tree.

        ``git ls-tree`` with a trailing slash lists the tree's
        contents; empty output means the tree does not exist at *ref*.
        """
        proc = _run(["git", "ls-tree", ref, "--", f"{path}/"], self.repo)
        return proc.returncode == 0 and bool(proc.stdout.strip())

    def export_tree(self, ref: str, subtree: Path, dest: Path) -> None:
        """Export *subtree* of *ref* so its files land directly in *dest*.

        ``git archive <ref> <path>`` streams a tar whose entries carry
        the full repo-relative prefix; ``tar --strip-components``
        (one component per subtree level) strips it, landing the
        pages at the top of *dest*.
        """
        path = subtree.as_posix()
        with tempfile.TemporaryDirectory() as tmp:
            extract_dir = Path(tmp) / "out"
            extract_dir.mkdir()
            archive = subprocess.Popen(
                ["git", "archive", "--format=tar", ref, path],
                cwd=self.repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout = archive.stdout
            if stdout is None:  # Popen(stdout=PIPE) always pipes
                msg = "git archive produced no stdout pipe"
                raise ExportError(msg)
            extract = subprocess.run(
                [
                    "tar",
                    "-x",
                    "--strip-components",
                    str(len(subtree.parts)),
                    "-C",
                    str(extract_dir),
                ],
                stdin=stdout,
                capture_output=True,
                text=True,
                check=False,
            )
            stdout.close()
            archive_error = ""
            if archive.stderr is not None:
                archive_error = archive.stderr.read().strip()
                archive.stderr.close()
            if archive.wait() != 0:
                msg = (
                    f"git archive failed for {ref[:12]} ({path}): "
                    f"{archive_error}"
                )
                raise ExportError(msg)
            if extract.returncode != 0:
                msg = (
                    f"tar extraction failed for {ref[:12]} ({path}): "
                    f"{extract.stderr.strip()}"
                )
                raise ExportError(msg)
            if not any(extract_dir.iterdir()):
                msg = (
                    f"revision {ref[:12]} has no {path} tree -- "
                    "nothing to place"
                )
                raise ExportError(msg)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(extract_dir), str(dest))


def detect_backend(repo: Path) -> HgBackend | GitBackend:
    """Auto-detect the VCS backend at the repo path.

    ``.hg`` -> :class:`HgBackend`, ``.git`` -> :class:`GitBackend`
    (a directory, or a file for worktrees/submodules), neither ->
    :class:`NoVcsBackendError`. Detection is by path ONLY -- CI
    leftovers like ``GITHUB_REF_NAME`` never select a backend.
    """
    if (repo / ".hg").is_dir():
        backend: HgBackend | GitBackend = HgBackend(repo=repo)
    elif (repo / ".git").exists():
        backend = GitBackend(repo=repo)
    else:
        msg = (
            f"{repo} carries neither .hg/ nor .git/ -- the VCS backend "
            "is auto-detected at the --repo path: point --repo at a "
            "working copy (hg) or clone (git) of the manual's repository"
        )
        raise NoVcsBackendError(msg)
    log.info("vcs-backend-detected", backend=backend.name, repo=str(repo))
    return backend


def active_bookmark(repo: Path) -> str:
    """The repo's ACTIVE bookmark name (``''`` when none is active).

    ``hg log -r . -T {activebookmark}`` reads exactly what ``hg su``
    (summary) reports as active: the bookmark the working dir sits on
    AND advances on commit. Updating to a bare rev deactivates it.
    """
    proc = _run(["hg", "log", "-r", ".", "-T", "{activebookmark}"], repo)
    if proc.returncode != 0:
        msg = (
            f"cannot read the active bookmark of {repo} "
            f"({proc.stderr.strip()}) -- is it an hg working directory?"
        )
        raise ActiveBookmarkError(msg)
    return proc.stdout.strip()


def match_active(versions: VersionSet, repo: Path) -> VersionEntry:
    """The declared entry whose ``rev`` is the repo's ACTIVE bookmark.

    That entry IS the local manual: it builds at ``/`` and is never
    checked out, whatever its TOML category. No active bookmark, or one
    unknown to the TOML, is an error -- there is NO fallback to any
    category: guessing would silently build the wrong manual at ``/``.
    """
    bookmark = active_bookmark(repo)
    if not bookmark:
        msg = (
            f"no active bookmark in {repo} -- the ACTIVE bookmark selects "
            "the local manual: hg up <bookmark> to activate one (verify "
            "with hg su); there is no fallback"
        )
        raise ActiveBookmarkError(msg)
    for entry in versions.entries():
        if entry.rev == bookmark:
            return entry
    known = ", ".join(entry.rev for entry in versions.entries())
    msg = (
        f"active bookmark {bookmark!r} matches no rev in "
        f"platform-versions.toml (known revs: {known}) -- hg up one of "
        "them or declare the rev"
    )
    raise ActiveBookmarkError(msg)


def matched_entry(
    versions: VersionSet, repo: Path, matched: str | None
) -> VersionEntry:
    """The declared entry whose content IS the manual built at ``/``.

    ``matched`` (the ``--matched`` flag) wins over everything: it
    names the rev directly. Without it, an hg repo falls back to its
    ACTIVE bookmark (:func:`match_active`, the local semantics); a
    git repo falls back to ``GITHUB_REF_NAME`` (the ref GitHub
    Actions built) and raises :class:`MatchedRefError` when neither
    is set -- there is NO fallback to any TOML category.
    """
    backend = detect_backend(repo)
    source = "--matched"
    if matched is not None:
        entry = _entry_by_rev(versions, matched, source, backend)
    elif isinstance(backend, HgBackend):
        source = "active-bookmark"
        entry = match_active(versions, repo)
    else:
        source = "GITHUB_REF_NAME"
        rev = os.environ.get("GITHUB_REF_NAME", "").strip()
        if not rev:
            msg = (
                f"git backend at {repo} needs the matched mirror "
                "branch: pass --matched <rev> or set GITHUB_REF_NAME "
                "(the ref GitHub Actions built); there is no fallback"
            )
            raise MatchedRefError(msg)
        entry = _entry_by_rev(versions, rev, source, backend)
    log.info(
        "matched-ref",
        backend=backend.name,
        source=source,
        ver=entry.ver,
        rev=entry.rev,
        status=entry.status,
    )
    return entry


def _entry_by_rev(
    versions: VersionSet,
    rev: str,
    source: str,
    backend: HgBackend | GitBackend,
) -> VersionEntry:
    """The declared entry whose ``rev`` equals *rev* -- or loud failure."""
    for entry in versions.entries():
        if entry.rev == rev:
            return entry
    known = ", ".join(entry.rev for entry in versions.entries())
    msg = (
        f"{source} rev {rev!r} matches no rev in "
        f"platform-versions.toml (known revs: {known}) -- in git mode "
        "the TOML revs ARE the mirror branch names"
    )
    raise MatchedRefError(msg)
