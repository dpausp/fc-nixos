"""Executable spec for ``tools/scaffold_page.py`` (generate + remove).

Two modes over the same two artifacts -- the markdown page under
``src/components/`` and the hand-maintained explicit navigation in
``zensical.toml``:

- GENERATE creates ``src/components/<name>.md`` as a house-convention
  stub (H1 with ``{ #nixos-<name> }`` anchor, TODO intro, ``nix``
  fence with the role option, ``sudo fc-manage switch`` hint) and
  inserts the nav entry ALPHABETICALLY into the chosen ``Components``
  group. The nav edit is TEXTUAL TOML SURGERY -- never a tomllib
  roundtrip (which would destroy formatting and comments): the file
  must still parse with tomllib afterwards and keep the exact house
  indentation of its sibling entries, including the compressed
  ``} ] },`` group-ending lines that an append has to split;

- REMOVE replaces a component page with a generic tombstone (H1 +
  anchor stay, warning admonition, generic switcher hint -- NO
  frontmatter/search-exclude so the page stays searchable and the
  client-side version switcher keeps offering it) and marks the nav
  label ``<Label> (removed)`` IN PLACE. The integration test pins the
  pay-off: a tombstoned master page whose snapshot still carries the
  real content keeps its ``pages`` entry in the switcher payload
  (``tools.gen_platform_versions`` is content-agnostic on purpose and
  stays untouched).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import tomllib
from structlog.testing import capture_logs
from tools import gen_platform_versions as gpv
from tools import scaffold_page as sp

# The mini nav mirrors the real zensical.toml layout: nav inside
# [project], Components section at indent 2, groups at indent 6,
# entries at indent 10, each group's LAST entry compressed to
# `} ] },`.
MINI_ZENSICAL = """\
[project]
site_name = "Mini"
docs_dir = "src"

