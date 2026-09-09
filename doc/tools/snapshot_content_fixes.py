"""Content fixes applied to placed version snapshots.

The version branches carry pre-fix content: dead split-era link
targets (``platform-releases/<branch>/...`` and
``../platform/<branch>/...``), pre-rename infrastructure targets
(``storage.md``), and old fetch-era sunsetting banners with dead
links. This table mirrors the fixes already applied to the
integration line and the version branches, so EVERY placed snapshot
becomes link-clean without backporting first -- adding a pair is the
supported way to temporarily fix unfixed branch content.

:data:`FIXES` pairs apply to every page; :data:`FILE_FIXES` pairs are
scoped to one page id (relative to the snapshot root) for dead URLs
that need a different replacement per source location.

ROLLBACK COVERAGE: pairs stay alive even after their fixes land on
the branch tips -- ``platform-versions.toml`` may point at any rev
that carries the namespaced tree, and pre-fix revs still need the
table (pinned by ``test_rollback_coverage`` against the oldest
namespaced revs).
"""

from __future__ import annotations

import re
from pathlib import Path

# (old, new) pairs, applied verbatim to every *.md of a placed snapshot.
FIXES: list[tuple[str, str]] = [
    # platform-releases split-era targets (platform/ pages)
    (
        "[managed components](../../platform-releases/fc-26.05-production/index.md#nixos-components)",
        "managed components",
    ),
    (
        "../../platform-releases/fc-26.05-production/logrotate.md#nixos-logrotate",
        "logrotate.md#nixos-logrotate",
    ),
    (
        "../../platform-releases/fc-26.05-production/user_profile.md#nixos-user-package-management",
        "user-profile.md#nixos-user-package-management",
    ),
    (
        "../../platform-releases/fc-26.05-production/systemd.md#nixos-systemd-app-service-example",
        "#nixos-systemd-app-service-example",
    ),
    # 26.05-era platform-releases remnants (folded from the branch link
    # fixes). Longer anchors first: the plain mysql pair would otherwise
    # mangle ...#nixos-mysql-upgrade, the performance pair must run
    # before its shorter prefix below.
    (
        "../../platform-releases/fc-26.05-production/mysql.md#nixos-mysql-upgrade",
        "../components/mysql.md#nixos-mysql-upgrade",
    ),
    (
        "../../platform-releases/fc-26.05-production/mysql.md#nixos-mysql",
        "mysql.md#nixos-mysql",
    ),
    (
        "../../platform-releases/fc-26.05-production/postgresql.md#nixos-postgresql-server",
        "postgresql.md#nixos-postgresql-server",
    ),
    (
        "../../platform-releases/fc-26.05-production/mailserver.md#nixos-mailserver-basic-setup",
        "#nixos-mailserver-basic-setup",
    ),
    (
        "../../platform-releases/fc-26.05-production/mailserver.md#mail-into-backends",
        "#mail-into-backends",
    ),
    (
        "../../platform-releases/fc-26.05-production/mailserver.md#nixos-mailserver",
        "mailserver.md#nixos-mailserver",
    ),
    (
        "../../platform-releases/fc-26.05-production/devhost.md#nixos-devhost",
        "devhost.md#nixos-devhost",
    ),
    (
        "../../platform-releases/fc-26.05-production/statshost.md#nixos-statshost",
        "statshost.md#nixos-statshost",
    ),
    (
        "../../platform-releases/fc-26.05-production/local.md#nixos-custom-modules",
        "../platform/local.md#nixos-custom-modules",
    ),
    (
        "../../platform-releases/fc-26.05-production/local.md#nixos-local",
        "../platform/local.md#nixos-local",
    ),
    (
        "../../platform-releases/fc-26.05-production/slurm.md#nixos-slurm-config-reference",
        "#nixos-slurm-config-reference",
    ),
    (
        "../../platform-releases/fc-26.05-production/slurm.md#nixos-fc-slurm",
        "#nixos-fc-slurm",
    ),
    (
        "../../platform-releases/fc-26.05-production/slurm.md#nixos-slurm-upgrade",
        "../components/slurm.md#nixos-slurm-upgrade",
    ),
    (
        "../../platform-releases/fc-26.05-production/webproxy.md#nixos-webgateway",
        "../components/webproxy.md#nixos-webgateway",
    ),
    (
        "../../platform-releases/fc-26.05-production/kubernetes.md#nixos-k3s-ipv6",
        "../components/kubernetes.md#nixos-k3s-ipv6",
    ),
    (
        "../../platform-releases/fc-26.05-production/kubernetes.md#nixos-k3s-update-versions",
        "../components/kubernetes.md#nixos-k3s-update-versions",
    ),
    (
        "See [nixos-webgateway](../../platform-releases/fc-26.05-production/webgateway.md#nixos-webgateway)",
        "See [nixos-webgateway](webgateway.md#nixos-webgateway)",
    ),
    (
        "../../platform-releases/fc-26.05-production/upgrades-whats-new.md#nixos-upgrade-general",
        "#nixos-upgrade-general",
    ),
    (
        "../../platform-releases/fc-26.05-production/upgrades-whats-new.md#nixos-upgrade-breaking",
        "#nixos-upgrade-breaking",
    ),
    (
        "../../platform-releases/fc-26.05-production/upgrades-whats-new.md#nixos-upgrade-percona",
        "#nixos-upgrade-percona",
    ),
    (
        "../../platform-releases/fc-26.05-production/upgrades-whats-new.md#nixos-upgrade-mail",
        "#nixos-upgrade-mail",
    ),
    (
        "../../platform-releases/fc-26.05-production/upgrades-whats-new.md#nixos-upgrade-opensearch",
        "#nixos-upgrade-opensearch",
    ),
    (
        "../../platform-releases/fc-26.05-production/upgrades-whats-new.md#nixos-upgrade-slurm",
        "#nixos-upgrade-slurm",
    ),
    (
        "../../platform-releases/fc-26.05-production/upgrades-whats-new.md#nixos-upgrade-webproxy",
        "#nixos-upgrade-webproxy",
    ),
    (
        "../../platform-releases/fc-26.05-production/upgrades-whats-new.md#nixos-upgrade-k3s",
        "#nixos-upgrade-k3s",
    ),
    # late 26.05 finds: slurm upgrade notes + webproxy anchor variant
    # (#nixos-webproxy, not the #nixos-webgateway entry above)
    (
        "../../platform-releases/fc-26.05-production/upgrade.md#nixos-upgrade",
        "../platform/upgrades-whats-new.md#nixos-upgrade",
    ),
    (
        "../../platform-releases/fc-26.05-production/webproxy.md#nixos-webproxy",
        "../components/webproxy.md#nixos-webproxy",
    ),
    # 25.11-era platform-releases remnants (folded from the 25.11 branch
    # link fixes). Same ordering rules: longer anchors first.
    (
        "../../platform-releases/fc-25.11-production/mailserver.md#nixos-mailserver-basic-setup",
        "#nixos-mailserver-basic-setup",
    ),
    (
        "../../platform-releases/fc-25.11-production/mailserver.md#mail-into-backends",
        "#mail-into-backends",
    ),
    (
        "../../platform-releases/fc-25.11-production/mailserver.md#nixos-mailserver",
        "mailserver.md#nixos-mailserver",
    ),
    (
        "../../platform-releases/fc-25.11-production/postgresql.md#nixos-postgresql-server",
        "postgresql.md#nixos-postgresql-server",
    ),
    (
        "../../platform-releases/fc-25.11-production/postgresql.md#nixos-postgresql-major-upgrade",
        "../components/postgresql.md#nixos-postgresql-major-upgrade",
    ),
    (
        "../../platform-releases/fc-25.11-production/mysql.md#nixos-mysql",
        "mysql.md#nixos-mysql",
    ),
    (
        "../../platform-releases/fc-25.11-production/devhost.md#nixos-devhost",
        "devhost.md#nixos-devhost",
    ),
    (
        "../../platform-releases/fc-25.11-production/statshost.md#nixos-statshost",
        "statshost.md#nixos-statshost",
    ),
    (
        "../../platform-releases/fc-25.11-production/local.md#nixos-custom-modules",
        "../platform/local.md#nixos-custom-modules",
    ),
    (
        "../../platform-releases/fc-25.11-production/local.md#nixos-local",
        "../platform/local.md#nixos-local",
    ),
    (
        "../../platform-releases/fc-25.11-production/slurm.md#nixos-slurm-config-reference",
        "#nixos-slurm-config-reference",
    ),
    (
        "../../platform-releases/fc-25.11-production/slurm.md#nixos-fc-slurm",
        "#nixos-fc-slurm",
    ),
    (
        "../../platform-releases/fc-25.11-production/slurm.md#nixos-slurm-upgrade",
        "../components/slurm.md#nixos-slurm-upgrade",
    ),
    (
        "../../platform-releases/fc-25.11-production/upgrade.md#nixos-upgrade",
        "../platform/upgrades-whats-new.md#nixos-upgrade",
    ),
    (
        "../../platform-releases/fc-25.11-production/user_profile.md#nixos-user-package-management",
        "user-profile.md#nixos-user-package-management",
    ),
    (
        "../../platform-releases/fc-25.11-production/systemd.md#nixos-systemd-app-service-example",
        "#nixos-systemd-app-service-example",
    ),
    (
        "../../platform-releases/fc-25.11-production/logrotate.md#nixos-logrotate",
        "logrotate.md#nixos-logrotate",
    ),
    (
        "../../platform-releases/fc-25.11-production/index.md#nixos-components",
        "../index.md#nixos-components",
    ),
    (
        "../../platform-releases/fc-25.11-production/webgateway.md#nixos-webgateway",
        "webgateway.md#nixos-webgateway",
    ),
    (
        "../../platform-releases/fc-25.11-production/ferretdb.md#nixos-ferretdb",
        "ferretdb.md#nixos-ferretdb",
    ),
    (
        "../../platform-releases/fc-25.11-production/upgrades-whats-new.md#nixos-upgrade-general",
        "#nixos-upgrade-general",
    ),
    (
        "../../platform-releases/fc-25.11-production/upgrades-whats-new.md#nixos-upgrade-breaking",
        "#nixos-upgrade-breaking",
    ),
    (
        "../../platform-releases/fc-25.11-production/upgrades-whats-new.md#nixos-upgrade-postgresql",
        "#nixos-upgrade-postgresql",
    ),
    (
        "../../platform-releases/fc-25.11-production/upgrades-whats-new.md#nixos-upgrade-percona",
        "#nixos-upgrade-percona",
    ),
    (
        "../../platform-releases/fc-25.11-production/upgrades-whats-new.md#nixos-upgrade-webgateway",
        "#nixos-upgrade-webgateway",
    ),
    (
        "../../platform-releases/fc-25.11-production/upgrades-whats-new.md#nixos-upgrade-mail",
        "#nixos-upgrade-mail",
    ),
    (
        "../../platform-releases/fc-25.11-production/upgrades-whats-new.md#nixos-upgrade-slurm",
        "#nixos-upgrade-slurm",
    ),
    # split-era targets under ../platform/<branch>/ (components/ pages)
    (
        "../platform/fc-26.05-production/local.md#nixos-custom-modules",
        "../platform/local.md#nixos-custom-modules",
    ),
    (
        "../platform/fc-26.05-production/local.md#nixos-local",
        "../platform/local.md#nixos-local",
    ),
    (
        "../platform/fc-26.05-production/upgrade.md#nixos-upgrade",
        "../platform/upgrades-whats-new.md#nixos-upgrade",
    ),
    (
        "../platform/fc-26.05-production/images/http_platform.png",
        "../images/http_platform.png",
    ),
    (
        "../platform/fc-26.05-production/images/tcp_ingress.png",
        "../images/tcp_ingress.png",
    ),
    (
        "../platform/fc-26.05-production/images/statshost/loki-explore.png",
        "../images/statshost/loki-explore.png",
    ),
    (
        "../platform/fc-26.05-production/images/statshost/loki-datasource.png",
        "../images/statshost/loki-datasource.png",
    ),
    (
        "../platform/fc-26.05-production/images/statshost/loki-simple-query.png",
        "../images/statshost/loki-simple-query.png",
    ),
    (
        "../platform/fc-26.05-production/images/statshost/loki-simple-query-results.png",
        "../images/statshost/loki-simple-query-results.png",
    ),
    (
        "../platform/fc-26.05-production/images/statshost/loki-demo-dashboards.png",
        "../images/statshost/loki-demo-dashboards.png",
    ),
    (
        "../platform/fc-26.05-production/images/statshost/loki-basic-logging-dashboard.png",
        "../images/statshost/loki-basic-logging-dashboard.png",
    ),
    # wrong-depth refs (getting-started era)
    ("![](../images/vorteile250.png)", "![](../../images/vorteile250.png)"),
    (
        "../security/data-protection.md#entry-control",
        "../../security/data-protection.md#entry-control",
    ),
    (
        "../infrastructure/networking/connecting.md#connecting",
        "../networking/connecting.md#connecting",
    ),
    (
        "../platform/users/index.md#useraccounts",
        "../../platform/users/index.md#useraccounts",
    ),
    (
        "../platform/deployment/index.md#application-deployment",
        "../../platform/deployment/index.md#application-deployment",
    ),
    (
        "../infrastructure/networking/index.md#networking",
        "../networking/index.md#networking",
    ),
    (
        "../../getting-started/index.md#firststeps",
        "../../infrastructure/getting-started/index.md#firststeps",
    ),
    ("../reference/users/index.md", "../platform/users/index.md"),
    # pre-rename infrastructure targets (storage.md -> block-storage.md);
    # the longer performance anchor must run before its shorter prefix
    (
        "../../infrastructure/storage.md#infrastructure-storage-performance",
        "../../infrastructure/block-storage.md#infrastructure-storage-performance",
    ),
    (
        "../infrastructure/storage.md#infrastructure-storage",
        "../infrastructure/block-storage.md#infrastructure-storage",
    ),
    # mangled Sphinx/RST remnants
    (
        "`current NixOS platform documentation <nixos-platform-index>`",
        "current NixOS platform documentation",
    ),
    (
        "See <project:../../infrastructure/backup.md> for possible values.",
        "See [the backup documentation](../../infrastructure/backup.md) for possible values.",
    ),
    ("`documentation <nixos-slurm>`", "documentation"),
    (
        "`documentation on upgrades and changes <nixos-upgrade>`",
        "documentation on upgrades and changes",
    ),
    ("`document <nixos-docker-storage-driver>`", "document"),
    ("`document <nixos-opensearch>`", "document"),
]

