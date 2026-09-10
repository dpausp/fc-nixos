"""Permanent unit + integration tests for ``tools/release_notes``.

Covers the ported text pipeline (release splitting, section parsing,
golden-format rendering, next-Monday default), the NEW package diff
(filtering, alphabetical order, label = attr key, replacement of a
hand-written Pull-upstream block), the fragment collection (comment
stripping, placeholder dropping, section merging, XX.XX baking), the
compare-chain derivation and orchestration against real LOCAL offline
repos on both backends (hg bookmarks and git mirror branches), the
hg shamap limit (no faked platform-code compare link), the CLI flags,
and the cross-tool contract with ``tools.gen_changes_index``
(:func:`parse_release_page` accepts every rendered page).

Everything runs offline against tmp mini-repos -- never against the
real repository or the mirror.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest
from pytest_readable import readable
from structlog.testing import capture_logs
from tests.helpers import (
    TOML_NEW_DOCS as TOML,
    git,
    git_env,
    hg,
    versions_file,
)
from tools import gen_changes_index as gci
from tools import release_notes as rn
from tools.vcs_backend import GitBackend, HgBackend

CHANNEL_URL = "https://hydra.flyingcircus.io/build/1/download/1/nixexprs.tar.xz"

R003_CHANGELOG = (
    "# Release 2026_003\n\n## NixOS XX.XX platform\n\n- old bullet\n"
)
R004_CHANGELOG = (
    "# Release 2026_004\n\n"
    "## Impact\n\n- Machines will reboot.\n\n"
    "## NixOS XX.XX platform\n\n"
    "- new bullet\n\n"
    "  continuation line\n\n"
    "- Pull upstream NixOS changes, security fixes, and package updates:\n"
    "    - chromium: 1.0 -> 1.0\n"
)

PACKAGES_V1 = {
    "chromium": {"name": "chromium-1.0", "pname": "chromium", "version": "1.0"},
    "vim": {"name": "vim-1.0", "pname": "vim", "version": "1.0"},
}
PACKAGES_V2 = {
    "chromium": {"name": "chromium-2.0", "pname": "chromium", "version": "2.0"},
    "vim": {"name": "vim-1.0", "pname": "vim", "version": "1.0"},
    "zsh": {"name": "zsh-1.0", "pname": "zsh", "version": "1.0"},
}
IMPORTANT = ["chromium", "vim", "zsh"]


def _collect_state(
    root: Path, changelog: str, np_rev: str, packages: dict
) -> None:
    (root / "changelog.d").mkdir(exist_ok=True)
    (root / "release").mkdir(exist_ok=True)
    (root / "changelog.d" / "CHANGELOG.md").write_text(changelog)
    (root / "release" / "versions.json").write_text(
        json.dumps({"nixpkgs": {"rev": np_rev}})
    )
    (root / "release" / "package-versions.json").write_text(
        json.dumps(packages)
    )
    (root / "release" / "important_packages.json").write_text(
        json.dumps(IMPORTANT)
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """git clone (file:// remote) whose fc-26.05-production carries
    collect commits for 2026_003 (old) and 2026_004 (new)."""
    remote = tmp_path / "git-remote"
    remote.mkdir()
    git(remote, "init", "-q", "-b", "fc-26.05-production")
    _collect_state(remote, R003_CHANGELOG, "a" * 40, PACKAGES_V1)
    git(remote, "add", "-A")
    git(remote, "commit", "-q", "-m", "Collect changelog fragments")
    _collect_state(remote, R004_CHANGELOG, "b" * 40, PACKAGES_V2)
    git(remote, "add", "-A")
    git(remote, "commit", "-q", "-m", "Collect changelog fragments")
    clone = tmp_path / "git-clone"
    git(tmp_path, "clone", "-q", f"file://{remote}", str(clone))
    return clone


@pytest.fixture
def hg_repo(tmp_path: Path) -> Path:
    """hg repo whose fc-26.05-production bookmark advances over the same
    two collect commits (2026_003 old, 2026_004 new)."""
    repo = tmp_path / "hg-repo"
    repo.mkdir()
    hg(repo, "init")
    (repo / ".hg" / "hgrc").write_text("[ui]\nusername = T <t@x>\n")
    (repo / "base.txt").write_text("base\n")
    _collect_state(repo, R003_CHANGELOG, "a" * 40, PACKAGES_V1)
    hg(repo, "addremove")
    hg(repo, "commit", "-m", "Collect changelog fragments")
    hg(repo, "bookmark", "fc-26.05-production")
    hg(repo, "up", "fc-26.05-production")
    _collect_state(repo, R004_CHANGELOG, "b" * 40, PACKAGES_V2)
    hg(repo, "addremove")
    hg(repo, "commit", "-m", "Collect changelog fragments")
    return repo


def _chain_shas(repo: Path) -> tuple[str, str]:
    """(old, new) collect-commit SHAs of the git fixture, independently."""
    shas = git(
        repo,
        "log",
        "--format=%H",
        "--grep",
        "Collect changelog fragments",
        "refs/remotes/origin/fc-26.05-production",
    ).split()
    return shas[1], shas[0]


def _channel_url(branch: str, release_id: str) -> str:
    return CHANNEL_URL


# --- ported pure functions ---------------------------------------------------


def test_split_releases_splits_on_release_headings():
    changelog = (
        "# Release 2026_004\n\n## NixOS XX.XX platform\n\n- b\n\n\n"
        "# Release 2026_003\n\n"
        "# Release 2026_002\n\n## Impact\n\n- x\n"
    )
    sections = rn.split_releases(changelog)
    assert set(sections) == {"2026_004", "2026_003", "2026_002"}
    assert sections["2026_003"] == ""
    assert "## Impact" in sections["2026_002"]


def test_split_releases_empty_changelog():
    assert rn.split_releases("") == {}


def test_transform_section_extracts_impact_and_platform():
    blocks = rn.parse_section(
        "## Impact\n\nMachines will reboot.\n\n"
        "## NixOS XX.XX platform\n\n- new bullet\n"
    )
    impact, platform = rn.transform_section(blocks, "26.05")
    assert impact == "Machines will reboot."
    assert platform == "- new bullet"


def test_transform_section_missing_platform():
    blocks = rn.parse_section("## Impact\n\nMachines will reboot.\n")
    impact, platform = rn.transform_section(blocks, "26.05")
    assert impact == "Machines will reboot."
    assert platform is None


def test_impact_block_adds_version_subsection():
    assert rn.impact_block("26.05", "Machines will reboot.") == (
        "### 26.05\n\nMachines will reboot."
    )


def test_impact_block_passes_through_existing_subsections():
    body = "### 25.11\n\n- old\n"
    assert rn.impact_block("26.05", body) == body


@readable(
    intention="render_release trifft das hand-gepflegte Golden-Format "
    "(r031/r033) byte-identisch",
    steps=[
        "Alle Sektionen (Impact, Platform, Detailed) rendern",
        "Mit der erwarteten Byte-Sequenz vergleichen",
    ],
    criteria=[
        "Frontmatter + zwei Leerzeilen + H1",
        "Sektionen durch \\n\\n\\n getrennt",
        "trailing \\n\\n, KEINE Archiv-Zeile",
    ],
)
def test_render_release_single_version_matches_hand_format():
    text = rn.render_release(
        "2026_004",
        "2026-08-17",
        [("26.05", "Machines will reboot to activate a changed kernel.")],
        [
            (
                "26.05",
                (
                    "- Pull upstream NixOS changes, security fixes, and "
                    "package updates:\n    - chromium: 1.0 -> 2.0"
                ),
            )
        ],
        [
            (
                "- NixOS 26.05: [platform code]("
                "https://github.com/flyingcircusio/fc-nixos/compare/old...new), "
                f"[channel url]({CHANNEL_URL})"
            )
        ],
    )
    assert text == (
        "---\n"
        "Publish Date: '2026-08-17'\n"
        "---\n"
        "\n"
        "\n"
        "# Release 2026_004 (2026-08-17)\n"
        "\n"
        "## Impact\n"
        "\n"
        "### 26.05\n"
        "\n"
        "Machines will reboot to activate a changed kernel.\n"
        "\n"
        "\n"
        "## NixOS 26.05 platform\n"
        "\n"
        "- Pull upstream NixOS changes, security fixes, and package "
        "updates:\n"
        "    - chromium: 1.0 -> 2.0\n"
        "\n"
        "\n"
        "## Detailed Changes\n"
        "\n"
        "- NixOS 26.05: [platform code]("
        "https://github.com/flyingcircusio/fc-nixos/compare/old...new), "
        f"[channel url]({CHANNEL_URL})\n"
        "\n"
    )


def test_render_release_empty_section():
    text = rn.render_release("2026_028", "2026-07-13", [], [], [])
    assert text == (
        "---\nPublish Date: '2026-07-13'\n---\n\n\n"
        "# Release 2026_028 (2026-07-13)\n\n"
    )


def test_render_release_never_renders_the_archive_line():
    text = rn.render_release("2026_004", "2026-08-17", [], [], [])
    assert gci.ARCHIVE_LINE not in text


def test_next_monday_after_thursday_release():
    # Thursday 2026-07-30 -> Monday 2026-08-03 (observed r031 pattern)
    assert rn.next_monday(datetime.date(2026, 7, 30)) == datetime.date(
        2026, 8, 3
    )


def test_next_monday_rolls_from_monday():
    assert rn.next_monday(datetime.date(2026, 8, 3)) == datetime.date(
        2026, 8, 10
    )


def test_production_branch_derives_from_version():
    assert rn.production_branch("26.05") == "fc-26.05-production"


# --- package diff (NEW) -------------------------------------------------------


@readable(
    intention="package_diff listet nur geaenderte wichtige Pakete, "
    "alphabetisch, Label = Attr-Key",
    steps=[
        "zwei package-versions-Staende und important-Set diffen",
        "unwichtige, unveraenderte und nur einseitige Pakete beiordnen",
    ],
    criteria=[
        "nur chromium als '    - chromium: 1.0 -> 2.0'",
        "vim (unveraendert) und zsh (nur neu) fehlen",
    ],
)
def test_package_diff_filters_and_sorts():
    lines = rn.package_diff(PACKAGES_V1, PACKAGES_V2, set(IMPORTANT))
    assert lines == ["    - chromium: 1.0 -> 2.0"]


def test_package_diff_sorted_alphabetically():
    old = {
        "zzz": {"version": "1"},
        "aaa": {"version": "1"},
    }
    new = {
        "zzz": {"version": "2"},
        "aaa": {"version": "2"},
    }
    assert rn.package_diff(old, new, {"aaa", "zzz"}) == [
        "    - aaa: 1 -> 2",
        "    - zzz: 1 -> 2",
    ]


def test_package_diff_without_important_filter_lists_nothing():
    assert rn.package_diff(PACKAGES_V1, PACKAGES_V2, None) == []


def test_strip_pull_block_drops_hand_written_block_with_children():
    body = (
        "- bullet\n\n"
        "- Pull upstream NixOS changes, security fixes, and package "
        "updates:\n    - chromium: 1.0 -> 1.0\n    - vim: 1.0 -> 1.1\n\n"
        "- later bullet"
    )
    assert rn.strip_pull_block(body) == "- bullet\n\n- later bullet"


def test_strip_pull_block_keeps_body_without_block():
    body = "- bullet\n\n  continuation"
    assert rn.strip_pull_block(body) == body


def test_with_pull_block_appends_only_when_non_empty():
    assert rn.with_pull_block("- b", ["    - a: 1 -> 2"]) == (
        "- b\n\n"
        "- Pull upstream NixOS changes, security fixes, and package "
        "updates:\n    - a: 1 -> 2"
    )
    assert rn.with_pull_block("- b", []) == "- b"


# --- fragment collection (collect mode) ---------------------------------------


@readable(
    intention="collect_fragments strippt Kommentare, verwirft Placeholder-"
    "Bullets, mergt Sektionen ueber Fragmente hinweg",
    steps=[
        (
            "drei Fragmente (Kommentar-Header, Placeholder-Impact, echte "
            "Bullets, XX.XX-Plattform-Heading) in changelog.d/ legen"
        ),
        "collect_fragments ausfuehren",
    ],
    criteria=[
        "genau die echten Platform-Bullets in Datei-Reihenfolge",
        "keine Placeholder- und keine Kommentar-Reste",
        "Impact-Bullets gemerged",
    ],
)
def test_collect_fragments_strips_drops_merges(tmp_path: Path):
    frag_dir = tmp_path / "changelog.d"
    frag_dir.mkdir()
    (frag_dir / "20260101_000000_PL-1_one_scriv.md").write_text(
        "<!--\nguidance comment\n-->\n\n"
        "### Impact\n\n-\n\n\n### NixOS XX.XX platform\n\n"
        "- Fix one. (PL-1)\n"
    )
    (frag_dir / "20260102_000000_PL-2_two_scriv.md").write_text(
        "### Impact\n\n<!-- inner comment -->\n- Machines restart.\n\n\n"
        "### NixOS XX.XX platform\n\n- Fix two.\n\n  explanation line\n"
    )
    (frag_dir / "20260301_000000_PL-3_three_scriv.md").write_text(
        "### Impact\n\n-\n\n\n### NixOS XX.XX platform\n\n- Add three.\n"
    )
    collected = rn.collect_fragments(frag_dir)
    assert collected.count == 3
    assert collected.impact == ["- Machines restart."]
    assert collected.platform == [
        "- Fix one. (PL-1)",
        "- Fix two.\n\n  explanation line",
        "- Add three.",
    ]


def test_fragment_bullets_glues_continuations_after_blank_lines():
    bullets = rn.fragment_bullets("- bullet\n\n  continuation\n\n- next")
    assert bullets == ["- bullet\n\n  continuation", "- next"]


def test_fragment_bullets_drops_placeholder_and_stray_prose():
    bullets = rn.fragment_bullets("-\n\n- real\n\nstray prose")
    assert bullets == ["- real"]


# --- VCS chain derivation ------------------------------------------------------


@readable(
    intention="derive_release_chain findet beide Collect-Commits "
    "message-basiert in der git-Historie",
    steps=[
        "Chain fuer 2026_004 gegen den Mini-Mirror ableiten",
        "mit den echten Collect-SHAs vergleichen",
    ],
    criteria=["(old, new) entspricht den Commits fuer r003/r004"],
)
def test_derive_release_chain_git(git_repo: Path):
    backend = GitBackend(repo=git_repo)
    chain = rn.derive_release_chain(backend, "fc-26.05-production", "2026_004")
    assert chain is not None
    old, new = chain
    assert (old, new) == _chain_shas(git_repo)


def test_derive_release_chain_hg(hg_repo: Path):
    backend = HgBackend(repo=hg_repo)
    chain = rn.derive_release_chain(backend, "fc-26.05-production", "2026_004")
    assert chain is not None
    old, new = chain
    nodes = hg(
        hg_repo,
        "log",
        "-r",
        "keyword('Collect changelog fragments')",
        "-T",
        "{node}\n",
    ).split()
    # the bare keyword revset iterates ascending (oldest first)
    assert (old, new) == (nodes[0], nodes[1])


def test_derive_release_chain_unknown_release_is_none(git_repo: Path):
    backend = GitBackend(repo=git_repo)
    assert (
        rn.derive_release_chain(backend, "fc-26.05-production", "2026_099")
        is None
    )


# --- orchestration: history mode ------------------------------------------------


@readable(
    intention="run_release_notes rendert die r-Seite im History-Modus: "
    "Fragment-Bullets, generierter Package-Diff statt Hand-Block, "
    "Detailed-Zeile mit Compare/nixpkgs/metadata/channel",
    steps=[
        (
            "git-Fixture (zwei Collect-Commits, Hand-Pull-Block im r004-"
            "Changelog) und TOML bauen"
        ),
        "run_release_notes fuer 2026_004 mit injizierter Channel-URL",
        "Seite und Log-Story pruefen",
    ],
    criteria=[
        "Impact '### 26.05' mit Changelog-Bullet",
        (
            "Platform: Fragment-Bullet + generierter Pull-Block "
            "(chromium 1.0 -> 2.0), Hand-Block ersetzt"
        ),
        "Detailed-Zeile mit echten SHAs, nixpkgs aaa...bbb, metadata, channel",
        (
            "Log-Events release-section-found / release-chain-derived / "
            "package-diff-rendered / release-page-written"
        ),
    ],
)
def test_run_release_notes_git_history_mode(git_repo: Path, tmp_path: Path):
    old, new = _chain_shas(git_repo)
    out = tmp_path / "src"
    with capture_logs() as logs:
        text = rn.run_release_notes(
            versions_file(tmp_path),
            git_repo,
            "2026_004",
            "2026-08-17",
            out=out,
            channel_url_fn=_channel_url,
        )
    assert text == (
        "---\n"
        "Publish Date: '2026-08-17'\n"
        "---\n\n\n"
        "# Release 2026_004 (2026-08-17)\n\n"
        "## Impact\n\n"
        "### 26.05\n\n"
        "- Machines will reboot.\n\n\n"
        "## NixOS 26.05 platform\n\n"
        "- new bullet\n\n"
        "  continuation line\n\n"
        "- Pull upstream NixOS changes, security fixes, and package "
        "updates:\n"
        "    - chromium: 1.0 -> 2.0\n\n\n"
        "## Detailed Changes\n\n"
        f"- NixOS 26.05: [platform code](https://github.com/flyingcircusio/"
        f"fc-nixos/compare/{old}...{new}), [nixpkgs/upstream changes]"
        f"(https://github.com/flyingcircusio/nixpkgs/compare/"
        f"{'a' * 40}...{'b' * 40}), [metadata](https://my.flyingcircus.io/"
        "releases/metadata/fc-26.05-production/2026_004), "
        f"[channel url]({CHANNEL_URL})\n\n"
    )
    assert (out / "changes" / "2026" / "r004.md").read_text() == text
    events = [entry["event"] for entry in logs]
    assert "release-section-found" in events
    assert "release-chain-derived" in events
    assert "package-diff-rendered" in events
    assert "release-page-written" in events


def test_run_release_notes_skips_unresolvable_production_branches(
    git_repo: Path, tmp_path: Path
):
    """prerelease/sunsetting branches missing in the clone: info-skip."""
    with capture_logs() as logs:
        rn.run_release_notes(
            versions_file(tmp_path),
            git_repo,
            "2026_004",
            "2026-08-17",
            out=tmp_path / "src",
            channel_url_fn=_channel_url,
        )
    skipped = [
        entry
        for entry in logs
        if entry["event"] == "production-branch-unavailable"
    ]
    assert {entry["branch"] for entry in skipped} == {
        "fc-26.11-production",
        "fc-25.11-production",
    }


@readable(
    intention="Cross-Tool-Contract: die gerenderte Seite besteht "
    "gen_changes_index.parse_release_page mit Datum+Versionen",
    steps=[
        "Seite rendern (beide Modi)",
        "parse_release_page ausfuehren",
    ],
    criteria=["date korrekt", "versions == ['26.05']"],
)
def test_rendered_page_passes_changes_index_parser(
    git_repo: Path, tmp_path: Path
):
    out = tmp_path / "src"
    rn.run_release_notes(
        versions_file(tmp_path),
        git_repo,
        "2026_004",
        "2026-08-17",
        out=out,
        channel_url_fn=_channel_url,
    )
    rel = gci.parse_release_page(out / "changes" / "2026" / "r004.md")
    assert rel.date == "2026-08-17"
    assert rel.versions == ["26.05"]
    assert rel.marker is None


@readable(
    intention="hg-Modus-Grenze (Shamap-Luecke): hg-Nodes liefern keine "
    "GitHub-SHAs -- Compare-Link fehlt mit Warnung statt fake SHA",
    steps=[
        "hg-Fixture (Collect-Commits als Nodes) bauen",
        "run_release_notes ausfuehren, Logs capturen",
    ],
    criteria=[
        "Warnung platform-compare-unavailable-hg-shamap mit Hint",
        "KEIN fc-nixos/compare-Link in der Detailed-Zeile",
        "nixpkgs-/metadata-/channel-Teile vorhanden",
    ],
)
def test_hg_mode_shamap_gap_warns_instead_of_faking(
    hg_repo: Path, tmp_path: Path
):
    with capture_logs() as logs:
        text = rn.run_release_notes(
            versions_file(tmp_path),
            hg_repo,
            "2026_004",
            "2026-08-17",
            out=tmp_path / "src",
            channel_url_fn=_channel_url,
        )
    warning = next(
        entry
        for entry in logs
        if entry["event"] == "platform-compare-unavailable-hg-shamap"
    )
    assert "shamap" in warning["hint"]
    assert "fc-nixos/compare" not in text
    assert "nixpkgs/compare" in text
    assert "releases/metadata/fc-26.05-production/2026_004" in text
    assert CHANNEL_URL in text


def test_run_release_notes_no_detailed_skips_chain_parts(
    git_repo: Path, tmp_path: Path
):
    """--no-detailed: keine Detailed-Sektion, Platform-Body unangetastet."""
    text = rn.run_release_notes(
        versions_file(tmp_path),
        git_repo,
        "2026_004",
        "2026-08-17",
        out=tmp_path / "src",
        detailed=False,
    )
    assert "## Detailed Changes" not in text
    # ohne Chain bleibt der handgeschriebene Pull-Block unveraendert stehen
    assert "    - chromium: 1.0 -> 1.0" in text
    assert "    - chromium: 1.0 -> 2.0" not in text


def test_run_release_notes_refuses_existing_without_force(
    git_repo: Path, tmp_path: Path
):
    config = versions_file(tmp_path)
    out = tmp_path / "src"
    rn.run_release_notes(
        config,
        git_repo,
        "2026_004",
        "2026-08-17",
        out=out,
        channel_url_fn=_channel_url,
    )
    with pytest.raises(FileExistsError):
        rn.run_release_notes(
            config,
            git_repo,
            "2026_004",
            "2026-08-17",
            out=out,
            channel_url_fn=_channel_url,
        )
    rn.run_release_notes(
        config,
        git_repo,
        "2026_004",
        "2026-08-17",
        out=out,
        force=True,
        channel_url_fn=_channel_url,
    )


def test_run_release_notes_validates_release_id_and_date(tmp_path: Path):
    with pytest.raises(ValueError, match="YYYY_NNN"):
        rn.run_release_notes(
            versions_file(tmp_path), tmp_path, "bad", "2026-08-17"
        )
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        rn.run_release_notes(
            versions_file(tmp_path), tmp_path, "2026_004", "17.08.2026"
        )


# --- orchestration: collect mode ------------------------------------------------


@readable(
    intention="Collect-Modus (VCS-loser Baum): Skelett aus Fragmenten, "
    "XX.XX gebacken auf TOML-stable, Package-Diff-Warnung, kein Detailed",
    steps=[
        "Sandbox mit changelog.d/-Fragmenten und release/-JSONs bauen",
        "run_release_notes fuer ein nicht gesammeltes Release",
    ],
    criteria=[
        "'## NixOS 26.05 platform' mit Fragment-Bullets",
        "kein XX.XX, keine Detailed-Sektion",
        "Warnung package-diff-skipped (keine Collect-Basis)",
    ],
)
def test_collect_mode_renders_skeleton_without_vcs(tmp_path: Path):
    sandbox = tmp_path / "sandbox"
    frag_dir = sandbox / "changelog.d"
    frag_dir.mkdir(parents=True)
    (frag_dir / "20260101_000000_PL-1_one_scriv.md").write_text(
        "### Impact\n\n-\n\n\n### NixOS XX.XX platform\n\n- Fix one. (PL-1)\n"
    )
    (frag_dir / "20260102_000000_PL-2_two_scriv.md").write_text(
        "### NixOS XX.XX platform\n\n- Fix two.\n"
    )
    (sandbox / "release").mkdir()
    (sandbox / "release" / "package-versions.json").write_text(
        json.dumps(PACKAGES_V2)
    )
    (sandbox / "release" / "important_packages.json").write_text(
        json.dumps(IMPORTANT)
    )
    with capture_logs() as logs:
        text = rn.run_release_notes(
            versions_file(tmp_path),
            sandbox,
            "2026_005",
            "2026-08-24",
            out=tmp_path / "src",
        )
    assert "## NixOS 26.05 platform" in text
    assert "XX.XX" not in text
    assert "- Fix one. (PL-1)\n\n- Fix two." in text
    assert "## Impact" not in text  # nur Placeholder -> Sektion entfaellt
    assert "## Detailed Changes" not in text
    assert "Pull upstream" not in text
    events = [entry["event"] for entry in logs]
    assert "collect-mode-no-vcs" in events
    assert "fragments-collected" in events
    assert "package-diff-skipped" in events
    rel = gci.parse_release_page(
        tmp_path / "src" / "changes" / "2026" / "r005.md"
    )
    assert (rel.date, rel.versions) == ("2026-08-24", ["26.05"])


def test_collect_mode_collects_package_diff_against_last_collect_commit(
    hg_repo: Path, tmp_path: Path
):
    """Collect-Modus MIT Seam: working tree gegen letzten Collect-Commit."""
    frag_dir = hg_repo / "changelog.d"
    (frag_dir / "20260101_000000_PL-9_new_scriv.md").write_text(
        "### NixOS XX.XX platform\n\n- Fix nine. (PL-9)\n"
    )
    (hg_repo / "release" / "package-versions.json").write_text(
        json.dumps(
            {
                **PACKAGES_V1,
                "chromium": {
                    "name": "chromium-3.0",
                    "pname": "chromium",
                    "version": "3.0",
                },
            }
        )
    )
    text = rn.run_release_notes(
        versions_file(tmp_path),
        hg_repo,
        "2026_005",
        "2026-08-24",
        out=tmp_path / "src",
    )
    assert (
        "- Pull upstream NixOS changes, security fixes, and package "
        "updates:\n    - chromium: 2.0 -> 3.0" in text
    )


def test_collect_mode_without_fragments_fails_loudly(tmp_path: Path):
    empty = tmp_path / "empty-repo"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="no fragments"):
        rn.run_release_notes(
            versions_file(tmp_path), empty, "2026_005", "2026-08-24"
        )


def test_collect_mode_never_touches_fragments(hg_repo: Path, tmp_path: Path):
    """Collect liest nur: Fragmente und CHANGELOG bleiben byte-identisch."""
    frag = hg_repo / "changelog.d" / "20260101_000000_PL-9_new_scriv.md"
    frag.write_text("### NixOS XX.XX platform\n\n- Fix nine. (PL-9)\n")
    changelog = hg_repo / "changelog.d" / "CHANGELOG.md"
    before_frag = frag.read_text()
    before_changelog = changelog.read_text()
    rn.run_release_notes(
        versions_file(tmp_path),
        hg_repo,
        "2026_005",
        "2026-08-24",
        out=tmp_path / "src",
    )
    assert frag.read_text() == before_frag
    assert changelog.read_text() == before_changelog


# --- CLI ------------------------------------------------------------------------


@readable(
    intention="CLI-Suite: Schreiben, --dry-run auf stdout, Validierung, "
    "--force, Default-Publish-Date",
    steps=[
        "main mit allen Flag-Kombinationen aufrufen",
        "Exit-Codes, Dateisystem und stdout/stderr pruefen",
    ],
    criteria=[
        "Exit 0 schreibt die Seite, stderr erzaehlt die Story",
        "--dry-run druckt die Seite, schreibt nichts",
        "kaputte Argumente -> Exit 2",
        "Existierende Seite -> Exit 1, mit --force Exit 0",
    ],
)
def test_cli_write_dry_run_validation_force(
    git_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    config = versions_file(tmp_path)
    out = tmp_path / "src"
    code = rn.main(
        [
            "--repo",
            str(git_repo),
            str(config),
            "2026_004",
            "--publish-date",
            "2026-08-17",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert (out / "changes" / "2026" / "r004.md").is_file()
    err = capsys.readouterr().err
    assert "release-page-written" in err

    code = rn.main(
        [
            "--repo",
            str(git_repo),
            str(config),
            "2026_004",
            "--publish-date",
            "2026-08-17",
            "--dry-run",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("---\nPublish Date: '2026-08-17'\n---")
    assert captured.out == (out / "changes" / "2026" / "r004.md").read_text()
    assert "release-page-dry-run" in captured.err

    assert (
        rn.main([str(config), "2026_004", "--publish-date", "17.08.2026"]) == 2
    )
    assert rn.main([str(config), "nope"]) == 2
    assert (
        rn.main(
            [
                "--repo",
                str(git_repo),
                str(config),
                "2026_004",
                "--publish-date",
                "2026-08-17",
                "--out",
                str(out),
            ]
        )
        == 1
    )
    assert (
        rn.main(
            [
                "--repo",
                str(git_repo),
                str(config),
                "2026_004",
                "--publish-date",
                "2026-08-17",
                "--out",
                str(out),
                "--force",
            ]
        )
        == 0
    )


def test_cli_defaults_publish_date_to_next_monday(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Ohne --publish-date: naechster Montag (feste Uhrzeit injiziert)."""
    import tools.release_notes as rn_mod

    monkeypatch.setattr(
        rn_mod,
        "next_monday",
        lambda today=None: datetime.date(2026, 8, 24),
    )
    out = tmp_path / "src"
    assert (
        rn.main(
            [
                "--repo",
                str(git_repo),
                str(versions_file(tmp_path)),
                "2026_004",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    text = (out / "changes" / "2026" / "r004.md").read_text()
    assert "Publish Date: '2026-08-24'" in text


# --- documentation contract ------------------------------------------------------


def test_module_docstring_documents_shamap_gap_and_workflow():
    """Der Modul-Docstring dokumentiert die hg-Grenze und den Workflow."""
    doc = rn.__doc__
    assert doc is not None
    assert "shamap" in doc
    assert "platform-compare-unavailable-hg-shamap" in doc
    assert "gen_changes_index" in doc
    assert "zensical.toml" in doc
    assert "Collect changelog fragments" in doc
