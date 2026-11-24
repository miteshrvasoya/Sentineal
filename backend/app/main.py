"""QuantLens API. Educational analysis tool, not investment advice."""
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.api.routes_backtest import router as backtest_router
from app.api.routes_fund import router as fund_router
from app.api.routes_llm import router as llm_router
from app.api.routes_models import router as models_router
from app.api.routes_news import router as news_router
from app.api.routes_scheduler import router as scheduler_router
from app.api.routes_screener import router as screener_router
from app.config import get_settings
from app.data import db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    import asyncio

    from app.deps import _session_ctx
    from app.scheduler import Scheduler, default_jobs
    if db._engine is None:
        db.init_engine()
    s = get_settings()
    app.state.scheduler = Scheduler(_session_ctx, default_jobs(_session_ctx))
    task = asyncio.create_task(app.state.scheduler.loop(s.scheduler_tick_seconds)) if s.scheduler_enabled else None
    yield
    if task:
        task.cancel()


def create_app() -> FastAPI:
    s = get_settings()
    logging.basicConfig(level=s.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = FastAPI(title="QuantLens", version="0.1.0",
                  description="Educational market analysis. Not investment advice.", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_list, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse({"error": "http_error", "detail": str(exc.detail)}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": "validation_error", "detail": str(exc.errors())}, status_code=422)

    app.include_router(router)
    app.include_router(news_router)
    app.include_router(llm_router)
    app.include_router(fund_router)
    app.include_router(models_router)
    app.include_router(backtest_router)
    app.include_router(screener_router)
    app.include_router(scheduler_router)
    return app


app = create_app()
