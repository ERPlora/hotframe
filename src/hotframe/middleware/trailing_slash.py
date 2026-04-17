"""
Trailing slash redirect middleware.

Django uses trailing slashes by default (/login/, /settings/, etc.).
hotframe uses no trailing slashes (/login, /settings, etc.).

This middleware redirects requests with trailing slashes to the
non-trailing-slash URL to ensure compatibility. Browsers, bookmarks,
and HTMX requests from Django Hub templates that use trailing slashes
will seamlessly work.

Excluded paths:
- / (root — handled by its own route)
- /api/* (API routes, no redirect)
- /static/* and /media/* (file serving)
- Paths that don't end with /
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response


class TrailingSlashMiddleware(BaseHTTPMiddleware):
    """Strip trailing slash and redirect (301) for browser compatibility."""

    # Prefixes that should NOT be redirected
    EXCLUDED_PREFIXES = ("/api/", "/static/", "/media/", "/__")

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip: root, no trailing slash, excluded prefixes
        if path == "/" or not path.endswith("/"):
            return await call_next(request)

        for prefix in self.EXCLUDED_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        # Strip trailing slash and redirect
        new_path = path.rstrip("/")
        if not new_path:
            new_path = "/"

        # Preserve query string
        query = request.url.query
        new_url = new_path + (f"?{query}" if query else "")

        # Use 301 for GET/HEAD (cacheable), 307 for POST/PUT/DELETE (preserves method)
        if request.method in ("GET", "HEAD"):
            return RedirectResponse(url=new_url, status_code=301)
        return RedirectResponse(url=new_url, status_code=307)
