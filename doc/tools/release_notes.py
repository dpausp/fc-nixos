"""Generate per-release changelog pages (``src/changes/<year>/rNNN.md``).

``./appenv python -m tools.release_notes [--repo PATH]
platform-versions.toml <RELEASE> [--publish-date YYYY-MM-DD]
[--dry-run] [--no-detailed]`` -- port of the /doc generator onto the
shared :mod:`tools.vcs_backend` seam, plus a generated package diff
and a fragment-collect mode. Two data sources, one rendered page in
the hand-maintained golden format (r031/r033):

* HISTORY mode -- the release was collected: every version declared
  in the TOML contributes via its PRODUCTION branch
  (``fc-<ver>-production``, resolved through the seam -- hg
  bookmarks strictly locally, git as ``refs/remotes/origin/<branch>``;
  an unresolvable branch is skipped with an info event, e.g. a
  prerelease without production branch). The cumulative
  ``changelog.d/CHANGELOG.md`` at the branch TIP provides the
  Impact/platform fragment bullets; the compare chain (each release's
  tip is a "Collect changelog fragments" commit whose changelog
  starts with ``# Release <id>``) provides the Detailed Changes
  links; ``release/versions.json`` at both chain links pins the
  nixpkgs compare; the channel URL comes from the release metadata
  API (certifi-verified -- unreachable degrades to a warning, the
  release manager fills it manually).

* COLLECT mode -- the release is being prepared: no production branch
  carries it yet (or ``--repo`` points at a tree without VCS), so the
  working-tree ``changelog.d/*_scriv.md`` fragments are collected
  (comments stripped, placeholder bullets dropped, sections merged,
  ``XX.XX`` baked to the TOML stable version) into a SKELETON page.
  The package diff compares the working tree against the last collect
  commit when the seam can resolve one; otherwise the Pull-upstream
  block is skipped with a warning. Fragments are NEVER modified or
  deleted -- output goes to the page (or stdout with ``--dry-run``)
  only.

NEW against the /doc generator: the package diff. Changed versions of
important packages (``release/package-versions.json`` at both chain
links, filtered on ``release/important_packages.json``, label = attr
key, alphabetically) render as ``- attr: old -> new`` under
``- Pull upstream NixOS changes, security fixes, and package
updates:`` -- a hand-written block of that shape in the changelog is
REPLACED by the generated one.

NOT ported from /doc: the zensical nav machinery (this repo's nav
model is a single changelog link in ``zensical.toml`` plus the
generated ``changes/index.md``) and the archive line -- the line
``*All releases: [changelog archive](../index.md).*`` is owned by
``tools.gen_changes_index`` (commit 18871).

Release workflow (this repo):

1. ``./appenv python -m tools.release_notes platform-versions.toml
   2026_034 [--publish-date YYYY-MM-DD]`` -- renders the skeleton
   (collect mode against the working tree) or the full page (history
   mode against the production bookmarks/branches);
2. the release manager reviews and refines the page (hand fixes,
   additional Impact notes, the channel URL when the API was
   unreachable) and commits ``rNNN.md``;
3. ``./appenv python -m tools.gen_changes_index`` -- regenerates
   ``changes/index.md`` and moves the archive link to the new latest
   page. The ``zensical.toml`` changelog target never changes.

HG-MODE LIMIT (the shamap gap): the ``[platform code]`` compare link
needs the GITHUB commit SHAs of the two chain links. In git mode the
mirror carries them; in hg mode the seam yields hg NODE hashes, and
hg nodes cannot be mapped to git SHAs locally (the shamap lives in
the mirror converter infrastructure, not in this repo). Faking a SHA
would point at an arbitrary commit -- instead the link is OMITTED
with a loud ``platform-compare-unavailable-hg-shamap`` warning. The
nixpkgs compare link is unaffected (``release/versions.json`` pins
the nixpkgs GIT revs on both sides); metadata and channel links are
SHA-free anyway.

The tool never overwrites an existing r-file (``--force`` overrides),
never touches ``changelog.d/``, and never commits.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import ssl
import subprocess
import sys
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import certifi
import structlog

from tools.gen_platform_versions import VersionSet, load_versions
from tools.vcs_backend import (
    GitBackend,
    HgBackend,
    NoVcsBackendError,
    RefResolutionError,
    VcsError,
    detect_backend,
)

log = structlog.get_logger()

# doc/ root -- defaults resolve relative to the module, not the cwd,
# so the tool works from any directory (sister tools do the same).
DOC_ROOT = Path(__file__).resolve().parents[1]

# The repository that carries the changelog fragments and release
# metadata: doc/'s parent (the fc-nixos working copy / mirror clone).
REPO_ROOT = DOC_ROOT.parent

# Every release section in a branch CHANGELOG.md starts with a level-1
# heading ``# Release YYYY_NNN``; the file is cumulative (newest first).
_RELEASE_HEADING = re.compile(r"^# Release (\d{4}_\d{3})\s*$", re.MULTILINE)

# Level-2 headings inside one release section (``## Impact``,
# ``## NixOS XX.XX platform``, ...).
_SECTION_HEADING = re.compile(r"^## (.+?)\s*$", re.MULTILINE)

# Level-3 headings inside one scriv fragment (``### Impact``,
# ``### NixOS XX.XX platform``).
_FRAGMENT_HEADING = re.compile(r"^### (.+?)\s*$", re.MULTILINE)

# HTML comments carry fragment guidance -- never release content.
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

# Blank-line-separated paragraph blocks (bullet + continuation glue).
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")

_RELEASE_ID = re.compile(r"\d{4}_\d{3}")
_PUBLISH_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

CHANGELOG_PATH = "changelog.d/CHANGELOG.md"
FRAGMENT_GLOB = "*_scriv.md"
VERSIONS_JSON = "release/versions.json"
PACKAGE_VERSIONS_JSON = "release/package-versions.json"
IMPORTANT_PACKAGES_JSON = "release/important_packages.json"

# The production branch each declared version releases from.
COLLECT_MESSAGE = "Collect changelog fragments"

PULL_UPSTREAM_LINE = (
    "- Pull upstream NixOS changes, security fixes, and package updates:"
)
PULL_UPSTREAM_PREFIX = "- Pull upstream"


def production_branch(ver: str) -> str:
    """The production branch a platform version releases from."""
    return f"fc-{ver}-production"


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """One captured subprocess -- never checked, never silent."""
    return subprocess.run(
        argv, cwd=cwd, capture_output=True, text=True, check=False
    )


# --- ported text pipeline (split/parse/transform/render) -------------------


def split_releases(changelog: str) -> dict[str, str]:
    """Split a branch ``CHANGELOG.md`` into ``{release_id: section_text}``.

    The section text excludes the ``# Release YYYY_NNN`` heading itself.
    Releases without any content map to an empty string.
    """
    matches = list(_RELEASE_HEADING.finditer(changelog))
    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(changelog)
        sections[match.group(1)] = changelog[start:end].strip("\n")
    return sections


def parse_section(section: str) -> dict[str, str]:
    """Map ``## heading`` -> body for one release section."""
    blocks: dict[str, str] = {}
    matches = list(_SECTION_HEADING.finditer(section))
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(section)
        blocks[match.group(1).strip()] = section[start:end].strip("\n")
    return blocks