# Path-dependent pairs: the SAME dead URL needs different replacements
# per source location (components/lamp.md links its same-dir
# webgateway.md, platform/deployment/lamp.md needs ../../components/).
# Keys are page ids relative to the snapshot root; these run BEFORE the
# global FIXES.
FILE_FIXES: dict[str, list[tuple[str, str]]] = {
    "components/lamp.md": [
        (
            "behind a [webgateway](../../platform-releases/fc-26.05-production/webgateway.md#nixos-webgateway)",
            "behind a [webgateway](webgateway.md#nixos-webgateway)",
        ),
        (
            "behind a [webgateway](../../platform-releases/fc-25.11-production/webgateway.md#nixos-webgateway)",
            "behind a [webgateway](webgateway.md#nixos-webgateway)",
        ),
    ],
    "platform/deployment/lamp.md": [
        (
            "behind a [webgateway](../../platform-releases/fc-26.05-production/webgateway.md#nixos-webgateway)",
            "behind a [webgateway](../../components/webgateway.md#nixos-webgateway)",
        ),
        (
            "behind a [webgateway](../../platform-releases/fc-25.11-production/webgateway.md#nixos-webgateway)",
            "behind a [webgateway](../../components/webgateway.md#nixos-webgateway)",
        ),
        # slimming relocation (see below): the dropped infrastructure/
        # subtree -- one ../ higher, into the main manual.
        (
            "[SRV interface](../../infrastructure/networking/networking.md#logical-networks)",
            "[SRV interface]"
            "(../../../infrastructure/networking/networking.md#logical-networks)",
        ),
    ],
    # same dead ferretdb URL as the global pair, but this page sits in
    # platform/deployment/ and must cross into ../../components/
    "platform/deployment/mongodb.md": [
        (
            "[FerretDB role](../../platform-releases/fc-25.11-production/ferretdb.md#nixos-ferretdb)",
            "[FerretDB role](../../components/ferretdb.md#nixos-ferretdb)",
        ),
    ],
    # platform/ pages link their same-dir local.md; the components/
    # occurrences of the same URL need ../platform/ (global FIXES)
    "platform/monitoring.md": [
        (
            "../../platform-releases/fc-26.05-production/local.md#nixos-local",
            "local.md#nixos-local",
        ),
        (
            "../../platform-releases/fc-25.11-production/local.md#nixos-local",
            "local.md#nixos-local",
        ),
    ],
    "platform/systemd.md": [
        (
            "../../platform-releases/fc-26.05-production/local.md#nixos-local",
            "local.md#nixos-local",
        ),
        (
            "../../platform-releases/fc-25.11-production/local.md#nixos-local",
            "local.md#nixos-local",
        ),
    ],
    # anchor backfill: security/data-protection.md links
    # platform/users/index.md#permissions, but that section only exists
    # from the branch mdBook-link fixes onward. The old string is the
    # pre-fix shape (components heading directly followed by the
    # [nixos] link definition), so the section is injected ONLY where
    # missing -- fixed-branch content is left untouched.
    "platform/users/index.md": [
        (
            "## Specific software components (roles) { #nixos-components }\n"
            "\n"
            "\n"
            "[nixos]: https://nixos.org",
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
            "[nixos]: https://nixos.org",
        ),
    ],
    # slimming relocations: the 26.05/25.11 branches dropped their
    # unversioned subtrees (changes/, infrastructure/, security/,
    # support/ and the root index.md) -- cross-references from the
    # surviving platform/ pages move one ../ higher into the main
    # manual or, where the anchor only exists in the snapshot, onto
    # the surviving in-tree page. Branch tips carry the fix at source,
    # leaving these pairs inert there; they stay alive for placements
    # from pre-backport revs (rollback contract, see
    # test_rollback_coverage).
    # types.md carries the mangled Sphinx/RST remnant in pre-backport
    # revs: this pair consumes it BEFORE the global remnant pair
    # (FILE_FIXES run first) and emits the corrected main-manual depth
    # directly.
    "platform/api/types.md": [
        (
            "See <project:../../infrastructure/backup.md> for possible values.",
            "See [the backup documentation]"
            "(../../../infrastructure/backup.md) for possible values.",
        ),
    ],
    "platform/logging.md": [
        (
            "[managed components](../index.md#nixos-components)",
            "[managed components](users/index.md#nixos-components)",
        ),
    ],
    "platform/philosophy.md": [
        (
            "[documenting our approach closely](../security/index.md)",
            "[documenting our approach closely](../../security/index.md)",
        ),
    ],
}