nav = [
  { "Changelog" = [ "changes/index.md" ] },
  { "Components" = [
      { "Databases" = [
          { "FerretDB" = "components/ferretdb.md" },
          { "MariaDB" = "components/mariadb.md" },
          { "MongoDB" = "components/mongodb.md" },
          { "MySQL" = "components/mysql.md" },
          { "PostgreSQL" = "components/postgresql.md" } ] },
      { "Web Serving" = [
          { "LAMP (Apache/php-fpm)" = "components/lamp.md" },
          { "Webgateway (NGINX, HAProxy)" = \
"components/webgateway.md" } ] }
  ] }
]
"""

DATABASES = (
    "ferretdb",
    "mariadb",
    "mongodb",
    "mysql",
    "postgresql",
)

MYSQL_PAGE = textwrap.dedent(
    """\
    # MySQL { #nixos-mysql }

    This component sets up a managed instance of the MySQL database
    server.

    ## Configuration

    Run `sudo fc-manage switch` to activate configuration changes.
    """
)


def write_mini_doc(root: Path, nav: str = MINI_ZENSICAL) -> Path:
    """A doc root: mini zensical.toml + the component pages it lists."""
    (root / "src" / "components").mkdir(parents=True)
    for name in (*DATABASES, "lamp", "webgateway"):
        page = MYSQL_PAGE if name == "mysql" else f"# {name}\n"
        (root / "src" / "components" / f"{name}.md").write_text(page)
    (root / "src" / "changes").mkdir()
    (root / "src" / "changes" / "index.md").write_text("# changelog\n")
    (root / "zensical.toml").write_text(nav)
    return root


@pytest.fixture
def mini_doc(tmp_path: Path) -> Path:
    return write_mini_doc(tmp_path / "doc")


def components_section(nav: list) -> list:
    """The value of the ``Components`` key of the parsed nav."""
    for item in nav:
        if isinstance(item, dict):
            section = item.get("Components")
            if isinstance(section, list):
                return section
    raise AssertionError("no Components section in nav")


def group_labels(section: list, group: str) -> list[str]:
    """Labels of ``group``'s entries, in nav order.

    A group parses to an array of one-key inline tables:
    ``[{"FerretDB": "..."}, ...]``.
    """
    for item in section:
        if isinstance(item, dict):
            entries = item.get(group)
            if isinstance(entries, list):
                return [
                    str(next(iter(entry)))
                    for entry in entries
                    if isinstance(entry, dict) and len(entry) == 1
                ]
    raise AssertionError(f"no {group!r} group in Components nav")


def parsed_nav(root: Path) -> list:
    return tomllib.loads((root / "zensical.toml").read_text())["project"]["nav"]


# ---------------------------------------------------------------------------
# generate: stub + nav insertion
# ---------------------------------------------------------------------------


def test_generate_stub_anatomy(mini_doc: Path) -> None:
    """Stub follows house conventions: anchor, TODO intro, nix fence."""
    sp.scaffold("somedb", None, "Databases", mini_doc)

    page = mini_doc / "src" / "components" / "somedb.md"
    text = page.read_text()
    lines = text.splitlines()
    assert lines[0] == "# Somedb { #nixos-somedb }"
    assert "TODO:" in text
    assert "```nix" in text
    assert "flyingcircus.roles.somedb.enable = true;" in text
    assert "sudo fc-manage switch" in text


def test_generate_nav_insert_sorted_in_middle(mini_doc: Path) -> None:
    """New entry lands at its alphabetical position with house indent."""
    with capture_logs() as logs:
        sp.scaffold("mongodb-lite", "MongoDB Lite", "Databases", mini_doc)

    nav = (mini_doc / "zensical.toml").read_text()
    section = components_section(parsed_nav(mini_doc))
    assert group_labels(section, "Databases") == [
        "FerretDB",
        "MariaDB",
        "MongoDB",
        "MongoDB Lite",
        "MySQL",
        "PostgreSQL",
    ]
    # exact house indentation: 10 spaces like the sibling entries
    assert (
        '\n          { "MongoDB Lite" = "components/mongodb-lite.md" },\n'
        in nav
    )
    assert any(
        e["event"] == "page-scaffolded"
        and e["name"] == "mongodb-lite"
        and e["group"] == "Databases"
        for e in logs
    )
    assert any(
        e["event"] == "nav-entry-inserted" and e["label"] == "MongoDB Lite"
        for e in logs
    )


def test_generate_nav_insert_at_group_end_splits_compressed_line(
    mini_doc: Path,
) -> None:
    """Appending after the last entry splits the ``} ] },`` line."""
    sp.scaffold("sqlite", None, "Databases", mini_doc)

    nav = (mini_doc / "zensical.toml").read_text()
    section = components_section(parsed_nav(mini_doc))
    assert group_labels(section, "Databases")[-2:] == [
        "PostgreSQL",
        "Sqlite",
    ]
    # the compressed PostgreSQL line was split: plain entry line ...
    assert '\n          { "PostgreSQL" = "components/postgresql.md" },\n' in nav
    # ... and a NEW compressed group ending carrying the new entry
    assert '\n          { "Sqlite" = "components/sqlite.md" } ] },\n' in nav
    assert parsed_nav(mini_doc)  # tomllib still parses the whole file


def test_generate_unknown_group_fails_with_group_list(
    mini_doc: Path,
) -> None:
    """Unknown group fails loudly, naming the available groups."""
    with pytest.raises(sp.ScaffoldError, match="NoSQL"):
        sp.scaffold("somedb", None, "NoSQL", mini_doc)

    try:
        sp.scaffold("somedb", None, "NoSQL", mini_doc)
    except sp.ScaffoldError as exc:
        assert "Databases" in str(exc)
        assert "Web Serving" in str(exc)
    assert not (mini_doc / "src" / "components" / "somedb.md").exists()


def test_generate_twice_fails(mini_doc: Path) -> None:
    """A second run over the same name fails loudly."""
    sp.scaffold("sqlite", None, "Databases", mini_doc)

    with pytest.raises(sp.ScaffoldError, match="exists already"):
        sp.scaffold("sqlite", "Sqlite", "Databases", mini_doc)

    section = components_section(parsed_nav(mini_doc))
    assert group_labels(section, "Databases").count("Sqlite") == 1


def test_generate_title_defaults_to_capitalized_slug(
    mini_doc: Path,
) -> None:
    """No title: nav label and H1 use the capitalized slug."""
    sp.scaffold("somedb", None, "Databases", mini_doc)

    section = components_section(parsed_nav(mini_doc))
    assert group_labels(section, "Databases")[-1] == "Somedb"
    first_line = (
        (mini_doc / "src" / "components" / "somedb.md")
        .read_text()
        .splitlines()[0]
    )
    assert first_line == "# Somedb { #nixos-somedb }"


def test_generate_rejects_invalid_slug(mini_doc: Path) -> None:
    """Slugs outside [a-z0-9-] never touch the filesystem."""
    with pytest.raises(sp.ScaffoldError, match="slug"):
        sp.scaffold("Bad_Name", None, "Databases", mini_doc)


# ---------------------------------------------------------------------------
# remove: tombstone + (removed) nav marker
# ---------------------------------------------------------------------------


def test_remove_tombstone_anatomy(mini_doc: Path) -> None:
    """Tombstone keeps H1+anchor, warns generically, stays searchable."""
    with capture_logs() as logs:
        sp.remove_page("mysql", mini_doc)

    text = (mini_doc / "src" / "components" / "mysql.md").read_text()
    assert text.splitlines()[0] == "# MySQL { #nixos-mysql }"
    assert '!!! warning "Component removed"' in text
    assert "no longer part of the current platform version" in text
    assert "version switcher" in text
    # NO frontmatter / search-exclude: the page must stay searchable
    # and switchable
    assert "---" not in text
    assert "search:" not in text
    # generic hint: no hardcoded platform versions
    import re

    assert not re.search(r"\d{2}\.\d{2}", text)
    assert any(
        e["event"] == "page-removed" and e["name"] == "mysql" for e in logs
    )


def test_remove_marks_nav_label_removed_in_place(mini_doc: Path) -> None:
    """Nav label gets the (removed) marker at its existing position."""
    sp.remove_page("mysql", mini_doc)

    section = components_section(parsed_nav(mini_doc))
    labels = group_labels(section, "Databases")
    assert labels == [
        "FerretDB",
        "MariaDB",
        "MongoDB",
        "MySQL (removed)",
        "PostgreSQL",
    ]
    assert labels.index("MySQL (removed)") == 3
    for item in section:
        if isinstance(item, dict):
            entries = item.get("Databases")
            if isinstance(entries, list):
                marked = [
                    e
                    for e in entries
                    if isinstance(e, dict) and "MySQL (removed)" in e
                ]
                assert marked == [{"MySQL (removed)": "components/mysql.md"}]


def test_remove_twice_fails(mini_doc: Path) -> None:
    """A second sunset of the same page fails loudly."""
    sp.remove_page("mysql", mini_doc)

    with pytest.raises(sp.ScaffoldError, match="tombstone already"):
        sp.remove_page("mysql", mini_doc)


def test_remove_unknown_page_fails(mini_doc: Path) -> None:
    with pytest.raises(sp.ScaffoldError, match="no such component page"):
        sp.remove_page("nosuchdb", mini_doc)


def test_remove_missing_nav_entry_fails(tmp_path: Path) -> None:
    """A page without a Components nav entry cannot be removed."""
    nav = MINI_ZENSICAL.replace(
        '          { "MySQL" = "components/mysql.md" },\n', ""
    )
    root = write_mini_doc(tmp_path / "doc", nav=nav)

    with pytest.raises(sp.ScaffoldError, match="no nav entry"):
        sp.remove_page("mysql", root)


def test_remove_german_twin_fails_loudly(mini_doc: Path) -> None:
    """A German twin blocks the removal with a remediation hint."""
    twin = mini_doc / "src" / "de" / "components" / "mysql.md"
    twin.parent.mkdir(parents=True)
    twin.write_text("# MySQL (de)\n")

    with pytest.raises(sp.ScaffoldError) as excinfo:
        sp.remove_page("mysql", mini_doc)
    assert "de/components/mysql.md" in str(excinfo.value)
    # the EN page must be untouched when the tool refuses
    assert (
        "managed instance"
        in (mini_doc / "src" / "components" / "mysql.md").read_text()
    )


# ---------------------------------------------------------------------------
# integration: sunset keeps the page switchable (payload unchanged)
# ---------------------------------------------------------------------------

VERSIONS_TOML = """\
[stable]
ver = "26.05"
rev = "fc-26.05-production"

