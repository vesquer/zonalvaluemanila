PY ?= $(shell command -v python3.14 || command -v python3.13 || command -v python3.12 || command -v python3.11 || echo python3)
ZV = .venv/bin/zv
.PHONY: setup base test build serve web
setup:
	$(PY) -m venv .venv && .venv/bin/pip install -q -e "engine[dev]"
	cd web && npm install
base:
	./scripts/build_base.sh
test:
	.venv/bin/pytest -q engine/tests
build:
	@test -n "$(PSGC)" || (echo "usage: make build PSGC=<code>"; exit 1)
	$(ZV) validate lgus/$(PSGC)/values.json
	$(ZV) build $(PSGC)
serve:
	cd web && npm run dev
web:
	cd web && npm run build