def parse_fragment(text: str) -> dict[str, str]:
    """Map ``### heading`` -> body for one scriv fragment (comments gone)."""
    stripped = _HTML_COMMENT.sub("", text)
    blocks: dict[str, str] = {}
    matches = list(_FRAGMENT_HEADING.finditer(stripped))
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(stripped)
        blocks[match.group(1).strip()] = stripped[start:end].strip("\n")
    return blocks


def transform_section(
    blocks: dict[str, str], version: str
) -> tuple[str | None, str | None]:
    """Extract the Impact body and the NixOS platform body of a section.

    The platform heading in the branch changelog always carries the
    ``XX.XX`` placeholder (kept for backport-friendliness); the version is
    baked in at render time, so only the body is returned here.
    """
    impact = blocks.get("Impact")
    platform = None
    for heading, body in blocks.items():
        if heading.startswith("NixOS ") and heading.endswith(" platform"):
            platform = body
            break
    return impact, platform


def impact_block(version: str, body: str) -> str:
    """Render one version's Impact subsection (``### <ver>`` + body).

    A body that already carries ``###`` subsections is passed through
    untouched (defensive: the branch changelog normally keeps flat bullets).
    """
    if body.lstrip().startswith("### "):
        return body
    return f"### {version}\n\n{body}"


