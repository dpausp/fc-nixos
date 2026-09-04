"""Unit spec for ``tools.snapshot_content_fixes``.

The fix table is the supported way to make ANY placed snapshot
link-clean -- including snapshots placed from pre-fix branch
revisions. Pinned behavior:

- global ``FIXES`` pairs apply to every page, in list order;
- prefix-adjacent pairs (``#nixos-mysql`` vs ``#nixos-mysql-upgrade``,
  ``#infrastructure-storage`` vs ``#infrastructure-storage-performance``)
  must not mangle each other -- longer anchors run first;
- ``FILE_FIXES`` pairs apply only to their page id and run BEFORE the
  global pairs: the same dead URL can need a different replacement per
  source location;
- :func:`fix_tree` applies the per-page pipeline to a whole tree.
"""

from __future__ import annotations

from pathlib import Path

from tools.snapshot_content_fixes import fix_page, fix_text, fix_tree

DEAD_WEBGATEWAY = (
    "behind a [webgateway]"
    "(../../platform-releases/fc-26.05-production/webgateway.md"
    "#nixos-webgateway)."
)


def test_mysql_pairs_do_not_mangle_each_other() -> None:
    """The plain #nixos-mysql pair must not eat #nixos-mysql-upgrade."""
    text = (
        "Read [the upgrade path]"
        "(../../platform-releases/fc-26.05-production/mysql.md"
        "#nixos-mysql-upgrade) and [the role]"
        "(../../platform-releases/fc-26.05-production/mysql.md#nixos-mysql)."
    )

    fixed, count = fix_text(text)

    assert count == 2
    assert "(../components/mysql.md#nixos-mysql-upgrade)" in fixed
    assert "(mysql.md#nixos-mysql)" in fixed
    assert "platform-releases" not in fixed


def test_storage_prefix_pairs_do_not_cross_mangle() -> None:
    """The long performance anchor runs before its shorter prefix."""
    text = (
        "See [performance]"
        "(../../infrastructure/storage.md#infrastructure-storage-performance)"
        " and [clusters]"
        "(../infrastructure/storage.md#infrastructure-storage)."
    )

    fixed, count = fix_text(text)

    assert count == 2
    assert (
        "(../../infrastructure/block-storage.md"
        "#infrastructure-storage-performance)" in fixed
    )
    assert (
        "(../infrastructure/block-storage.md#infrastructure-storage)" in fixed
    )
    assert "/storage.md" not in fixed


def test_same_dead_url_gets_per_page_replacement() -> None:
    """components/lamp.md and platform/deployment/lamp.md share the
    dead webgateway URL but need different relative targets."""
    body = "# LAMP\n\n" + DEAD_WEBGATEWAY + "\n"

    comp_fixed, comp_count = fix_page("components/lamp.md", body)
    dep_fixed, dep_count = fix_page("platform/deployment/lamp.md", body)

    assert comp_count == 1
    assert dep_count == 1
    assert "[webgateway](webgateway.md#nixos-webgateway)" in comp_fixed
    assert (
        "[webgateway](../../components/webgateway.md#nixos-webgateway)"
        in dep_fixed
    )


def test_file_scoped_pair_wins_over_overlapping_global() -> None:
    """platform/ pages link their same-dir local.md; components/ pages
    need ../platform/ for the very same dead URL -- the file-scoped
    pairs must consume the URL before the global pair does."""
    dead = (
        "see [nixos-local](../../platform-releases/fc-26.05-production/"
        "local.md#nixos-local)"
    )

    mon_fixed, mon_count = fix_page("platform/monitoring.md", dead)
    mem_fixed, mem_count = fix_page("components/memcached.md", dead)

    assert mon_count == 1
    assert mem_count == 1
    assert "(local.md#nixos-local)" in mon_fixed
    assert "(../platform/local.md#nixos-local)" in mem_fixed


def test_pages_without_file_entry_get_global_pairs_only() -> None:
    """An unlisted page id falls back to the global pipeline alone."""
    fixed, count = fix_page("components/kubernetes.md", DEAD_WEBGATEWAY)

    assert count == 0
    assert fixed == DEAD_WEBGATEWAY


def test_fix_tree_applies_file_scoped_pairs(tmp_path: Path) -> None:
    """fix_tree resolves each page's id and applies its scoped pairs."""
    comp = tmp_path / "components"
    dep = tmp_path / "platform" / "deployment"
    comp.mkdir()
    dep.mkdir(parents=True)
    (comp / "lamp.md").write_text("# L\n\n" + DEAD_WEBGATEWAY + "\n")
    (dep / "lamp.md").write_text("# L\n\n" + DEAD_WEBGATEWAY + "\n")

    changed = fix_tree(tmp_path)

    assert changed == 2
    assert "(webgateway.md#nixos-webgateway)" in (comp / "lamp.md").read_text()
    assert (
        "(../../components/webgateway.md#nixos-webgateway)"
        in (dep / "lamp.md").read_text()
    )
