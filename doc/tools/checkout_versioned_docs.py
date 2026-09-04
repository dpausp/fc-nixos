"""Place version snapshots under ``src/<ver>/`` from LOCAL VCS revisions.

The counterpart of ``tools.gen_platform_versions.py``: the entry
matched by :mod:`tools.vcs_backend` (the hg repo's ACTIVE bookmark
locally, or the ``--matched`` ref in a git mirror clone) is the local
manual -- never checked out. Every OTHER entry in
``platform-versions.toml`` is resolved STRICTLY locally (hg:
``hg log -r <rev>``, git: ``git rev-parse refs/remotes/origin/<rev>``
-- no network, no pull/fetch) and exported into ``src/<ver>/``.
An unresolvable rev fails loudly -- no fallback of any kind.

What gets exported depends on the status: ONLY prerelease revisions
(the living dev line) export the WHOLE ``doc/src/**``; every other
non-matched version -- sunsetting AND a non-matched ``[stable]``
alike -- exports ONLY its branch's namespaced ``doc/src/<ver>/**``
(the one-time sunset move commit). A non-prerelease revision without
that namespaced tree fails loudly with the remediation -- it NEVER
falls back to the whole tree, which would duplicate the stable
manual under a versioned URL.

Every placed snapshot is made link-clean first:
:mod:`tools.snapshot_content_fixes` re-applies the fix table already
landed on the integration line (dead split-era targets, old
fetch-era sunsetting banners) to the branch content. On top, every
NON-prerelease snapshot -- sunsetting and a non-matched ``[stable]``
alike -- gets ``search: exclude`` frontmatter (keeping it out of the
search index) and a warning banner linking the counterpart in the
built manual when it exists; only the banner wording differs (an old
stable's public status is stable, never sunsetting). Otherwise
prerelease snapshots stay verbatim: they ARE the integration line.

A manifest (``src/.checkout-manifest.json``) records the exported ref
(node hash or mirror-branch sha) per version plus the sha256 of this
tool and the fix table (:mod:`tools.snapshot_content_fixes`). A
version is skipped when BOTH are unchanged -- re-running never clobbers
the placed tree, and editing this tool OR the fix table re-places every
version (banner/frontmatter/fix-table logic may have changed). Undeclared
``src/<NN.NN>/`` dirs are pruned.

Regenerate via ``make checkout-versioned-docs`` (then
``make gen-platform-versions`` to refresh the switcher payload).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import structlog

from tools import snapshot_content_fixes
from tools.gen_platform_versions import (
    DOC_ROOT,
    REPO_ROOT,
    VersionEntry,
    load_versions,
)
from tools.snapshot_content_fixes import fix_tree
from tools.vcs_backend import (
    GitBackend,
    HgBackend,
    NamespacedTreeError,
    VcsError,
    detect_backend,
    matched_entry,
)

log = structlog.get_logger()

# Only doc/src of a revision becomes a snapshot: the whole tree for a
# prerelease, just the namespaced subtree for every other status.
MASTER_SUBTREE = Path("doc") / "src"


def namespaced_subtree(ver: str) -> Path:
    """Repo-relative subtree of a non-prerelease version's branch."""
    return MASTER_SUBTREE / ver


def namespaced_include(ver: str) -> str:
    """Archive include pattern for a non-prerelease version's subtree."""
    return f"{namespaced_subtree(ver).as_posix()}/**"


# Manifest lives (hidden) at the src/ root, beside the snapshot dirs.
MANIFEST_NAME = ".checkout-manifest.json"

# `search:` key in frontmatter (nested form: `search:\n  exclude: true`)
SEARCH_KEY_RE = re.compile(r"(?m)^search:")

SEARCH_EXCLUDE_BLOCK = "search:\n  exclude: true\n"

# Warning-banner sentence body per non-prerelease snapshot status. A
# non-matched [stable] gets the sunsetting treatment (search
# exclusion + banner) but its public status is stable: the wording
# must never say "sunsetting".
STATUS_CLAUSE = {
    "stable": "is an older version",
    "sunsetting": "is in sunsetting",
}


def fingerprint_of(*files: Path) -> str:
    """sha256 over the concatenated bytes of *files* (stable order)."""
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.read_bytes())
    return digest.hexdigest()


def tool_fingerprint() -> str:
    """sha256 of this module AND the fix table -- editing either re-places."""
    return fingerprint_of(Path(__file__), Path(snapshot_content_fixes.__file__))


def load_manifest(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text())


