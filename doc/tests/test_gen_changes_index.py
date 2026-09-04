"""Executable spec for ``tools/gen_changes_index.py``.

The generator turns the release tree ``src/changes/<year>/rNNN.md``
into the committed changelog archive ``src/changes/index.md`` and
places the archive link on the latest release page. Properties that
pin the design:

- ``parse_release_page`` extracts the ``Publish Date`` frontmatter
  date, the unique ``## NixOS NN.NN platform`` versions (descending)
  and the markers ``cancelled`` (H1 suffix) / ``never rolled out``
  (body phrase); marker pages legitimately lack date/versions;
- ``render_index`` produces per-year tables (``Release | Date |
  Versions``), years descending, releases descending within a year,
  duplicate versions collapsed, marker rows as italic annotations;
- ``main`` writes ``changes/index.md`` and idempotently places the
  archive link directly under the H1 of the CURRENT latest release
  page -- a former latest page (pre-existing link) stays
  byte-identical, nothing is ever removed;
- a non-marker page lacking date or versions fails the run LOUDLY:
  exit 1 naming every broken page;
- the CLI ``python -m tools.gen_changes_index --src <root>`` works
  end-to-end from ``doc/``.

All tests run against fixture trees ONLY -- never against the real
``doc/src`` tree.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pytest_readable import readable
from tools import gen_changes_index as gci

DOC = Path(__file__).resolve().parents[1]

PAGE_TMPL = """---
Publish Date: '{date}'
---

# Release {label} ({date})

## Impact

### 25.11

- impact note

## NixOS {v1} platform

- change a

## NixOS {v2} platform

