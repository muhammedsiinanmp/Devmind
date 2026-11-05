import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from core.database import AsyncSessionLocal
from services.llm_client import (
    MODEL_CHAIN,
    cached_model_listed,
    server_provider_models,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    checks: dict[str, str] = {}

    # Database + pgvector extension
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            row = await session.execute(
                text("SELECT extversion FROM pg_extension WHERE extname='vector'")
            )
            pgvector_version = row.scalar_one_or_none()
            checks["database"] = "ok"
            checks["pgvector"] = (
                f"ok ({pgvector_version})"
                if pgvector_version
                else "error: extension not installed"
            )
    except Exception:
        # Log details server-side only; the endpoint is unauthenticated.
        logger.exception("health_check.database_error")
        checks["database"] = "error"
        checks["pgvector"] = "unknown"

    # LLM providers — informational only, failover chain handles degradation.
    # "listed" is null when the provider has no key or its
    # model listing couldn't be fetched. Listings are cached for a few minutes.
    llm: dict[str, dict[str, object]] = {
        provider: {"model": model, "enabled": False, "listed": None}
        for provider, model in server_provider_models().items()
    }
    for config in MODEL_CHAIN:
        provider = config.provider.value
        listed = await cached_model_listed(config)
        llm[provider] = {"model": config.model, "enabled": True, "listed": listed}
        if listed is None:
            checks[f"llm_{provider}"] = "unreachable"
        else:
            checks[f"llm_{provider}"] = "ok" if listed else "model_not_listed"

    # DB down or pgvector missing → 503 so ECS/k8s stops routing traffic here
    critical_ok = checks.get("database") == "ok" and checks.get(
        "pgvector", ""
    ).startswith("ok")
    overall = "ok" if critical_ok else "degraded"
    status_code = 200 if critical_ok else 503

    return JSONResponse(
        {"status": overall, "checks": checks, "llm": llm},
        status_code=status_code,
    )
