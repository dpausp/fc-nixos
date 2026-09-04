"""Build-time tooling for the Flying Circus documentation.

The versioned-docs pipeline: ``tools.checkout_versioned_docs`` places
per-version snapshot trees under ``src/<ver>/`` from strictly local VCS
revisions (hg locally, git mirror branches in CI),
``tools.gen_platform_versions`` regenerates the version-switcher payload
from ``platform-versions.toml`` and the page inventory, and
``tools.vcs_backend`` is the shared hg|git seam. ``tools.md_comments``
strips MyST ``%`` comment lines at build time; ``tools.scaffold_page``
generates and sunsets component pages.
"""