def write_manifest(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def ensure_namespaced_tree(
    backend: HgBackend | GitBackend, entry: VersionEntry, ref: str
) -> None:
    """Fail loudly when the revision lacks ``doc/src/<ver>/``.

    Every NON-prerelease ``rev`` (sunsetting, or a non-matched
    ``[stable]``) must point at the sunset move commit that namespaced
    ``doc/src`` into ``doc/src/<ver>/``. A revision without that tree
    (e.g. a pre-move changeset carrying the whole ``doc/src``) must
    NEVER fall back to it -- the snapshot would duplicate the stable
    manual under a versioned URL. The backend asks its VCS directly
    (hg: ``hg files path:``, git: ``git ls-tree``) whether the tree
    exists at *ref*; empty output means it does not.
    """
    if backend.has_subtree(ref, namespaced_subtree(entry.ver).as_posix()):
        return
    msg = (
        f"{entry.status} revision {ref[:12]} for ver {entry.ver} has "
        f"no doc/src/{entry.ver}/ tree -- every non-prerelease "
        f"snapshot must carry its branch's namespaced "
        f"doc/src/{entry.ver}/ subtree: point rev at the changeset "
        f"that moved doc/src into doc/src/{entry.ver}/ (the sunset "
        f"move); revisions carrying only the whole doc/src tree are "
        f"never a fallback"
    )
    raise NamespacedTreeError(msg)


def checkout_version(
    backend: HgBackend | GitBackend,
    src_root: Path,
    entry: VersionEntry,
    ref: str,
) -> Path:
    """Export ``ref``'s docs as ``src_root/<ver>/`` (replacing any old tree).

    Prerelease revisions export the WHOLE ``doc/src/**`` (the living
    dev line); every other status -- sunsetting and a non-matched
    ``[stable]`` alike -- only its branch's namespaced
    ``doc/src/<ver>/**`` (see :func:`ensure_namespaced_tree`). The
    backend's export strips its own prefixes: pages land at the TOP
    of ``src_root/<ver>/`` for both hg and git.
    """
    if entry.status == "prerelease":
        subtree = MASTER_SUBTREE
    else:
        ensure_namespaced_tree(backend, entry, ref)
        subtree = namespaced_subtree(entry.ver)
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "out"
        backend.export_tree(ref, subtree, staging)
        target = src_root / entry.ver
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(staging), str(target))
    return target


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split into (frontmatter-with-delimiters, body); ("", text) if none.

    A leading ``---`` without a closing ``---`` line is NOT frontmatter
    (e.g. a stray horizontal rule) -- everything stays in the body.
    """
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---", 4)
    if end == -1:
        return "", text
    close_end = text.find("\n", end + 1)
    if close_end == -1:
        return text, ""
    return text[: close_end + 1], text[close_end + 1 :]


def frontmatter_with_search_exclude(frontmatter: str) -> str:
    """A frontmatter block (with delimiters) carrying the search key.

    The key is inserted right after the opening delimiter -- unless a
    ``search:`` key is already there (left alone; sunsetting trees come
    from backports that carry our conventions).
    """
    if SEARCH_KEY_RE.search(frontmatter):
        return frontmatter
    return frontmatter.replace("---\n", f"---\n{SEARCH_EXCLUDE_BLOCK}", 1)


def process_snapshot(
    tree: Path, ver: str, status: str, stable_ver: str, src_root: Path
) -> int:
    """Frontmatter + banner on every page of a non-prerelease snapshot.

    Order matters: frontmatter must stay the FIRST thing in the file
    (zensical only parses it there), the banner follows, then the
    untouched body. The banner links the stable counterpart only when
    the page exists in the local tree -- a dead ref would break the
    build's link validation. ``status`` picks the banner wording
    (:data:`STATUS_CLAUSE`). Returns the number of processed pages.
    """
    clause = STATUS_CLAUSE[status]
    count = 0
    for page in sorted(tree.rglob("*.md")):
        page_id = page.relative_to(tree).with_suffix("").as_posix()
        counterpart = (src_root / f"{page_id}.md").is_file()
        frontmatter, body = split_frontmatter(page.read_text())
        if frontmatter:
            frontmatter = frontmatter_with_search_exclude(frontmatter)
        else:
            frontmatter = f"---\n{SEARCH_EXCLUDE_BLOCK}---\n"
        page.write_text(
            frontmatter
            + "\n"
            + banner(page_id, ver, stable_ver, counterpart, clause)
            + body.lstrip("\n")
        )
        count += 1
    log.info("snapshot-annotated", ver=ver, status=status, pages=count)
    return count


def banner(
    page_id: str, ver: str, stable_ver: str, counterpart: bool, clause: str
) -> str:
    """Warning banner; links the stable counterpart if it exists."""
    up = "../" * (page_id.count("/") + 1)
    if counterpart:
        target = f"{up}{page_id}"
        where = f"the [{stable_ver} version]({target})"
    else:
        where = f"the [{stable_ver} manual]({up}index)"
    return (
        f'!!! warning "Documentation for platform version {ver}"\n'
        f"    Platform version {ver} {clause} -- this page is kept for"
        " reference.\n"
        f"    The stable documentation for this topic is {where}.\n\n"
    )


def prune_orphans(src_root: Path, keep: set[str]) -> list[str]:
    """Remove undeclared ``src/<NN.NN>/`` snapshot dirs; return their names."""
    pruned = []
    if not src_root.is_dir():
        return pruned
    for child in sorted(src_root.iterdir()):
        if (
            child.is_dir()
            and re.fullmatch(r"\d{2}\.\d{2}", child.name)
            and child.name not in keep
        ):
            shutil.rmtree(child)
            pruned.append(child.name)
            log.info("orphan-pruned", ver=child.name, path=str(child))
    return pruned


def run_checkout(
    versions_path: Path,
    src_root: Path,
    repo: Path,
    matched_ref: str | None = None,
) -> tuple[int, int, list[str]]:
    """Checkout driver: (checked-out, skipped, pruned) counts.

    Shared by ``main`` and tests -- everything except argparse and log
    configuration lives here. The entry selected by the VCS seam
    (:func:`tools.vcs_backend.matched_entry`: ACTIVE bookmark for hg,
    ``matched_ref``/``GITHUB_REF_NAME`` for git) IS the local manual
    and is never checked out; ALL other entries become snapshots, a
    non-matched ``[stable]`` included (from its namespaced tree, like
    a sunsetting version). Every placement is made link-clean (content
    fixes) and every non-prerelease snapshot annotated (search-exclude
    frontmatter + warning banner).
    """
    versions = load_versions(versions_path)
    backend = detect_backend(repo)
    manual = matched_entry(versions, repo, matched_ref)
    entries = [e for e in versions.entries() if e.ver != manual.ver]

    manifest_path = src_root / MANIFEST_NAME
    manifest = load_manifest(manifest_path)
    fingerprint = tool_fingerprint()
    recorded: dict = manifest.get("versions", {})
    same_tool = manifest.get("tool_sha256") == fingerprint

    result = {"tool_sha256": fingerprint, "versions": {}}
    checked = skipped = 0

    for entry in entries:
        ref = backend.resolve_ref(entry.rev)
        if same_tool and recorded.get(entry.ver, {}).get("ref") == ref:
            log.info("checkout-skipped", ver=entry.ver, ref=ref[:12])
            skipped += 1
            result["versions"][entry.ver] = {"ref": ref}
            continue
        tree = checkout_version(backend, src_root, entry, ref)
        log.info("checkout-placed", ver=entry.ver, ref=ref[:12], path=str(tree))
        fixed = fix_tree(tree)
        log.info("content-fixes-applied", ver=entry.ver, pages=fixed)
        if entry.status != "prerelease":
            process_snapshot(
                tree, entry.ver, entry.status, manual.ver, src_root
            )
        result["versions"][entry.ver] = {"ref": ref}
        checked += 1

    pruned = prune_orphans(src_root, set(result["versions"]))
    write_manifest(manifest_path, result)
    return checked, skipped, pruned


# Minimum log level for the CLI (matches logging.INFO; the int literal keeps
# the tool free of an ``import logging`` per the project's structlog-only rule).
_INFO_LEVEL = 20


def _configure_logging() -> None:
    """Render human-readable diagnostics to stderr (see gen_platform_versions)."""
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(_INFO_LEVEL),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry: ``python -m tools.checkout_versioned_docs``.

    Exit codes: ``0`` (placed/skipped/pruned), ``1`` (rev resolution,
    export, or matched-ref failure), ``2`` (invalid
    platform-versions.toml).
    """
    _configure_logging()
    parser = argparse.ArgumentParser(
        prog="checkout_versioned_docs",
        description="Place src/<ver>/ snapshots from local revisions (hg working copy or git mirror clone).",
    )
    parser.add_argument(
        "--versions", type=Path, default=DOC_ROOT / "platform-versions.toml"
    )
    parser.add_argument("--src", type=Path, default=DOC_ROOT / "src")
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--matched",
        metavar="REV",
        default=None,
        help="Rev whose entry IS the manual at '/' (default: the ACTIVE "
        "bookmark of an hg repo; in git mode GITHUB_REF_NAME)",
    )
    args = parser.parse_args(argv)

    try:
        checked, skipped, pruned = run_checkout(
            args.versions, args.src, args.repo, args.matched
        )
    except ValueError as exc:
        log.error("versions-invalid", path=str(args.versions), error=str(exc))
        return 2
    except VcsError as exc:
        log.error("checkout-failed", error=str(exc))
        return 1

    log.info("checkout-done", checked=checked, skipped=skipped, pruned=pruned)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
