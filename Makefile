.PHONY: test api web-dev web-build install

install:            ## python package + web deps
	pip install -e ".[api]" -r <(echo pytest) 2>/dev/null || pip install -e ".[api]" pytest
	cd web && npm install

test:               ## full python suite
	python -m pytest tests/ -q

api:                ## backend + built SPA on :8000
	cd web && npm run build
	PYTHONPATH=src uvicorn bionexus.api.app:app --port 8000

api-dev:            ## backend only (auto-reload)
	PYTHONPATH=src uvicorn bionexus.api.app:app --port 8000 --reload

web-dev:            ## Vite dev server on :5173 (proxies /api to :8000)
	cd web && npm run dev

web-build:          ## production SPA build
	cd web && npm run build
