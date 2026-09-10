"""Rollback coverage: the fix table covers the OLDEST namespaced revs.

``platform-versions.toml`` may point at any rev that carries the
namespaced ``doc/src/<ver>/**`` tree. The oldest such revs are the
per-version move/integration changesets; every later branch rev only
ever REMOVED dead artifacts (link fixes, banner migration), never
added any. Link-cleaning the oldest revs therefore implies
link-cleaning ALL of them -- this spec pins that guarantee against
the REAL repository history:

- 26.05 -- ``897acc84f5c0`` "move doc content to new versioned structure"
- 25.11 -- ``9761b8ea8c4f`` "integrate 25.11 export docs from doc repo"

Both are placed like the Makefile pipeline does (real repo,
temporary src) and must come out free of every dead-era artifact.
Revs older than the moves fail loudly BY DESIGN (anti-duplication
guard, see ``test_checkout_versioned_docs``). Skipped where the
history is not available as Mercurial: the CI git mirror cannot
resolve hg node hashes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import REPO_ROOT as REPO
from tools import checkout_versioned_docs as cot
from tools.vcs_backend import active_bookmark

# Dead-era artifacts the fix table must clear on placement.
DEAD_MARKERS = (
    "platform-releases/",  # split-era link targets
    "infrastructure/storage.md",  # pre-rename storage targets
    "This is a sunsetting version",  # old fetch-era banners
    "{{ stable_url }}",  # unsubstituted handoff banners
)

requires_hg = pytest.mark.skipif(
    not (REPO / ".hg").is_dir(),
    reason="historical hg node hashes unresolvable (CI git mirror)",
)


def rollback_toml(active: str) -> str:
    """Versions file with the ACTIVE bookmark as local manual and both
    version branches rolled back to their oldest namespaced revs."""
    return (
        f"[[prerelease]]\n"
        f'ver = "26.11"\n'
        f'rev = "{active}"\n'
        f"\n"
        f"[stable]\n"
        f'ver = "26.05"\n'
        f'rev = "897acc84f5c0"\n'
        f"\n"
        f"[[sunsetting]]\n"
        f'ver = "25.11"\n'
        f'rev = "9761b8ea8c4f"\n'
    )


def place_rollback_snapshots(tmp_path: Path) -> Path:
    """Run the placement exactly like the Makefile pipeline: real repo,
    temporary versions file + src. Returns the src dir."""
    active = active_bookmark(REPO)
    assert active, "no active bookmark: rollback needs a local manual line"
    versions = tmp_path / "platform-versions.toml"
    versions.write_text(rollback_toml(active))
    src = tmp_path / "src"
    src.mkdir()

    code = cot.main(
        ["--versions", str(versions), "--src", str(src), "--repo", str(REPO)]
    )
    assert code == 0
    return src


@requires_hg
def test_oldest_namespaced_revs_place_link_clean(tmp_path: Path) -> None:
    """Rolling both branches back to their integration/move commits
    yields snapshots free of every dead-era marker."""
    src = place_rollback_snapshots(tmp_path)

    for ver in ("26.05", "25.11"):
        tree = src / ver
        assert tree.is_dir(), f"{ver} was not placed"
        pages = sorted(tree.rglob("*.md"))
        assert pages, f"{ver} tree is empty"
        for page in pages:
            text = page.read_text(encoding="utf-8")
            rel = page.relative_to(src)
            for marker in DEAD_MARKERS:
                assert marker not in text, f"{marker!r} survived in {rel}"


@requires_hg
def test_permissions_anchor_backfilled_at_oldest_revs(
    tmp_path: Path,
) -> None:
    """Pre-mdBook-fix revs lack the Permissions section that
    ``security/data-protection.md``'s ``#permissions`` link targets:
    the fix table injects it, so the anchor resolves at every
    namespaced rev (zensical validates anchors)."""
    src = place_rollback_snapshots(tmp_path)

    for ver in ("26.05", "25.11"):
        users = src / ver / "platform" / "users" / "index.md"
        assert users.is_file(), f"{ver}: platform/users/index.md missing"
        text = users.read_text(encoding="utf-8")
        assert "## Permissions { #permissions }" in text, (
            f"{ver}: Permissions section not backfilled"
        )
