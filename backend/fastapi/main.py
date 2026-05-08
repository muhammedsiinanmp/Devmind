from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from core.config import get_settings
from core.logging import configure_logging
from routers.health import router as health_router
from routers.review import router as review_router
from routers.embeddings import router as embeddings_router
from routers.scan import router as scan_router

settings = get_settings()


if settings.sentry_dsn_fastapi:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn_fastapi,
        environment=settings.sentry_environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    yield


app = FastAPI(
    title="DevMind AI Engine",
    version="1.0.0",
    docs_url="/docs" if settings.sentry_environment != "production" else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator().instrument(app).expose(app)

app.include_router(health_router)
app.include_router(review_router)
app.include_router(embeddings_router)
app.include_router(scan_router)
