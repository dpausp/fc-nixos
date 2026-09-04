"""E2E demo 1: release_notes in git mode against the REAL fc-nixos mirror.

``--repo /doc/.fetch-cache/fc-nixos``, RELEASE ``2026_033``, publish
date ``2026-08-17`` (the actual r033 release): the generated page must
match the committed gold ``doc/src/changes/2026/r033.md`` byte-for-byte
in the split acceptance -- (a) frontmatter+heading, (b) the platform
section incl. fragment bullets + the 26 generated package entries,
(c) the Detailed Changes line -- after stripping the one line
``tools.gen_changes_index`` owns (the archive link).

The ONE documented divergence: the committed gold carries the release
manager's hand edits on top of the generated skeleton (the changelog
says ``imporive``, the reviewed page says ``improve`` -- and an extra
Impact bullet the changelog never had, outside the split). This test
pins that divergence to EXACTLY the known typo fix via difflib --
anything else drifting fails loudly.

Skips loudly when the mirror is missing or the metadata API (channel
URL) is unreachable -- both are prerequisites of byte-identity.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest
from pytest_readable import readable
from tools import gen_changes_index as gci
from tools import release_notes as rn
from tools.vcs_backend import VcsError

DOC_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = DOC_ROOT.parent

# The persistent git mirror the /doc fetch pipeline maintains
# (blob-less partial clone; the blobs this test needs are cached).
MIRROR = Path("/doc/.fetch-cache/fc-nixos")

RELEASE = "2026_033"
PUBLISH_DATE = "2026-08-17"
BRANCH = "fc-26.05-production"

GOLD = DOC_ROOT / "src" / "changes" / "2026" / "r033.md"

# The release manager's typo fix in the reviewed gold page: the branch
# changelog (mirror tip AND the r033 collect commit) says "imporve".
TYPO_GOLD = (
    "- improve early boot logging for physical and virtual machines (PL-135546)"
)
TYPO_CHANGELOG = (
    "- imporve early boot logging for physical and virtual machines (PL-135546)"
)


def strip_archive_line(text: str) -> str:
    """Drop the gen_changes_index-owned line (+ its blank) from *text*."""
    return text.replace(f"{gci.ARCHIVE_LINE}\n\n", "")


def split_page(text: str) -> tuple[str, str, str]:
    """(a) frontmatter+heading, (b) platform section, (c) detailed line."""
    heading = f"# Release {RELEASE} ({PUBLISH_DATE})\n"
    part_a = text[: text.index(heading) + len(heading)]
    plat = text.index("## NixOS 26.05 platform")
    det = text.index("## Detailed Changes")
    part_b = text[plat:det].rstrip("\n")
    part_c = next(
        line for line in text.splitlines() if line.startswith("- NixOS 26.05:")
    )
    return part_a, part_b, part_c


def package_entries(part_b: str) -> list[str]:
    return [line for line in part_b.splitlines() if line.startswith("    - ")]


@pytest.fixture
def generated(tmp_path: Path) -> str:
    """The r033 page rendered from the real mirror (or a loud skip)."""
    if not (MIRROR / ".git").exists():
        pytest.skip(f"fc-nixos git mirror missing: {MIRROR}")
    channel_url = rn.fetch_channel_url(BRANCH, RELEASE)
    if channel_url is None:
        pytest.skip(
            "release metadata API unreachable -- the channel URL is part "
            "of the byte-identity contract (network required)"
        )
    text = ""
    try:
        text = rn.run_release_notes(
            DOC_ROOT / "platform-versions.toml",
            MIRROR,
            RELEASE,
            PUBLISH_DATE,
            out=tmp_path / "src",
            channel_url_fn=lambda branch, release: channel_url,
        )
    except VcsError as exc:
        pytest.skip(f"mirror unusable (partial clone without network?): {exc}")
    return text


@readable(
    intention="r033 im git-Modus gegen den echten Mirror: (a)/(b)/(c) "
    "byte-identisch zum Gold nach Archiv-Zeilen-Strip",
    steps=[
        "Mirror und Metadata-API praeflighten (sonst laut skippen)",
        "Seite gegen /doc/.fetch-cache/fc-nixos rendern",
        "Gold um die gen_changes_index-eigene Archiv-Zeile reduzieren",
        (
            "(a) Frontmatter+Heading, (b) Platform-Sektion, (c) Detailed-Zeile "
            "separat vergleichen"
        ),
    ],
    criteria=[
        "(a) und (c) byte-identisch",
        (
            "(b) bis auf DIE EINE dokumentierte Hand-Korrektur (Typo "
            "imporive->improve) byte-identisch"
        ),
        "Package-Diff: exakt die 26 Gold-Eintraege",
    ],
)
def test_r033_split_acceptance_byte_identical(generated: str) -> None:
    gold = strip_archive_line(GOLD.read_text(encoding="utf-8"))
    gen_a, gen_b, gen_c = split_page(generated)
    gold_a, gold_b, gold_c = split_page(gold)

    assert gen_a == gold_a
    assert gen_c == gold_c

    diff = sorted(
        line
        for line in difflib.unified_diff(
            gold_b.splitlines(), gen_b.splitlines(), lineterm=""
        )
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    )
    assert diff == sorted([f"-{TYPO_GOLD}", f"+{TYPO_CHANGELOG}"]), (
        "the platform section drifted beyond the ONE documented hand edit "
        "(the release manager's typo fix); every other byte must match"
    )

    gold_entries = package_entries(gold_b)
    gen_entries = package_entries(gen_b)
    assert len(gold_entries) == 26
    assert gen_entries == gold_entries


@readable(
    intention="Cross-Tool-Contract und CLI-Story der echten r033-Generierung",
    steps=[
        "generierte Seite durch gen_changes_index.parse_release_page jagen",
        "CLI-Hauptprogramm mit --repo Mirror ausfuehren",
        "Exit-Code und stderr-Log-Story pruefen",
    ],
    criteria=[
        "parse_release_page: date 2026-08-17, versions ['26.05']",
        "Exit 0, Seite geschrieben",
        (
            "stderr: backend=git, release-section-found, release-chain-derived, "
            "release-page-written; 25.11 geprueft und verworfen"
        ),
    ],
)
def test_r033_cross_tool_contract_and_cli_story(
    generated: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "cli-src"  # the `generated` fixture already used src/
    code = rn.main(
        [
            "--repo",
            str(MIRROR),
            str(DOC_ROOT / "platform-versions.toml"),
            RELEASE,
            "--publish-date",
            PUBLISH_DATE,
            "--out",
            str(out),
        ]
    )
    assert code == 0
    page = out / "changes" / "2026" / "r033.md"
    assert page.read_text(encoding="utf-8") == generated

    rel = gci.parse_release_page(page)
    assert rel.date == PUBLISH_DATE
    assert rel.versions == ["26.05"]
    assert rel.marker is None

    err = capsys.readouterr().err
    assert "vcs-backend-detected" in err and "backend=git" in err
    assert "release-section-found" in err
    assert "release-chain-derived" in err
    assert "release-page-written" in err
    assert "release-not-in-branch" in err  # 25.11 checked, does not carry r033
