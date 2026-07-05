SHELL := /bin/bash

SPEC := kernel.spec

.PHONY: srpm
srpm:
	@set -euo pipefail; \
	out="$(outdir)"; \
	if [[ -z "$$out" ]]; then \
		out="$$(pwd)"; \
	fi; \
	if [[ ! -f "$(SPEC)" ]]; then \
		printf 'missing spec file: %s\n' "$(SPEC)" >&2; \
		exit 1; \
	fi; \
	rel="$$(date -u +%s)"; \
	tmp="$$(mktemp -d)"; \
	trap 'rm -rf "$$tmp"' EXIT; \
	cp "$(SPEC)" "$$tmp/$(SPEC)"; \
	sed -i -E "s/^%global[[:space:]]+buildrel[[:space:]].*/%global buildrel $$rel/" "$$tmp/$(SPEC)"; \
	source_url=; \
	while IFS= read -r line; do \
		case "$$line" in \
			Source0:*) \
				source_url="$${line#Source0:}"; \
				source_url="$${source_url#"$${source_url%%[![:space:]]*}"}"; \
				source_url="$${source_url%%[[:space:]]*}"; \
				break; \
				;; \
		esac; \
	done < <(rpmspec --parse "$$tmp/$(SPEC)"); \
	if [[ -z "$$source_url" ]]; then \
		printf 'missing expanded Source0 in %s\n' "$$tmp/$(SPEC)" >&2; \
		exit 1; \
	fi; \
	curl -L --fail --retry 3 --output "$$tmp/$${source_url##*/}" "$$source_url"; \
	rpmbuild -bs \
		--define "_sourcedir $$tmp" \
		--define "_srcrpmdir $$out" \
		"$$tmp/$(SPEC)"