[[sunsetting]]
ver = "25.11"
rev = "fc-25.11-production"
"""


def test_remove_keeps_page_switchable_in_payload(
    tmp_path: Path,
) -> None:
    """Tombstone in the master + real page in the snapshot = switchable.

    The payload scan is file-existence based: removal (replacing
    content, keeping the file) keeps ``components/mysql`` carried by
    the 25.11 snapshot -- exactly what the version switcher needs to
    keep offering the page. gen_platform_versions stays untouched.
    """
    root = write_mini_doc(tmp_path / "doc")
    (root / "platform-versions.toml").write_text(VERSIONS_TOML)
    snapshot = root / "src" / "25.11" / "components"
    snapshot.mkdir(parents=True)
    (snapshot / "mysql.md").write_text(MYSQL_PAGE)

    sp.remove_page("mysql", root)

    versions = gpv.load_versions(root / "platform-versions.toml")
    payload = gpv.build_payload(versions, versions.stable, root / "src")
    assert payload["pages"]["components/mysql"] == ["25.11"]
    # the snapshot content is untouched -- only the master page changed
    assert "managed instance" in (snapshot / "mysql.md").read_text()


# ---------------------------------------------------------------------------
# CLI facade
# ---------------------------------------------------------------------------


def test_main_generates_page(
    mini_doc: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """:meth:`main` generates via argparse, logging to stderr."""
    code = sp.main(
        [
            "--group",
            "Databases",
            "mongodb-lite",
            "--title",
            "MongoDB Lite",
            "--doc-root",
            str(mini_doc),
        ]
    )

    assert code == 0
    assert (mini_doc / "src" / "components" / "mongodb-lite.md").exists()
    err = capsys.readouterr().err
    assert "page-scaffolded" in err
    assert "nav-entry-inserted" in err


def test_main_remove(
    mini_doc: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """:meth:`main --remove` tombstones and marks the nav label."""
    code = sp.main(["--remove", "mysql", "--doc-root", str(mini_doc)])

    assert code == 0
    text = (mini_doc / "src" / "components" / "mysql.md").read_text()
    assert "no longer part of the current platform version" in text
    section = components_section(parsed_nav(mini_doc))
    assert "MySQL (removed)" in group_labels(section, "Databases")
    err = capsys.readouterr().err
    assert "page-removed" in err
    assert "nav-marked-removed" in err


def test_main_requires_group_without_remove(
    mini_doc: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Generate mode without --group is a usage error (exit 2)."""
    with pytest.raises(SystemExit) as excinfo:
        sp.main(["somedb", "--doc-root", str(mini_doc)])

    assert excinfo.value.code == 2
    assert "--group" in capsys.readouterr().err


def test_main_failure_returns_one(
    mini_doc: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ScaffoldError maps to exit 1 with the reason on stderr."""
    code = sp.main(["--group", "NoSQL", "somedb", "--doc-root", str(mini_doc)])

    assert code == 1
    err = capsys.readouterr().err
    assert "scaffold-page-failed" in err
    assert "NoSQL" in err
