PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
UVICORN := $(PY) -m uvicorn

.PHONY: test api api-dev web-dev web-build install

install:            ## python package + web deps (in ./.venv — make targets use it)
	@test -d .venv || python3 -m venv .venv
	.venv/bin/pip install -e ".[api]" pytest
	cd web && npm install

test:               ## full python suite
	$(PY) -m pytest tests/ -q

api:                ## backend + built SPA on :8000
	cd web && npm run build
	PYTHONPATH=src $(UVICORN) bionexus.api.app:app --port 8000

api-dev:            ## backend only (auto-reload)
	PYTHONPATH=src $(UVICORN) bionexus.api.app:app --port 8000 --reload

web-dev:            ## Vite dev server on :5173 (proxies /api to :8000)
	cd web && npm run dev

web-build:          ## production SPA build
	cd web && npm run build
