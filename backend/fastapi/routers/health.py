from fastapi import APIRouter
from sqlalchemy import text

from core.database import AsyncSessionLocal
from services.llm_client import MODEL_CHAIN, check_provider_health

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"

    llm_status = {}
    for config in MODEL_CHAIN:
        provider, is_healthy = await check_provider_health(config)
        llm_status[provider] = "ok" if is_healthy else "error"

    return {"status": "ok", "db": db_status, "llm": llm_status}
