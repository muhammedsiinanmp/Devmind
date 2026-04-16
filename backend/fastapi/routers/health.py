from fastapi import APIRouter
from sqlalchemy import text
from core.database import AsyncSessionLocal

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"

    return {"status": "ok", "db": db_status}
