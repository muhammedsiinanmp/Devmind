from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from core.database import AsyncSessionLocal
from services.llm_client import MODEL_CHAIN, check_provider_health

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
    except Exception as exc:
        checks["database"] = f"error: {exc}"
        checks["pgvector"] = "unknown"

    # LLM providers — informational only, failover chain handles degradation
    for config in MODEL_CHAIN:
        provider, is_healthy = await check_provider_health(config)
        checks[f"llm_{provider}"] = "ok" if is_healthy else "unreachable"

    # DB down or pgvector missing → 503 so ECS/k8s stops routing traffic here
    critical_ok = checks.get("database") == "ok" and checks.get(
        "pgvector", ""
    ).startswith("ok")
    overall = "ok" if critical_ok else "degraded"
    status_code = 200 if critical_ok else 503

    return JSONResponse(
        {"status": overall, "checks": checks},
        status_code=status_code,
    )
