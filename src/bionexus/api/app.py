"""BioNexus web API: a thin FastAPI layer over the engine.

One uvicorn process serves the typed REST contract (`/api/v1`, see
`api/v1/schemas.py`) and the built SPA. All state lives in the existing
registry and provenance stores; nothing here owns logic.
"""
from __future__ import annotations

import hmac
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI(title="BioNexus API", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:5173"],
    allow_methods=["*"], allow_headers=["*"])

# ---- state-changing-request guard (approvals, halt, launch, delete ...)
# The API is a local control surface with no user accounts. Two cheap
# defences against drive-by browser attacks on localhost: a request that
# carries an Origin/Host must be local, and when BIONEXUS_API_TOKEN is set
# every mutating call must present it (X-BioNexus-Token).
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1", "testserver"}


@app.middleware("http")
async def _guard_mutations(request: Request, call_next):
    import os
    from urllib.parse import urlparse
    from fastapi.responses import JSONResponse
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
    if host and host not in _LOCAL_HOSTS and \
            not os.environ.get("BIONEXUS_ALLOW_REMOTE"):
        return JSONResponse({"detail": "non-local Host refused"}, 403)
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin and (urlparse(origin).hostname or "") not in _LOCAL_HOSTS:
            return JSONResponse({"detail": "cross-origin write refused"}, 403)
        users = _api_tokens()
        if users:
            presented = request.headers.get("x-bionexus-token") or ""
            who = next((u for t, u in users.items()
                        if hmac.compare_digest(t, presented)), None)
            if who is None:
                return JSONResponse({"detail": "API token required"}, 401)
            request.state.user = who
    return await call_next(request)


def _api_tokens() -> dict[str, str]:
    """token -> person. BIONEXUS_API_TOKENS="alice:tok1,bob:tok2" gives
    per-person identity (approvals are attributed to the token's owner);
    the single BIONEXUS_API_TOKEN maps to the user 'operator'. No tokens
    configured = open local mode."""
    import os
    out: dict[str, str] = {}
    for part in (os.environ.get("BIONEXUS_API_TOKENS") or "").split(","):
        name, sep, tok = part.strip().partition(":")
        if sep and name and tok:
            out[tok] = name
    single = os.environ.get("BIONEXUS_API_TOKEN")
    if single:
        out.setdefault(single, "operator")
    return out


from bionexus.api.v1 import router as v1_router  # noqa: E402
app.include_router(v1_router)


@app.get("/api/system/health")
def health() -> dict:
    return {"ok": True, "provenance_db": Path("bionexus.db").exists()}


_web_dist = Path(__file__).resolve().parents[3] / "web" / "dist"
if _web_dist.exists():                                    # pragma: no cover
    from fastapi.staticfiles import StaticFiles
    app.mount("/assets", StaticFiles(directory=str(_web_dist / "assets")),
              name="spa-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """BrowserRouter deep links: real files serve, everything else
        (non-API client routes like /experiments/<eid>) gets the SPA shell.
        Registered last — concrete /api routes above always win."""
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(404, "no such endpoint")
        candidate = (_web_dist / full_path).resolve()
        if (full_path and candidate.is_file()
                and candidate.is_relative_to(_web_dist.resolve())):
            return FileResponse(candidate)
        return FileResponse(_web_dist / "index.html")
