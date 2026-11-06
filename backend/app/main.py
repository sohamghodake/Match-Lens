import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app import __version__
from app.api import ats, health, matches, resumes
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.retention import sweep_forever
from app.db.session import get_engine

# Uploads are capped at 5 MB; allow some room for multipart framing.
MAX_REQUEST_BYTES = 6 * 1024 * 1024


class RequestSizeLimit:
    """Reject oversized requests from the Content-Length header, before the body is
    read or spooled to disk. The upload route still checks the actual file size."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            length = dict(scope["headers"]).get(b"content-length")
            if length and length.isdigit() and int(length) > self.max_bytes:
                response = JSONResponse({"detail": "Request body too large."}, status_code=413)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    sweeper = asyncio.create_task(sweep_forever()) if app.state.run_sweeper else None
    yield
    if sweeper:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper
    await get_engine().dispose()


def create_app(settings: Settings | None = None, *, run_sweeper: bool = True) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="MatchLens API", version=__version__, lifespan=lifespan)
    app.state.run_sweeper = run_sweeper
    app.dependency_overrides[get_settings] = lambda: settings
    # Added first so it sits inside CORS: the browser can then read the 413.
    app.add_middleware(RequestSizeLimit, max_bytes=MAX_REQUEST_BYTES)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.include_router(health.router)
    app.include_router(resumes.router)
    app.include_router(matches.router)
    app.include_router(ats.router)
    if settings.eval_tools:
        from eval.api import router as eval_router  # local labeling tools only

        app.include_router(eval_router)
    return app


app = create_app()
