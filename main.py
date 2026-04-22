import time
import uuid
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
import re
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
import uvicorn

from app.database import engine, Base
from app import models  # noqa

from app.routers import (
    auth_router,
    budget_router,
    approval_router,
    dashboard_router,
    dummy_router,
    import_router,
    search_router,
)
from app.logger import app_logger, error_logger, new_correlation_id

# Create all DB tables on startup (including new audit_logs table)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title   = "RBL Bank IT Budget Portal",
    version = "1.1.0",
    docs_url= "/docs",
    redoc_url= "/redoc",
)

templates = Jinja2Templates(directory="app/templates")

def highlight(text, query):
    if not text or not query:
        return text

    pattern = "|".join(re.escape(word) for word in query.split())

    highlighted = re.sub(
        f"({pattern})",
        r"<mark>\1</mark>",
        text,
        flags=re.IGNORECASE
    )
    return Markup(highlighted)


templates.env.filters["highlight"] = highlight

# ── Request Logging Middleware ────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Log every HTTP request with:
    - Correlation ID (unique per request)
    - Method + path
    - Response status code
    - Duration in ms

    Sensitive paths (login POST) are logged without body.
    """
    corr_id   = new_correlation_id()
    start     = time.time()
    method    = request.method
    path      = request.url.path

    # Attach correlation ID to request state for downstream use
    request.state.correlation_id = corr_id

    # Log incoming request (skip static files noise)
    if not path.startswith("/static"):
        app_logger.info(
            f"→ {method} {path}",
            extra={
                "extra": {
                    "correlation_id": corr_id,
                    "method"        : method,
                    "path"          : path,
                    "client_ip"     : request.client.host if request.client else "unknown",
                }
            }
        )

    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        error_logger.error(
            f"UNHANDLED EXCEPTION: {method} {path} — {exc}",
            extra={
                "extra": {
                    "correlation_id": corr_id,
                    "method"        : method,
                    "path"          : path,
                    "duration_ms"   : duration_ms,
                }
            },
            exc_info=True,
        )
        raise

    duration_ms = int((time.time() - start) * 1000)

    if not path.startswith("/static"):
        level = "WARNING" if response.status_code >= 400 else "INFO"
        app_logger.info(
            f"← {method} {path} [{response.status_code}] {duration_ms}ms",
            extra={
                "extra": {
                    "correlation_id": corr_id,
                    "method"        : method,
                    "path"          : path,
                    "status_code"   : response.status_code,
                    "duration_ms"   : duration_ms,
                }
            }
        )

    # Add correlation ID to response headers (useful for debugging)
    response.headers["X-Correlation-ID"] = corr_id
    return response


# ── Static files & Routers ────────────────────────────────────
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_router.router,     prefix="/auth",      tags=["Auth"])
app.include_router(dashboard_router.router,prefix="/dashboard", tags=["Dashboard"])
app.include_router(budget_router.router,   prefix="/budget",    tags=["Budget"])
app.include_router(approval_router.router, prefix="/approval",  tags=["Approvals"])
app.include_router(import_router.router,   prefix="/import",    tags=["Import"])
app.include_router(dummy_router.router,    prefix="/dummy",     tags=["Future"])
app.include_router(search_router.router, prefix="/search", tags=["Search"])

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/auth/login")


@app.get("/health", tags=["System"])
async def health():
    """Health check — used by monitoring tools."""
    return {
        "status" : "healthy",
        "app"    : "RBL Bank IT Budget Portal",
        "version": "1.1.0",
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)