def render_release(
    release_id: str,
    publish_date: str,
    impact_blocks: list[tuple[str, str]],
    platform_blocks: list[tuple[str, str]],
    detailed_lines: list[str],
) -> str:
    """Render the r-file body matching the hand-maintained format.

    Sections are separated by two blank lines; the file ends with a trailing
    blank line pair (matching ``src/changes/2026/r031.md``). The archive
    link is NOT rendered here -- ``tools.gen_changes_index`` owns it.
    """
    sections: list[str] = []
    if impact_blocks:
        impact = "## Impact\n\n" + "\n\n\n".join(
            impact_block(ver, body) for ver, body in impact_blocks
        )
        sections.append(impact)
    for ver, body in platform_blocks:
        sections.append(f"## NixOS {ver} platform\n\n{body}")
    if detailed_lines:
        sections.append("## Detailed Changes\n\n" + "\n".join(detailed_lines))
    text = (
        f"---\nPublish Date: '{publish_date}'\n---\n\n\n"
        f"# Release {release_id} ({publish_date})\n\n"
    )
    if sections:
        text += "\n\n\n".join(sections) + "\n\n"
    return text


def next_monday(today: datetime.date | None = None) -> datetime.date:
    """The next Monday at or after *today*.

    Release notes publish on Mondays (observed pattern: Thursday release,
    Monday publish). A Monday *today* rolls to the following Monday.
    """
    today = today or datetime.datetime.now(tz=datetime.timezone.utc).date()
    days = (0 - today.weekday()) % 7
    return today + datetime.timedelta(days=days or 7)


# --- package diff (NEW) ------------------------------------------------------


