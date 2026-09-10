.PHONY: all html serve clean test

all: checkout-versioned-docs gen-platform-versions html

gen-platform-versions: 
	./appenv python -m tools.gen_platform_versions

checkout-versioned-docs: 
	./appenv python -m tools.checkout_versioned_docs

html:
	./zensical build

serve: checkout-versioned-docs gen-platform-versions
	./zensical serve

VERSIONED_DIRS := 25.11 26.05

clean:
	rm -rf _build $(VERSIONED_DIRS:%=src/%)
	rm -f src/.checkout-manifest.json

# The doc tests (tests/) need the dev dependency group: appenv builds
# the plain runtime venv (no pytest), so this goes through uv, which
# creates/syncs doc/.venv from pyproject.toml + uv.lock first.
test:
	uv run pytest tests
