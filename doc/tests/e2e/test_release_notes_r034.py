"""E2E demo 2: release_notes collect mode + gen_changes_index handover.

The REAL three ``changelog.d/*_scriv.md`` fragments of the upcoming
2026_034 release are copied into a sandbox (never touched in place):
collect + render produces the r034 skeleton -- exactly the 3 platform
bullets, NO empty Impact section (all fragments carry only the
placeholder), ``XX.XX`` baked to the TOML stable version, publish date
parameterizable (the CLI defaults to next Monday -- pinned offline).

Then ``tools.gen_changes_index.main`` runs against the sandbox tree
(the real r033 gold page copied in as the former latest): the r034 row
lands in the ``index.md`` table and the archive link moves to r034,
idempotently -- the real repository state is never modified (asserted
byte-identical before/after).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pytest_readable import readable
from tests.helpers import DOC_ROOT, REPO_ROOT
from tools import gen_changes_index as gci
from tools import release_notes as rn

RELEASE = "2026_034"
PUBLISH_DATE = "2026-08-24"  # the Monday after r033's 2026-08-17

# The real r034 fragment set, in changelog.d/ collection (filename) order.
EXPECTED_BULLETS = [
    (
        "- Fix a small with the Grafana frontend showing a basic auth form "
        "sometimes due to improper subpath handling in the frontend."
    ),
    (
        "- Fix an issue where object storage credentials were not passed to "
        "loki correctly. (PL-135488)"
    ),
    "- Add solr 9 and 10. (PL-133351)",
]


def platform_bullets(text: str) -> list[str]:
    """Top-level ``- `` bullet lines of the platform section."""
    body = text.split("## NixOS 26.05 platform\n\n", 1)[1]
    body = body.split("\n\n## ", 1)[0]
    return [line for line in body.splitlines() if line.startswith("- ")]


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """The real fragments + release metadata copied into a sandbox tree."""
    fragment_dir = REPO_ROOT / "changelog.d"
    fragments = sorted(fragment_dir.glob("*_scriv.md"))
    # This demo IS the r034 proof: exactly the three real fragments.
    assert len(fragments) == 3, (
        f"expected the three real r034 fragments in {fragment_dir}, "
        f"found {[f.name for f in fragments]}"
    )
    box = tmp_path / "sandbox"
    (box / "changelog.d").mkdir(parents=True)
    for fragment in fragments:
        shutil.copy2(fragment, box / "changelog.d" / fragment.name)
    (box / "release").mkdir()
    for name in ("package-versions.json", "important_packages.json"):
        shutil.copy2(REPO_ROOT / "release" / name, box / "release" / name)
    return box


@readable(
    intention="r034-Skelett aus den 3 echten Fragmenten: genau 3 Platform-"
    "Bullets, keine Leer-Impact-Sektion, XX.XX auf 26.05 gebacken",
    steps=[
        "die 3 echten Fragmente nach changelog.d/ der Sandbox kopieren",
        "collect+render fuer 2026_034 mit fixem Publish-Date",
        "Sektionen und Bullets der Seite pruefen",
    ],
    criteria=[
        "'## NixOS 26.05 platform' mit genau den 3 erwarteten Bullets",
        "keine Impact-Sektion, keine Detailed-Sektion, kein Pull-Block",
        "kein XX.XX mehr in der Seite",
    ],
)
def test_r034_skeleton_from_real_fragments(
    sandbox: Path, tmp_path: Path
) -> None:
    text = rn.run_release_notes(
        DOC_ROOT / "platform-versions.toml",
        sandbox,
        RELEASE,
        PUBLISH_DATE,
        out=tmp_path / "src",
    )
    assert text.startswith(
        f"---\nPublish Date: '{PUBLISH_DATE}'\n---\n\n\n"
        f"# Release {RELEASE} ({PUBLISH_DATE})\n\n"
    )
    assert "XX.XX" not in text
    assert "## Impact" not in text
    assert "## Detailed Changes" not in text
    assert "Pull upstream" not in text
    assert platform_bullets(text) == EXPECTED_BULLETS
    rel = gci.parse_release_page(
        tmp_path / "src" / "changes" / "2026" / "r034.md"
    )
    assert (rel.date, rel.versions) == (PUBLISH_DATE, ["26.05"])


@readable(
    intention="gen_changes_index-Uebergabe auf dem Sandbox-Baum: r034-Zeile "
    "in der Index-Tabelle, Archiv-Link wandert idempotent auf r034",
    steps=[
        (
            "echte r033-Gold-Seite als bisherige Latest in den Sandbox-Baum "
            "kopieren"
        ),
        "gen_changes_index.main --src sandbox ausfuehren",
        "Index-Tabelle, Archiv-Link und Idempotenz pruefen",
        (
            "Echtzustand (Fragmente, CHANGELOG, echte Pages) byte-identisch "
            "halten"
        ),
    ],
    criteria=[
        "Exit 0, r034-Zeile '| [2026_034](2026/r034.md) | 2026-08-24 | 26.05 |'",
        "Archiv-Zeile unter dem r034-H1, r033 unangetastet",
        "zweiter Lauf byte-identisch",
        "keine echte Datei veraendert",
    ],
)
def test_r034_gen_changes_index_handover(
    sandbox: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "src"
    # skeleton first (collect mode writes into the sandbox src tree)
    rn.run_release_notes(
        DOC_ROOT / "platform-versions.toml",
        sandbox,
        RELEASE,
        PUBLISH_DATE,
        out=src,
    )
    # the real r033 gold page (WITH its archive line) is the former latest
    gold_r033 = (DOC_ROOT / "src" / "changes" / "2026" / "r033.md").read_text(
        encoding="utf-8"
    )
    (src / "changes" / "2026" / "r033.md").write_text(
        gold_r033, encoding="utf-8"
    )

    r034 = src / "changes" / "2026" / "r034.md"
    r033 = src / "changes" / "2026" / "r033.md"

    before_fragments = {
        f.name: f.read_text(encoding="utf-8")
        for f in sorted((REPO_ROOT / "changelog.d").glob("*"))
    }
    before_real_index = (DOC_ROOT / "src" / "changes" / "index.md").read_text(
        encoding="utf-8"
    )

    assert gci.main(["--src", str(src)]) == 0

    index = (src / "changes" / "index.md").read_text(encoding="utf-8")
    assert "| [2026_034](2026/r034.md) | 2026-08-24 | 26.05 |" in index
    assert (
        f"# Release {RELEASE} ({PUBLISH_DATE})\n\n{gci.ARCHIVE_LINE}"
        in r034.read_text(encoding="utf-8")
    )
    assert r033.read_text(encoding="utf-8") == gold_r033
    err = capsys.readouterr().err
    assert "index-written" in err
    assert "archive-link-placed" in err and "r034" in err

    # idempotent: the archive link never moves twice
    page_once = r034.read_text(encoding="utf-8")
    index_once = index
    assert gci.main(["--src", str(src)]) == 0
    assert r034.read_text(encoding="utf-8") == page_once
    assert (src / "changes" / "index.md").read_text(encoding="utf-8") == (
        index_once
    )
    err = capsys.readouterr().err
    assert "archive-link-present" in err

    # no real state changed: fragments, CHANGELOG, real pages untouched
    after_fragments = {
        f.name: f.read_text(encoding="utf-8")
        for f in sorted((REPO_ROOT / "changelog.d").glob("*"))
    }
    assert after_fragments == before_fragments
    assert (DOC_ROOT / "src" / "changes" / "index.md").read_text(
        encoding="utf-8"
    ) == before_real_index
    assert (DOC_ROOT / "src" / "changes" / "2026" / "r033.md").read_text(
        encoding="utf-8"
    ) == gold_r033