# Old fetch-era sunsetting banner (dead platform-releases link inside):
# a bare '!!! warning' line followed by the indented one-liner.
OLD_BANNER_RE = re.compile(
    r"!!! warning\n    This is a sunsetting version[^\n]*\n\n?"
)


def fix_text(text: str) -> tuple[str, int]:
    """Apply all global fixes to one page; return (new_text, fix_count)."""
    count = 0
    for old, new in FIXES:
        if old in text:
            text = text.replace(old, new)
            count += 1
    text, banners = OLD_BANNER_RE.subn("", text)
    return text, count + banners


def fix_page(page_id: str, text: str) -> tuple[str, int]:
    """Apply file-scoped pairs (first), then :func:`fix_text`.

    File-scoped pairs must run first: their old strings would otherwise
    be consumed by an overlapping global pair with the wrong target.
    """
    count = 0
    for old, new in FILE_FIXES.get(page_id, []):
        if old in text:
            text = text.replace(old, new)
            count += 1
    fixed, global_count = fix_text(text)
    return fixed, count + global_count


def fix_tree(tree: Path) -> int:
    """Fix every ``*.md`` below *tree* in place; return pages changed."""
    changed = 0
    for page in sorted(tree.rglob("*.md")):
        page_id = page.relative_to(tree).as_posix()
        original = page.read_text(encoding="utf-8")
        fixed, count = fix_page(page_id, original)
        if count:
            page.write_text(fixed, encoding="utf-8")
            changed += 1
    return changed
