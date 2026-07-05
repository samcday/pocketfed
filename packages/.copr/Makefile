SHELL := /bin/bash

SPEC ?= $(firstword $(wildcard *.spec))

.PHONY: srpm
srpm:
	@set -euo pipefail; \
	out="$(outdir)"; \
	if [[ -z "$$out" ]]; then \
		out="$$(pwd)"; \
	fi; \
	if [[ -z "$(SPEC)" || ! -f "$(SPEC)" ]]; then \
		printf 'missing spec file: %s\n' "$(SPEC)" >&2; \
		exit 1; \
	fi; \
	if ! command -v spectool >/dev/null 2>&1; then \
		dnf install -y rpm-build rpmdevtools; \
	fi; \
	rel="$$(date -u +%s)"; \
	tmp="$$(mktemp -d)"; \
	trap 'rm -rf "$$tmp"' EXIT; \
	cp -a . "$$tmp/src"; \
	cd "$$tmp/src"; \
	if grep -Eq '^%global[[:space:]]+buildrel[[:space:]]+' "$(SPEC)"; then \
		sed -i -E "s/^%global[[:space:]]+buildrel[[:space:]].*/%global buildrel $$rel/" "$(SPEC)"; \
	fi; \
	spectool -g "$(SPEC)"; \
	rpmbuild -bs \
		--define "_sourcedir $$PWD" \
		--define "_srcrpmdir $$out" \
		"$(SPEC)"
