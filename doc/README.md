# Flying Circus Platform Documentation

This directory builds the public manual of the Flying Circus NixOS
platform, infrastructure, components, Directory API, and changelog.
The documentation lives inside the `fc-nixos` repo, so `doc/src/`
always matches the code of the current platform branch.

Where the result is served:

- Production: <https://docs.flyingcircus.io> (built from the default branch)
- Staging: <https://doc.fcdocstag.fcio.net>

## Tech

- [Zensical](https://github.com/flyingcircusio/zensical) (Rust core,
  Python CLI), classic theme variant; local template overrides in
  `theme/` (the logo anchors link the manual index)
- Python-Markdown with pymdownx extensions; MyST `%` comment lines are
  stripped before parsing (the `md_comments` markdown extension)
- Self-hosted assets: fonts and the glightbox runtime are vendored
  under `src/_static/vendor/` -- no page loads anything from a CDN;
  content images get click-to-zoom via glightbox
- `use_directory_urls = false`: pages serve at `/<path>.html` URLs.
  Internal links must therefore target `.md` pages -- only those are
  rewritten to `.html` and link-validated by the build (this is why
  the snapshot banners emit `.md` links; see below)
- Build tooling via [appenv](https://github.com/flyingcircusio/appenv):
  a single-file Python tool that pins the environment from
  `pyproject.toml` / `uv.lock`.

## Development

No install step: `appenv` builds the venv on first use, every later
run reuses it. `./zensical` is a symlink to appenv.

### Live preview

```bash
make serve
```

Places the version snapshots and generates the switcher payload
first, then starts a live-reload server at `http://localhost:8000` --
edits in `src/` appear in the browser immediately. Prefer this over a
bare `./zensical serve`: on a fresh clone that would serve without
snapshots and switcher data.

### Full build

```bash
make    # checkout-versioned-docs -> gen-platform-versions -> html
```

| Target | Effect |
| --- | --- |
| `make` | Full pipeline: place snapshots, generate switcher data, build HTML into `_build/` |
| `make serve` | Placement + switcher data, then the live preview server |
| `make checkout-versioned-docs` | Places version snapshots under `src/<ver>/` from the revisions in `platform-versions.toml` |
| `make gen-platform-versions` | Regenerates `src/_static/platform-versions.js` (switcher payload) from `platform-versions.toml` and the page inventory |
| `make html` | Builds the static HTML into `_build/` |
| `make test` | Runs the test suite in `tests/` (see [Tests](#tests)) |
| `make clean` | Removes `_build/`, the placed `src/<ver>/` trees, and the placement manifest |

### Running tools directly

```bash
./zensical build
./zensical serve
./appenv python -m tools.checkout_versioned_docs
./appenv python -m tools.gen_platform_versions
./appenv python -m tools.scaffold_page ...     # see "Adding a component page"
./appenv python -m tools.release_notes ...     # see "Release notes"
```

## Versioned documentation

The manual is versioned like the platform: the documentation lives in
`doc/src/` of the platform repo, so each platform branch carries the
docs that match its code. `platform-versions.toml` names the versions
to publish -- the build places ONE of them as the manual at `/` and
every other as a read-only snapshot under `/<ver>/`. A reader on an
older platform release reads the documentation of exactly that
release, at a stable URL.

### URL layout

| URL | Serves |
| --- | --- |
| `/` | manual index (the matched version) |
| `/components/ferretdb.html` | manual page |
| `/25.11/` | snapshot index |
| `/25.11/components/ferretdb.html` | the same page, 25.11 snapshot |
| `/de/security/data-protection.html` | German tree (unversioned) |

The sidebar version switcher appears only on pages that at least one
snapshot also carries -- common pages (security policies, support)
get no flyout at all (details in the switcher section below).

### Version switcher

The `src/_static/platform-versions.js` payload is **generated** by
`make gen-platform-versions` -- never edit it by hand. Releases and
sunsets are configured exclusively in `platform-versions.toml`. The
payload is master-centric and inverted:

```json
{
  "master": "26.05",
  "versions": {"<ver>": {"label": "...", "status": "...", "index": "/"}},
  "pages": {"<page-id>": ["<ver>", "..."]}
}
```

`master` is the matched entry's version (the manual built at `/`);
`pages` has keys only for master pages carried by at least one
snapshot, each value listing the carrying snapshot versions (without
the master) in canonical TOML order. A page present only in the
master tree is a common page without its own switcher; a snapshot
page without a master equivalent is excluded from the payload and
triggers the generator's `snapshot-extra-pages` warning. The version
switcher therefore only ever offers versions that verifiably carry
the current page.

### Configuration

Versions are driven by `platform-versions.toml`: a `[stable]` entry,
`[[prerelease]]` and `[[sunsetting]]` entries, each naming a version
and a **rev** -- an hg bookmark locally, a git mirror branch in CI.

**The matched rev decides what you are building:** the entry whose
`rev` is matched IS the local manual at `/` and is never checked out.
Every other entry becomes a snapshot under `src/<ver>/` pulled from
its own branch. An unresolvable match fails the build loudly; there
is no fallback -- neither for rev resolution nor for the snapshot
shapes:

| Category | Public lifecycle | Snapshot source | Placement treatment |
| --- | --- | --- | --- |
| `[stable]` (not matched) | previous stable release | namespaced `doc/src/<ver>/**` | warning banner + `search: exclude` |
| `[[prerelease]]` | upcoming release | whole `doc/src/**` | pages stay untouched |
| `[[sunsetting]]` | version in phase-out | namespaced `doc/src/<ver>/**` | warning banner + `search: exclude` |

The namespaced shape comes from the branch's one-time **sunset move
commit** (`hg mv doc/src doc/src/<ver>`); a non-prerelease revision
without that directory fails the build loudly with the remediation
hint. Banner pages link the counterpart in the built manual when it
exists locally, and the banner emits `.md` targets -- zensical
rewrites them to `.html` and validates them; extensionless targets
would pass through raw and 404 under static hosting.

Rev resolution is auto-detected at the repository path:

- **hg (local):** the ACTIVE bookmark (`hg su`) selects the manual.
  `tools/checkout_versioned_docs.py` resolves bookmarks strictly
  locally (no pull, no network) and exports the snapshots under
  `src/<ver>/`.
- **git (CI):** the TOML `rev`s ARE the GitHub mirror branch names,
  resolved as `refs/remotes/origin/<branch>` of a full clone. The
  matched ref comes from `--matched`, falling back to
  `GITHUB_REF_NAME` (the branch GitHub Actions built); with neither
  set the build fails loudly.

### Content fixes and the rollback contract

At placement, `tools/snapshot_content_fixes.py` rewrites known-stale
content in the placed trees: per-page string pairs and global
substitutions (the build logs `content-fixes-applied pages=N`).

Why a fix table instead of only fixing the branches:
`platform-versions.toml` may point at ANY revision that carries the
namespaced tree -- a rollback can select a revision older than any
branch-side fix. The pairs are permanent insurance: typically dead at
the branch tips (the fix landed there as a backport commit), but live
for every historical revision in between.
`tests/test_rollback_coverage.py` pins this contract against the
oldest namespaced revisions -- every pair must still fire there.

### Operational notes

- **Branch hops need a clean tree:** `src/<ver>/` snapshots are
  ignored artifacts locally, but the version branches track those
  paths. `hg up <other-branch>` fails with "untracked file differs"
  while snapshots are placed -- run `make clean` first.
- **Skip/redo:** the placement manifest records node + tool
  fingerprint per version; an unchanged state is skipped. Editing a
  tool flips the fingerprint and re-places idempotently.
- **No fallback, anywhere:** unresolvable revs, wrong snapshot
  shape, missing snippets -- the pipeline fails loudly instead of
  degrading silently.

### Lifecycle

Compact rules; the tools above do the mechanical part:

- **Upcoming release:** add a `[[prerelease]]` entry (ver + rev); its
  documentation comes from that branch's `doc/src/`.
- **Promotion:** move `[stable]` to the new version. The previous
  stable becomes `[[sunsetting]]` once its branch has the one-time
  sunset move commit -- the namespaced shape is mandatory from then
  on.
- **Global texts** (security policies, support guidelines) live in
  the stable tree; older snapshots keep their own copies for
  contextual integrity, and their banners link the stable
  counterparts. Keeping those copies correct is backport discipline
  on the version branches.
- **Version branches stay buildable but clean:** never commit
  `.appenv/` state there; content fixes that matter at the tip go as
  backport commits on the branch -- the fix table covers the
  historical revisions below the tip (see the rollback contract).

## Writing documentation

### Tree layout

| Path | State | Content |
| --- | --- | --- |
| `src/` | committed | English manual pages |
| `src/de/` | committed | German pages, served at `/de/<path>/`, each cross-links its English twin |
| `src/changes/` | committed | release-note pages `<year>/r<NNN>.md` + generated `index.md` |
| `snippets/` | committed | shared text fragments (see [Snippets](#snippets)) |
| `theme/`, `src/_static/` | committed | theme overrides, CSS/JS, vendored fonts and lightbox |
| `zensical.toml` | committed | build config + hand-maintained nav |
| `src/<NN.NN>/` | generated, ignored | placed version snapshots |
| `src/_static/platform-versions.js` | generated, ignored | switcher payload |
| `src/.checkout-manifest.json` | generated, ignored | placement fingerprints (skip/redo bookkeeping) |

### Navigation

The nav in `zensical.toml` is hand-maintained. A page missing from it
is still built, but not linked -- zensical does not warn about unlisted
pages. Unlisted by design: `index.md` (reached via logo and site
title), `devopsguide-de.md` (linked from dead media), and the German
tree `src/de/`. When you add a page, add its nav entry in the same
change -- component pages get both from one command (next section).

Pages that must stay out of the search index carry
`search: exclude: true` frontmatter: the German tree and every
annotated snapshot page (injected automatically at placement).

### Adding a component page

```bash
./appenv python -m tools.scaffold_page <name> --group "Databases"   # + optional --title
```

creates `src/components/<name>.md` as a house-convention stub (H1 with
`{ #nixos-<name> }` anchor, role-option fence, `sudo fc-manage
switch` hint) and inserts the nav entry alphabetically into the given
`Components` group. Removing a component (it no longer exists in the
current platform version) works on the same two artifacts:

```bash
./appenv python -m tools.scaffold_page <name> --remove
```

replaces the page with a tombstone (H1 and anchor stay verbatim) and
renames the nav label to `<Label> (removed)`. The page file stays on
purpose: the switcher payload scan is file-existence based, so the
version switcher keeps offering the snapshots' real documentation for
the removed component.

### Snippets

Text that is **identical** on two or more pages belongs in the snippet
library `snippets/` -- one file per notice, named after its topic and
written as the complete admonition including a title:

    !!! warning "Title of the notice"
        The shared text, complete and self-contained. ...

Pages include a snippet right below their H1 via
`--8<-- "<name>.md"` (`pymdownx.snippets` with
`base_path = "snippets"` and `check_paths = true`; see `zensical.toml`
for the warm-cache caveat -- snippet edits surface on cold builds
only).

What does **not** belong there: near-variants (snippets cannot be
parameterized -- one file per variant or no snippet at all), release
notes (frozen history), and the generated snapshot trees under
`src/<ver>/` (their banners are injected by
`tools/checkout_versioned_docs.py`). 


### Release notes

Each release gets a page `src/changes/<year>/r<NNN>.md`:

1. **Generate** -- `./appenv python -m tools.release_notes
   platform-versions.toml 2026_034` renders the page from the VCS
   history (production branches), or -- while the release is being
   prepared -- a skeleton from the working-tree `changelog.d/`
   fragments; `--publish-date YYYY-MM-DD` overrides the date default.
   An existing page is never overwritten; the tool never commits.
2. **Complete manually** -- the release manager refines Impact notes
   and the channel URL (the metadata API may be unreachable) and
   commits the page.
3. **Refresh the index** -- `./appenv python -m tools.gen_changes_index`
   regenerates `src/changes/index.md`; move the nav "Changelog" entry
   in `zensical.toml` to the new page (manual -- the tools do not
   touch the nav).

## Continuous integration

`.github/workflows/docs.yml` builds the manual on every push touching
`doc/**` (and on `workflow_dispatch`) and uploads the HTML as a
workflow artifact; publishing happens elsewhere. The workflow's
action refs are pinned by `tests/test_docs_workflow.py`.

## Tests

```bash
make test
```

runs `uv run pytest tests`: uv creates/syncs the doc venv including
the dev dependency group -- the appenv venv has no pytest.

| Suite | Pins |
| --- | --- |
| `test_checkout_versioned_docs.py` (+ `_units`) | placement contract: matched-rev selection, snapshot shapes, banner, index stubs, skip/redo |
| `test_rollback_coverage.py` | rollback contract: the oldest namespaced revisions still place, fix, and banner correctly |
| `test_gen_platform_versions.py`, `test_active_bookmark_matching.py` | switcher payload generation and matched-rev resolution |
| `test_snapshot_content_fixes.py` | the fix table |
| `test_snippets.py` | every snippet include resolves; no snippet is orphaned |
| `test_de_pages.py` | German tree: reference resolution, search and nav exclusion |
| `test_nav_general.py`, `test_no_dead_layout_refs.py` | nav and theme invariants |
| `test_docs_workflow.py` | CI workflow action pins |
| `test_release_notes.py`, `test_gen_changes_index.py`, `test_scaffold_page.py`, `test_vcs_backend.py` | tool units |

