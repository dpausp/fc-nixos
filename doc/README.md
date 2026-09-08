# Flying Circus Platform Documentation

This directory contains the documentation for the Flying Circus platform,
built with [Zensical](https://github.com/flyingcircusio/zensical).

The documentation lives directly inside the `fc-nixos` monorepo: `doc/src/`
always matches the OS code of the current branch.

## How to Build and Preview Locally

We use `uv` (via the `appenv` wrapper) to manage dependencies and the Python
environment. You do not need a full Nix environment to build the docs!

1. **Start the local preview server:**
   ```bash
   ./appenv python -m zensical serve -f zensical.toml
   ```
   This will start a local web server at `http://localhost:8000`. It features
   live-reloading: any changes you make to the `.md` files in `src/` will
   instantly appear in your browser.

2. **Build everything (switcher payload, snapshots, HTML):**
   ```bash
   make
   ```
   or run the individual targets:

   | Target | What it does |
   | --- | --- |
   | `make gen-platform-versions` | Regenerates `src/_static/platform-versions.js` from `platform-versions.toml` and the page inventory |
   | `make checkout-versioned-docs` | Places version snapshots under `src/<ver>/` from local revisions |
   | `make html` | Builds the static HTML into `_build/` |

## Documentation Versioning

Versions are driven by `platform-versions.toml`: a `[stable]` entry,
`[[prerelease]]` and `[[sunsetting]]` entries, each naming a version and
a **rev** -- an hg bookmark locally, a git mirror branch in CI. The
categories describe the PUBLIC lifecycle (stable release, upcoming
release, phase-out) -- not who is built.

**The matched rev decides what you are building:** the entry whose `rev`
is matched IS the local manual at `/` and is never checked out. Every
other entry -- including a non-matched `[stable]` -- becomes a snapshot
under `src/<ver>/` pulled from its own branch. An unresolvable match
fails the build loudly; there is no fallback. The VCS backend is
auto-detected at the repository path:

- **hg (local):** the ACTIVE bookmark (`hg su`) selects the manual.
  `tools/checkout_versioned_docs.py` resolves bookmarks **strictly
  locally** (no pull, no network) and exports snapshots under
  `src/<ver>/`.
- **git (CI):** the TOML `rev`s ARE the GitHub mirror branch names,
  resolved as `refs/remotes/origin/<branch>` of a full clone. The
  matched ref comes from `--matched`, falling back to `GITHUB_REF_NAME`
  (the branch GitHub Actions built); with neither set the build fails
  loudly. Export runs via `git archive | tar` with the archive prefix
  stripped.

Snapshot shapes are backend-independent: non-sunsetting snapshot
revisions (prerelease, or a non-matched `[stable]`) are exported from
their whole `doc/src/**` tree, and `[[sunsetting]]` revisions must carry
their docs namespaced at `doc/src/<ver>/**` -- created by the branch's
one-time **sunset move commit** (`hg mv doc/src doc/src/<ver>`). A
sunsetting revision without that directory fails the build loudly with
the remediation hint; there is deliberately **no fallback** to the
whole-tree shape for old versions. Sunsetting pages receive
`search: exclude` frontmatter and a warning banner linking to the
counterpart in the built manual when it exists locally.

## Continuous Integration

`.github/workflows/docs.yml` builds the manual on every push touching
`doc/**` (and on `workflow_dispatch`): full-history checkout (all
mirror branches are needed to resolve the TOML revs), Python 3.13, an
exactly pinned `uv` with a cache keyed on `uv.lock`, then `make` in
`doc/`. The HTML lands in `_build/` and is uploaded as a workflow
artifact; publishing is out of scope for the workflow.

## Version Switcher

The `src/_static/platform-versions.js` payload is **generated** by
`make gen-platform-versions` -- never edit it by hand. Releases and sunsets
are configured exclusively in `platform-versions.toml`. The payload is
master-centric and inverted:

```json
{
  "master": "26.05",
  "versions": {"<ver>": {"label": "...", "status": "...", "index": "/"}},
  "pages": {"<page-id>": ["<ver>", "..."]}
}
```

`master` is the matched entry's version (the manual built at `/`);
`pages` has keys only for master pages carried by at least one snapshot,
each value listing the carrying snapshot versions (without the master) in
canonical TOML order. A page present only in the master tree is a common
page without its own switcher; a snapshot page without a master equivalent
is excluded from the payload and triggers the generator's
`snapshot-extra-pages` warning. The version switcher therefore only ever
offers versions that verifiably carry the current page.

## Cross-Version Documents

Global texts (security policies, support guidelines) live in the stable
tree. Older snapshots keep their own copies for contextual integrity; their
banner links readers to the stable counterpart. Keeping global texts
stable across snapshots is backport discipline on the version branches.

## Shared Content Snippets

Text that is **identical** on two or more pages belongs in the snippet
library `snippets/` -- one file per notice, written as the complete
admonition including a title (`sunsetting-<component>.md` is the naming
model for banners):

    !!! warning "Sunsetting"
        The <component> role is in sunsetting. ...

Pages include a snippet right below their H1 via
`--8<-- "sunsetting-<component>.md"` (`pymdownx.snippets` with
`base_path = "snippets"` and `check_paths = true`; see `zensical.toml`
for the warm-cache caveat -- snippet edits surface on cold builds only).

What does **not** belong there: near-variants (snippets cannot be
parameterized -- one file per variant or no snippet at all), release
notes (frozen history), and the generated snapshot trees under
`src/<ver>/` (their banners are injected by
`tools/checkout_versioned_docs.py`). `tests/test_snippets.py` guards
both directions: every include must resolve to an existing snippet, and
no snippet may be orphaned.
