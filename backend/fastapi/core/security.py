from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from .config import get_settings

settings = get_settings()

internal_key_header = APIKeyHeader(name="X-Internal-Secret", auto_error=False)


async def verify_internal_token(api_key: str = Security(internal_key_header)) -> str:
    if not api_key or api_key != settings.fastapi_internal_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing internal service token",
        )
    return api_key
