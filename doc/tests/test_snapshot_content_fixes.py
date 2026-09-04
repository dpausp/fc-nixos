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


PRE_FIX_USERS_INDEX = (
    "# Flying Circus platform 25.11 { #nixos-platform-index }\n"
    "\n"
    "## General platform\n"
    "\n"
    "## Specific software components (roles) { #nixos-components }\n"
    "\n"
    "\n"
    "[nixos]: https://nixos.org\n"
)

FIXED_USERS_INDEX = (
    "# Flying Circus platform 25.11 { #nixos-platform-index }\n"
    "\n"
    "## General platform\n"
    "\n"
    "## Specific software components (roles) { #nixos-components }\n"
    "\n"
    "## Permissions { #permissions }\n"
    "\n"
    "Permissions control user access to VMs and services. "
    "They are managed centrally via\n"
    "[my.flyingcircus.io](https://my.flyingcircus.io) and provisioned to all relevant\n"
    "systems, including proper removal of access rights. "
    "See also the permission table\n"
    "in the platform documentation.\n"
    "\n"
    "[nixos]: https://nixos.org\n"
)


def test_permissions_section_is_injected_where_missing() -> None:
    """Pre-fix branch revisions lack the Permissions section that
    security/data-protection.md's ``#permissions`` link needs -- the
    injection pair backfills it so the anchor resolves."""
    fixed, count = fix_page("platform/users/index.md", PRE_FIX_USERS_INDEX)

    assert count == 1
    assert fixed == FIXED_USERS_INDEX


def test_permissions_section_is_not_injected_twice() -> None:
    """Branch-fixed content already carries the section: the pre-fix
    shape no longer matches, the page must pass through untouched."""
    fixed, count = fix_page("platform/users/index.md", FIXED_USERS_INDEX)

    assert count == 0
    assert fixed == FIXED_USERS_INDEX


def test_late_2605_pairs_slurm_upgrade_and_webproxy_anchor() -> None:
    """The pre-link-fix 26.05 tree carries two more dead targets: the
    slurm upgrade notes and the #nixos-webproxy anchor variant."""
    slurm = (
        "listed in the [upgrade notes]"
        "(../../platform-releases/fc-26.05-production/upgrade.md#nixos-upgrade)."
    )
    upgrades = (
        "read the [role documentation]"
        "(../../platform-releases/fc-26.05-production/webproxy.md#nixos-webproxy)"
    )

    slurm_fixed, slurm_count = fix_page("components/slurm.md", slurm)
    up_fixed, up_count = fix_page("platform/upgrades-whats-new.md", upgrades)

    assert slurm_count == 1
    assert (
        "[upgrade notes](../platform/upgrades-whats-new.md#nixos-upgrade)"
        in (slurm_fixed)
    )
    assert up_count == 1
    assert "[role documentation](../components/webproxy.md#nixos-webproxy)" in (
        up_fixed
    )


def test_2511_mailserver_prefix_pairs_do_not_mangle_each_other() -> None:
    """The plain #nixos-mailserver pair must not eat
    #nixos-mailserver-basic-setup (25.11-era URLs)."""
    text = (
        "See [basic setup]"
        "(../../platform-releases/fc-25.11-production/mailserver.md"
        "#nixos-mailserver-basic-setup) and [the role]"
        "(../../platform-releases/fc-25.11-production/mailserver.md#nixos-mailserver)."
    )

    fixed, count = fix_text(text)

    assert count == 2
    assert "(#nixos-mailserver-basic-setup)" in fixed
    assert "(mailserver.md#nixos-mailserver)" in fixed
    assert "platform-releases" not in fixed
