"""Serve the built frontend from the API process (FRONTEND_DIST_DIR), for one-container
hosting such as a free Hugging Face Space or Render web service.

Behaves like frontend/nginx.conf: hashed /assets/* are cached immutably, every other
unknown path falls back to index.html (client-side routing) with the same
Content-Security-Policy, and nothing outside the dist directory -- or under /api -- is
ever served from here.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

# Same policy as frontend/nginx.conf without a map tile host; the container build
# writes the exact nginx policy (with the tile host) to FRONTEND_CSP_FILE instead.
DEFAULT_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
    "media-src 'self' blob:; connect-src 'self'; font-src 'self'; object-src 'none'; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


def build_csp(csp_file: str, frame_ancestors: str) -> str:
    csp = DEFAULT_CSP
    if csp_file:
        csp = " ".join(Path(csp_file).read_text(encoding="utf-8").split())
    if frame_ancestors.strip():
        csp = csp.replace("frame-ancestors 'none'", "frame-ancestors " + " ".join(frame_ancestors.split()))
    return csp


def mount_frontend(app: FastAPI, dist_dir: str, csp_file: str = "", frame_ancestors: str = "") -> None:
    root = Path(dist_dir).resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"FRONTEND_DIST_DIR has no index.html: {root}")
    csp = build_csp(csp_file, frame_ancestors)
    html_headers = {"Content-Security-Policy": csp, "Cache-Control": "no-cache"}

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def frontend(path: str, request: Request):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        if path:
            candidate = (root / path).resolve()
            inside = candidate.is_relative_to(root)
            hidden = any(part.startswith(".") for part in Path(path).parts)
            if inside and not hidden and candidate.is_file():
                if candidate.parent == root / "assets":
                    return FileResponse(candidate, headers={"Cache-Control": "public, max-age=31536000, immutable"})
                return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
            if path.startswith("assets/"):
                raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(index, headers=html_headers)
