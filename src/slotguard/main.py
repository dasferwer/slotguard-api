import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request

from slotguard.api.router import api_router
from slotguard.config import get_settings

settings = get_settings()
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("slotguard.http")

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    summary="Room booking API with conflict protection and role-based access control",
    docs_url="/docs",
    redoc_url="/redoc",
)
app.include_router(api_router)


@app.middleware("http")
async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    started_at = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_id=%s method=%s path=%s status=%s duration_ms=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "docs": "/docs",
        "health": "/health",
    }