def package_versions_json(text: str | None) -> dict | None:
    """Parse a ``package-versions.json`` payload (None passes through)."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning(
            "package-versions-unparsable",
            error=str(exc),
        )
        return None


def package_diff(old: dict, new: dict, important: set[str] | None) -> list[str]:
    """``    - attr: old -> new`` per changed important package, sorted.

    Label is the attr key of ``package-versions.json`` (how the attr is
    referenced in ``important_packages.json``); only packages present (and
    important) on BOTH sides with differing versions list -- alphabetically.
    """
    wanted = set(old) & set(new) & (important or set())
    lines: list[str] = []
    for attr in sorted(wanted):
        old_ver = old[attr].get("version")
        new_ver = new[attr].get("version")
        if old_ver and new_ver and old_ver != new_ver:
            lines.append(f"    - {attr}: {old_ver} -> {new_ver}")
    return lines


def strip_pull_block(body: str) -> str:
    """Drop a hand-written Pull-upstream bullet and its indented children.

    The generated package diff replaces the hand-maintained block: without
    the strip a re-render would duplicate the section. Blank lines that
    only separated the dropped block go with it.
    """
    kept: list[str] = []
    skipping = False
    for line in body.splitlines():
        if line.startswith(PULL_UPSTREAM_PREFIX):
            skipping = True
            while kept and not kept[-1].strip():
                kept.pop()
            continue
        if skipping and line.strip() and (line[0] in " \t"):
            continue  # indented child of the dropped bullet
        skipping = False
        kept.append(line)
    return "\n".join(kept).strip("\n")


def with_pull_block(body: str, diff_lines: list[str]) -> str:
    """Append the generated Pull-upstream block under *body* (when non-empty)."""
    if not diff_lines:
        return body
    return f"{body}\n\n{PULL_UPSTREAM_LINE}\n" + "\n".join(diff_lines)


# --- fragment collection (collect mode) --------------------------------------


def fragment_bullets(body: str) -> list[str]:
    """Bullet blocks of one fragment section, placeholders dropped.

    Blank-line-separated blocks: a block starting with ``- `` is a bullet
    (a lone ``-`` is the scriv placeholder and is dropped), an INDENTED
    block is a CONTINUATION glued onto the previous bullet (scriv style:
    a blank line between bullet and indented explanation). Unindented
    prose is not changelog content and is dropped.
    """
    bullets: list[str] = []
    for block in _PARAGRAPH_SPLIT.split(body.strip()):
        if not block.strip():
            continue
        if block.strip() == "-":
            continue  # placeholder bullet
        if block.startswith("- "):
            bullets.append(block.rstrip())
        elif bullets and block[:1] in (" ", "\t"):
            bullets[-1] = f"{bullets[-1]}\n\n{block.rstrip()}"
    return bullets


@dataclass(frozen=True, slots=True)
class CollectedFragments:
    """Merged scriv fragment sections across ``changelog.d/*_scriv.md``."""

    impact: list[str]
    platform: list[str]
    count: int


def collect_fragments(fragment_dir: Path) -> CollectedFragments:
    """Collect every ``*_scriv.md`` fragment of *fragment_dir* (sorted).

    HTML comments are stripped, placeholder bullets dropped, sections
    merged in filename order (the ``YYYYMMDD_...`` prefix makes that
    chronological). Never writes anything -- collection is read-only.
    """
    impact: list[str] = []
    platform: list[str] = []
    fragments = sorted(fragment_dir.glob(FRAGMENT_GLOB))
    for fragment in fragments:
        sections = parse_fragment(fragment.read_text(encoding="utf-8"))
        for heading, body in sections.items():
            if heading == "Impact":
                impact.extend(fragment_bullets(body))
            elif heading.startswith("NixOS ") and heading.endswith(" platform"):
                platform.extend(fragment_bullets(body))
    collected = CollectedFragments(
        impact=impact, platform=platform, count=len(fragments)
    )
    log.info(
        "fragments-collected",
        fragments=collected.count,
        impact_bullets=len(impact),
        platform_bullets=len(platform),
    )
    return collected


# --- VCS-backed derivation (chain, pins, package payload) --------------------


def collect_commits(
    backend: HgBackend | GitBackend, ref: str, branch: str
) -> list[str]:
    """The ``Collect changelog fragments`` commits on *branch*, newest first.

    hg walks ``::<ref>`` with a keyword search, git greps its log from the
    resolved ``refs/remotes/origin/<branch>`` commit -- both strictly local.
    """
    if isinstance(backend, HgBackend):
        proc = _run(
            [
                "hg",
                "log",
                "-r",
                f"reverse(::{ref})",
                "-k",
                COLLECT_MESSAGE,
                "-T",
                "{node}\n",
            ],
            backend.repo,
        )
    else:
        proc = _run(
            [
                "git",
                "--no-pager",
                "log",
                "--format=%H",
                "--grep",
                COLLECT_MESSAGE,
                ref,
            ],
            backend.repo,
        )
    if proc.returncode != 0:
        msg = (
            f"cannot enumerate {COLLECT_MESSAGE!r} commits on {branch!r} "
            f"({proc.stderr.strip()})"
        )
        raise VcsError(msg)
    commits = [line for line in proc.stdout.split() if line]
    log.info("collect-commits-found", branch=branch, count=len(commits))
    return commits


def derive_release_chain(
    backend: HgBackend | GitBackend, branch: str, release_id: str
) -> tuple[str, str] | None:
    """The ``(old, new)`` compare chain for *release_id* on *branch*.

    Each release's production tip is a "Collect changelog fragments"
    commit whose ``changelog.d/CHANGELOG.md`` starts with
    ``# Release <id>``. The chain is that commit (new) and the previous
    such commit (old). Revs are hg nodes / git SHAs -- whatever the
    backend resolves; see the module docstring for the hg shamap limit.
    """
    ref = backend.resolve_ref(branch)
    new_rev: str | None = None
    old_rev: str | None = None
    for rev in collect_commits(backend, ref, branch):
        changelog = backend.read_file(rev, CHANGELOG_PATH)
        if changelog is None:
            continue
        lines = changelog.splitlines()
        first = lines[0] if lines else ""
        if first == f"# Release {release_id}":
            new_rev = rev
        elif new_rev is not None and first.startswith("# Release "):
            old_rev = rev
            break
    if new_rev is None or old_rev is None:
        log.warning(
            "release-chain-missing",
            branch=branch,
            release=release_id,
            old=old_rev,
            new=new_rev,
        )
        return None
    log.info(
        "release-chain-derived",
        branch=branch,
        release=release_id,
        old=old_rev[:12],
        new=new_rev[:12],
    )
    return old_rev, new_rev


def _json_at(
    backend: HgBackend | GitBackend, rev: str, path: str
) -> dict | None:
    """Parsed JSON content of *path* at *rev* (None when absent/broken)."""
    return package_versions_json(backend.read_file(rev, path))


def nixpkgs_rev(backend: HgBackend | GitBackend, rev: str) -> str | None:
    """The pinned nixpkgs rev at *rev* (from ``release/versions.json``)."""
    data = _json_at(backend, rev, VERSIONS_JSON)
    if not isinstance(data, dict):
        return None
    try:
        return data["nixpkgs"]["rev"]
    except (KeyError, TypeError):
        return None


def release_package_diff(
    backend: HgBackend | GitBackend, chain: tuple[str, str]
) -> list[str]:
    """The generated Pull-upstream entries for one *chain* (old, new)."""
    old_rev, new_rev = chain
    old_pkgs = _json_at(backend, old_rev, PACKAGE_VERSIONS_JSON)
    new_pkgs = _json_at(backend, new_rev, PACKAGE_VERSIONS_JSON)
    important_raw = _json_at(backend, new_rev, IMPORTANT_PACKAGES_JSON)
    if old_pkgs is None or new_pkgs is None:
        log.warning(
            "package-diff-skipped",
            reason="package-versions.json unreadable at a chain link",
            old=old_rev[:12],
            new=new_rev[:12],
        )
        return []
    important = set(important_raw) if isinstance(important_raw, list) else None
    if important is None:
        log.warning(
            "package-diff-skipped",
            reason=f"{IMPORTANT_PACKAGES_JSON} unreadable at the chain tip",
            new=new_rev[:12],
        )
    lines = package_diff(old_pkgs, new_pkgs, important)
    log.info("package-diff-rendered", count=len(lines))
    return lines


# --- metadata API ------------------------------------------------------------


def fetch_channel_url(branch: str, release_id: str) -> str | None:
    """The hydra channel URL for a release from the metadata API.

    Returns None (with a warning) when the API is unreachable or the field
    is missing -- the release manager then fills the link manually.
    """
    url = f"https://my.flyingcircus.io/releases/metadata/{branch}/{release_id}"
    try:
        context = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(url, context=context, timeout=30) as resp:
            data = json.load(resp)
        return data.get("channel_url")
    except Exception as exc:  # noqa: BLE001 -- any failure degrades gracefully
        log.warning("channel-url-fetch-failed", url=url, error=str(exc))
        return None


def render_detailed_changes(
    backend: HgBackend | GitBackend,
    contributing: Sequence[tuple[str, str]],
    release_id: str,
    *,
    channel_url_fn=fetch_channel_url,
) -> list[str]:
    """One ``- NixOS <ver>: ...`` line per contributing production branch.

    A branch whose chain cannot be derived is skipped with a warning; the
    release manager completes the section manually in that case. In hg mode
    the platform-code compare link is omitted with the shamap warning (see
    the module docstring) -- never a faked SHA.
    """
    lines: list[str] = []
    for ver, branch in contributing:
        chain = derive_release_chain(backend, branch, release_id)
        if chain is None:
            log.warning(
                "detailed-changes-chain-missing", version=ver, branch=branch
            )
            continue
        old_rev, new_rev = chain
        old_np = nixpkgs_rev(backend, old_rev)
        new_np = nixpkgs_rev(backend, new_rev)
        parts: list[str] = []
        if isinstance(backend, GitBackend):
            parts.append(
                "[platform code]("
                f"https://github.com/flyingcircusio/fc-nixos/compare/"
                f"{old_rev}...{new_rev})"
            )
        else:
            log.warning(
                "platform-compare-unavailable-hg-shamap",
                version=ver,
                branch=branch,
                old_node=old_rev[:12],
                new_node=new_rev[:12],
                hint=(
                    "hg node hashes cannot be mapped to the GitHub SHAs the "
                    "compare link needs (shamap lives in the mirror "
                    "converter) -- fill the link manually instead of faking "
                    "a SHA"
                ),
            )
        if old_np and new_np:
            parts.append(
                "[nixpkgs/upstream changes]("
                f"https://github.com/flyingcircusio/nixpkgs/compare/"
                f"{old_np}...{new_np})"
            )
        parts.append(
            "[metadata](https://my.flyingcircus.io/releases/metadata/"
            f"{branch}/{release_id})"
        )
        channel_url = (
            channel_url_fn(branch, release_id) if channel_url_fn else None
        )
        if channel_url:
            parts.append(f"[channel url]({channel_url})")
        lines.append(f"- NixOS {ver}: " + ", ".join(parts))
    return lines


# --- orchestration -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Contribution:
    """One production branch carrying the release."""

    ver: str
    branch: str
    impact: str | None
    platform: str | None
    chain: tuple[str, str] | None


def _find_contributions(
    backend: HgBackend | GitBackend,
    versions: VersionSet,
    release_id: str,
    *,
    detailed: bool,
) -> list[Contribution]:
    """The declared versions whose production branch carries *release_id*."""
    contributing: list[Contribution] = []
    for entry in versions.entries():
        branch = production_branch(entry.ver)
        try:
            ref = backend.resolve_ref(branch)
        except RefResolutionError:
            log.info(
                "production-branch-unavailable",
                ver=entry.ver,
                branch=branch,
            )
            continue
        changelog = backend.read_file(ref, CHANGELOG_PATH)
        if changelog is None:
            log.info("branch-changelog-missing", ver=entry.ver, branch=branch)
            continue
        sections = split_releases(changelog)
        if release_id not in sections:
            log.info(
                "release-not-in-branch",
                ver=entry.ver,
                branch=branch,
                release=release_id,
            )
            continue
        impact, platform = transform_section(
            parse_section(sections[release_id]), entry.ver
        )
        chain = (
            derive_release_chain(backend, branch, release_id)
            if detailed
            else None
        )
        contributing.append(
            Contribution(
                ver=entry.ver,
                branch=branch,
                impact=impact,
                platform=platform,
                chain=chain,
            )
        )
        log.info(
            "release-section-found",
            ver=entry.ver,
            branch=branch,
            release=release_id,
        )
    return contributing


def _collect_mode_page(
    versions: VersionSet, repo: Path, backend: HgBackend | GitBackend | None
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str]]:
    """(impact_blocks, platform_blocks, detailed_lines) from fragments."""
    fragment_dir = repo / "changelog.d"
    fragments = (
        sorted(fragment_dir.glob(FRAGMENT_GLOB))
        if fragment_dir.is_dir()
        else []
    )
    if not fragments:
        msg = (
            f"no fragments to collect in {fragment_dir} -- either the "
            "release was never collected (no production branch carries it) "
            "or changelog.d/ is empty"
        )
        raise RuntimeError(msg)
    ver = versions.stable.ver
    collected = collect_fragments(fragment_dir)
    impact_blocks = (
        [(ver, "\n\n".join(collected.impact))] if collected.impact else []
    )
    platform_body = "\n\n".join(collected.platform)
    diff_lines = _collect_mode_diff(versions, repo, backend, ver)
    platform_blocks = [(ver, with_pull_block(platform_body, diff_lines))]
    log.info(
        "release-notes-skeleton",
        version=ver,
        fragments=collected.count,
        publish_target="working tree",
    )
    return impact_blocks, platform_blocks, []


def _collect_mode_diff(
    versions: VersionSet,
    repo: Path,
    backend: HgBackend | GitBackend | None,
    ver: str,
) -> list[str]:
    """Package diff of the prepared release: last collect commit vs tree.

    The old side needs the seam (the last "Collect changelog fragments"
    commit of the stable production branch); the new side is the working
    tree's ``release/package-versions.json``. Without a seam -- a sandbox
    without VCS, or a clone without the production branch -- the block is
    skipped with a warning instead of guessed.
    """
    new_path = repo / PACKAGE_VERSIONS_JSON
    if not new_path.is_file():
        log.warning(
            "package-diff-skipped",
            reason=f"no {PACKAGE_VERSIONS_JSON} in the working tree",
            repo=str(repo),
        )
        return []
    new_pkgs = package_versions_json(new_path.read_text(encoding="utf-8"))
    branch = production_branch(versions.stable.ver)
    old_rev = None
    if backend is not None:
        try:
            ref = backend.resolve_ref(branch)
            commits = collect_commits(backend, ref, branch)
            old_rev = commits[0] if commits else None
        except (RefResolutionError, VcsError) as exc:
            log.info(
                "collect-base-unavailable",
                branch=branch,
                reason=str(exc)[:200],
            )
    if old_rev is None:
        log.warning(
            "package-diff-skipped",
            reason=(
                f"no collect commit resolvable on {branch} -- the skeleton "
                "ships without the Pull-upstream block"
            ),
            version=ver,
        )
        return []
    assert backend is not None  # old_rev only resolves through the seam
    old_pkgs = _json_at(backend, old_rev, PACKAGE_VERSIONS_JSON)
    important_raw = _json_at(backend, old_rev, IMPORTANT_PACKAGES_JSON)
    if old_pkgs is None:
        log.warning(
            "package-diff-skipped",
            reason=f"{PACKAGE_VERSIONS_JSON} unreadable at the collect base",
            old=old_rev[:12],
        )
        return []
    important = set(important_raw) if isinstance(important_raw, list) else None
    lines = (
        package_diff(old_pkgs, new_pkgs, important)
        if isinstance(new_pkgs, dict)
        else []
    )
    log.info("package-diff-rendered", count=len(lines))
    return lines


def run_release_notes(
    config_path: Path,
    repo: Path,
    release_id: str,
    publish_date: str,
    *,
    out: Path = DOC_ROOT / "src",
    force: bool = False,
    dry_run: bool = False,
    detailed: bool = True,
    channel_url_fn=fetch_channel_url,
) -> str:
    """Render (and write, unless *dry_run*) the r-file for *release_id*.

    History mode when a production branch carries the release, collect
    mode (working-tree fragments) otherwise. Raises ``ValueError`` for a
    malformed release id / publish date, ``RuntimeError`` when neither
    mode has data, ``FileExistsError`` when the target exists and
    *force* is False, :class:`tools.vcs_backend.VcsError` on seam
    failures. Returns the rendered page text.
    """
    if not _RELEASE_ID.fullmatch(release_id):
        raise ValueError(
            f"release id must be of the form YYYY_NNN: {release_id!r}"
        )
    if not _PUBLISH_DATE.fullmatch(publish_date):
        raise ValueError(
            f"publish date must be of the form YYYY-MM-DD: {publish_date!r}"
        )
    versions = load_versions(config_path)

    backend: HgBackend | GitBackend | None = None
    try:
        backend = detect_backend(repo)
    except NoVcsBackendError:
        log.info(
            "collect-mode-no-vcs",
            repo=str(repo),
            reason="no .hg/ and no .git/ -- reading working-tree fragments",
        )

    contributing = (
        _find_contributions(backend, versions, release_id, detailed=detailed)
        if backend is not None
        else []
    )

    if contributing:
        assert backend is not None  # contributions come from the seam only
        impact_blocks: list[tuple[str, str]] = []
        platform_blocks: list[tuple[str, str]] = []
        for contribution in contributing:
            if contribution.impact:
                impact_blocks.append((contribution.ver, contribution.impact))
            if contribution.platform is not None:
                body = contribution.platform
                if detailed and contribution.chain is not None:
                    diff_lines = release_package_diff(
                        backend, contribution.chain
                    )
                    body = with_pull_block(strip_pull_block(body), diff_lines)
                platform_blocks.append((contribution.ver, body))
        # r035 pattern: sections ascending by version (21.05 before 24.05).
        impact_blocks.sort(key=lambda item: item[0])
        platform_blocks.sort(key=lambda item: item[0])
        detailed_lines = (
            render_detailed_changes(
                backend,
                [(c.ver, c.branch) for c in contributing],
                release_id,
                channel_url_fn=channel_url_fn,
            )
            if detailed
            else []
        )
    else:
        impact_blocks, platform_blocks, detailed_lines = _collect_mode_page(
            versions, repo, backend
        )

    text = render_release(
        release_id, publish_date, impact_blocks, platform_blocks, detailed_lines
    )

    year, num = release_id.split("_")
    target = out / "changes" / year / f"r{int(num):03d}.md"
    if dry_run:
        log.info("release-page-dry-run", would_write=str(target))
        return text
    if target.exists() and not force:
        raise FileExistsError(
            f"release page already exists: {target} (use --force to overwrite)"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    log.info("release-page-written", path=str(target), release=release_id)
    return text


# Minimum log level for the CLI (matches logging.INFO; the int literal keeps
# the tool free of an ``import logging`` per the project's structlog-only
# rule).
_INFO_LEVEL = 20


def _configure_logging() -> None:
    """Render human-readable diagnostics to stderr.

    stderr, resolved at call time: ``make`` surfaces a failing
    prerequisite's stderr verbatim while stdout stays clean for
    ``--dry-run`` output -- and pytest's capsys captures it
    (capture_logs around ``main()`` does NOT work: this
    reconfiguration clobbers it).
    """
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
    """CLI entry: ``python -m tools.release_notes``.

    Exit codes: ``0`` (page rendered -- written or printed), ``1``
    (no data for the release, seam failure, existing target without
    ``--force``), ``2`` (malformed release id / publish date, invalid
    platform-versions.toml).
    """
    _configure_logging()
    parser = argparse.ArgumentParser(
        prog="release_notes",
        description=(
            "Generate src/changes/<year>/rNNN.md from branch changelogs, "
            "the package diff and (for uncollected releases) the working-"
            "tree changelog.d fragments."
        ),
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=REPO_ROOT,
        help="Repository with the branch changelogs and release metadata "
        "(default: doc/'s parent)",
    )
    parser.add_argument("config", type=Path, metavar="platform-versions.toml")
    parser.add_argument("release", metavar="RELEASE")
    parser.add_argument(
        "--publish-date",
        metavar="YYYY-MM-DD",
        default=None,
        help="Publish date (default: next Monday)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the rendered page to stdout instead of writing it",
    )
    parser.add_argument(
        "--no-detailed",
        dest="detailed",
        action="store_false",
        help="Skip the Detailed Changes section and the VCS-chain-derived "
        "package diff",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DOC_ROOT / "src",
        help="src tree root to place changes/<year>/rNNN.md in "
        "(default: doc/src)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing release page",
    )
    args = parser.parse_args(argv)

    publish_date = args.publish_date or next_monday().isoformat()
    try:
        text = run_release_notes(
            args.config,
            args.repo,
            args.release,
            publish_date,
            out=args.out,
            force=args.force,
            dry_run=args.dry_run,
            detailed=args.detailed,
        )
    except ValueError as exc:
        log.error("release-notes-invalid", error=str(exc))
        return 2
    except (VcsError, RuntimeError, FileExistsError, OSError) as exc:
        log.error("release-notes-failed", error=str(exc))
        return 1
    if args.dry_run:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