- change b
"""


def build_tree(src: Path) -> None:
    """Minimal release tree: 2 years, 4+1 releases incl. both markers.

    2026/r003 carries a pre-existing archive line (former latest).
    """
    ch = src / "changes"
    (ch / "2025").mkdir(parents=True)
    (ch / "2026").mkdir()
    (ch / "2025" / "r001.md").write_text(
        PAGE_TMPL.format(
            date="2025-01-06", label="2025_001", v1="23.11", v2="24.05"
        )
    )
    (ch / "2026" / "r001.md").write_text(
        PAGE_TMPL.format(
            date="2026-01-13", label="2026_001", v1="25.11", v2="25.11"
        )
    )
    (ch / "2026" / "r002.md").write_text(
        "# Release 2026_002 (cancelled)\n\n"
        "This release was cancelled and was merged with release"
        " [2026_003](./r003.md).\n"
    )
    (ch / "2026" / "r003.md").write_text(
        "---\n"
        "Publish Date: '2026-01-27'\n"
        "---\n\n"
        "# Release 2026_003 (2026-01-27)\n\n"
        "***This release was never rolled out to production due to a"
        " regression.*** Changes land in 2026_004.\n\n"
        "*All releases: [changelog archive](../index.md).*\n"
    )
    (ch / "2026" / "r004.md").write_text(
        PAGE_TMPL.format(
            date="2026-02-02", label="2026_004", v1="25.11", v2="26.05"
        )
    )


@readable(
    intention="parse_release_page liefert Datum, eindeutige absteigende "
    "Versionen und Marker",
    steps=[
        "Fixture-Baum bauen",
        "Seiten mit Frontmatter/platform-Sektionen parsen",
        "Marker-Seiten parsen",
    ],
    criteria=[
        "date/year/num korrekt",
        "versions unique + absteigend",
        "marker cancelled / never rolled out",
    ],
)
def test_parse_release_page_extracts_date_versions_marker(tmp_path):
    src = tmp_path / "src"
    build_tree(src)
    rel = gci.parse_release_page(src / "changes" / "2026" / "r004.md")
    assert (rel.year, rel.num, rel.date) == ("2026", 4, "2026-02-02")
    assert rel.versions == ["26.05", "25.11"]
    assert rel.marker is None
    assert (
        gci.parse_release_page(src / "changes" / "2026" / "r002.md").marker
        == "cancelled"
    )
    assert (
        gci.parse_release_page(src / "changes" / "2026" / "r003.md").marker
        == "never rolled out"
    )


@readable(
    intention="render_index produziert Tabellen je Jahr, Jahre und "
    "Releases absteigend, Marker-Zeilen",
    steps=[
        "Fixture-Baum rendern",
        "Struktur- und Zeilen-Assertions gegen das Markdown",
    ],
    criteria=[
        "Titelzeile '# Changelog { #changelog }'",
        "## 2026 vor ## 2025, Releases absteigend je Jahr",
        "Header/Modifier-Zeile '| Release | Date | Versions |'",
        "exakte Zeilen inkl. Marker und Unique-versionen",
    ],
)
def test_render_index_tables_desc(tmp_path):
    src = tmp_path / "src"
    build_tree(src)
    md = gci.render_index(src)
    assert md.splitlines()[0] == "# Changelog { #changelog }"
    assert md.index("## 2026") < md.index("## 2025")
    assert (
        md.index("[2026_004]")
        < md.index("[2026_003]")
        < md.index("[2026_002]")
        < md.index("[2026_001]")
        < md.index("## 2025")
    )
    assert "| Release | Date | Versions |" in md
    assert "| ------- | ---- | -------- |" in md
    assert "| [2026_004](2026/r004.md) | 2026-02-02 | 26.05, 25.11 |" in md
    assert (
        "| [2026_003](2026/r003.md) | 2026-01-27 | *(never rolled out)* |" in md
    )
    assert "| [2026_002](2026/r002.md) | — | *(cancelled)* |" in md
    assert "| [2026_001](2026/r001.md) | 2026-01-13 | 25.11 |" in md
    assert "| [2025_001](2025/r001.md) | 2025-01-06 | 24.05, 23.11 |" in md


@readable(
    intention="main setzt den Archiv-Link unter dem H1 der aktuellen "
    "Latest-Seite, idempotent, fruehere Latest-Seiten unangetastet",
    steps=[
        "main gegen Fixture ausfuehren",
        "Link-Zeile unter H1 pruefen",
        "fruehere Latest-Seite byte-identisch",
        "zweiter Lauf aendert nichts",
    ],
    criteria=[
        "Exit 0",
        "exakt eine Link-Zeile unter dem H1",
        "r003 unveraendert",
        "zweiter Lauf byte-identisch",
    ],
)
def test_latest_link_idempotent_and_former_latest_untouched(tmp_path):
    src = tmp_path / "src"
    build_tree(src)
    r004 = src / "changes" / "2026" / "r004.md"
    r003 = src / "changes" / "2026" / "r003.md"
    before003 = r003.read_text()

    assert gci.main(["--src", str(src)]) == 0
    assert (
        "# Release 2026_004 (2026-02-02)\n\n"
        "*All releases: [changelog archive](../index.md).*\n"
        in r004.read_text()
    )
    assert r003.read_text() == before003

    after_first_page = r004.read_text()
    after_first_index = (src / "changes" / "index.md").read_text()
    assert gci.main(["--src", str(src)]) == 0
    assert r004.read_text() == after_first_page
    assert (src / "changes" / "index.md").read_text() == after_first_index


@readable(
    intention="Nicht-Marker-Seite ohne Datum/Versionen scheitert laut mit "
    "Seitenliste und Exit 1",
    steps=[
        "kaputte Seite in Fixture legen",
        "main ausfuehren",
        "Exit-Code und Ausgabe pruefen",
    ],
    criteria=["Exit 1", "Seitenpfad 2025/r002.md in der Ausgabe"],
)
def test_loud_failure_names_broken_pages(tmp_path, capsys):
    src = tmp_path / "src"
    build_tree(src)
    (src / "changes" / "2025" / "r002.md").write_text(
        "# Release 2025_002 (2025-02-03)\n\n"
        "no frontmatter, no platform sections, no marker\n"
    )
    rc = gci.main(["--src", str(src)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "2025/r002.md" in captured.out + captured.err


@readable(
    intention="CLI python -m tools.gen_changes_index --src <root> "
    "funktioniert end-to-end",
    steps=["subprocess aus doc/ starten", "Exit-Code und index.md pruefen"],
    criteria=["Exit 0", "index.md beginnt mit '# Changelog { #changelog }'"],
)
def test_cli_end_to_end(tmp_path):
    src = tmp_path / "src"
    build_tree(src)
    proc = subprocess.run(
        [sys.executable, "-m", "tools.gen_changes_index", "--src", str(src)],
        cwd=DOC,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert (
        (src / "changes" / "index.md")
        .read_text()
        .startswith("# Changelog { #changelog }")
    )


@readable(
    intention="index.md führt den Intro-Absatz mit Reversed-chronological- "
    "und Sidebar-Hinweis vor den Jahrestabellen",
    steps=[
        "Fixture-Baum rendern",
        "Intro vor der ersten Jahresüberschrift ansiedeln",
        "Schlüsselwörter prüfen",
    ],
    criteria=[
        "'reverse chronological' im Intro",
        "'sidebar' im Intro",
        "Intro vor '## 2026'",
    ],
)
def test_index_intro_reverse_chronological_and_sidebar_hint(tmp_path):
    src = tmp_path / "src"
    build_tree(src)
    md = gci.render_index(src)
    intro_end = md.index("## 2026")
    intro = md[:intro_end]
    assert "reverse chronological" in intro
    assert "sidebar" in intro


@readable(
    intention="main loggt Schreib- und Link-Events; zweiter Lauf loggt "
    "unchanged/present und schreibt nichts",
    steps=[
        "ersten Lauf gegen Fixture ausführen und stderr prüfen",
        "zweiten Lauf ausführen und stderr prüfen",
    ],
    criteria=[
        "Erster Lauf: index-written + archive-link-placed + done",
        "Zweiter Lauf: index-unchanged + archive-link-present",
    ],
)
def test_main_logs_writes_and_idempotent_second_run(tmp_path, capsys):
    src = tmp_path / "src"
    build_tree(src)

    assert gci.main(["--src", str(src)]) == 0
    first = capsys.readouterr().err
    assert "index-written" in first
    assert "archive-link-placed" in first
    assert "gen-changes-index-done" in first

    assert gci.main(["--src", str(src)]) == 0
    second = capsys.readouterr().err
    assert "index-unchanged" in second
    assert "archive-link-present" in second


@readable(
    intention="fehlendes changes/-Verzeichnis scheitert laut mit Exit 1",
    steps=["main gegen leeres src ausführen", "Exit-Code und stderr prüfen"],
    criteria=["Exit 1", "changes-missing in stderr"],
)
def test_changes_dir_missing_fails_loudly(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    assert gci.main(["--src", str(src)]) == 1
    assert "changes-missing" in capsys.readouterr().err


@readable(
    intention="Fremddateien im changes/-Baum werden verwarnungsgemäß "
    "übersprungen, ohne den Archiv-Inhalt zu verschmutzen",
    steps=[
        "notes.md in Jahresverzeichnis ablegen",
        "main ausführen",
        "Exit-Code, stderr-Warnung und index.md prüfen",
    ],
    criteria=[
        "Exit 0",
        "page-skipped-Warnung nennt notes.md",
        "notes erscheint nicht in index.md",
    ],
)
def test_stray_files_are_skipped_with_warning(tmp_path, capsys):
    src = tmp_path / "src"
    build_tree(src)
    (src / "changes" / "2025" / "notes.md").write_text("# notes\n")
    assert gci.main(["--src", str(src)]) == 0
    err = capsys.readouterr().err
    assert "page-skipped" in err
    assert "2025/notes.md" in err
    assert "notes" not in (src / "changes" / "index.md").read_text()
