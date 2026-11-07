"""
Feedback router: Django sends each DevMind comment's accepted/rejected
verdict here when it changes (issue #74). Internal only (X-Internal-Secret).
"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.security import verify_internal_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/feedback",
    tags=["feedback"],
    dependencies=[Depends(verify_internal_token)],
)


class FeedbackUpsertRequest(BaseModel):
    """A comment's current verdict; a null signal removes its example."""

    comment_id: int = Field(gt=0)
    repo_full_name: str = Field(min_length=1, max_length=200)
    # The PR the comment was on; its own later reviews leave it out.
    pr_number: int = Field(default=0, ge=0)
    signal: Optional[Literal["accepted", "rejected"]] = None
    # Limits well above what Django sends (hunks are cut to 4000 characters),
    # so a bad request can't make FastAPI embed or store huge text.
    file_path: str = Field(default="", max_length=1000)
    line_number: int = 0
    category: str = Field(default="", max_length=50)
    severity: str = Field(default="", max_length=50)
    body: str = Field(default="", max_length=10_000)
    code_hunk: str = Field(default="", max_length=20_000)


class FeedbackUpsertResponse(BaseModel):
    stored: bool
    deleted: int = 0


@router.post("/upsert", response_model=FeedbackUpsertResponse)
async def upsert_feedback(request: FeedbackUpsertRequest):
    """
    Embed and store the comment with its code hunk, replacing an earlier
    example of the same comment, or delete it when the signal is null.
    """
    from core.database import AsyncSessionLocal
    from routers.review import _chunk_text, _source_ref
    from services import feedback_store
    from services.vector_store import vector_store

    try:
        if request.signal is None:
            async with AsyncSessionLocal() as session:
                deleted = await feedback_store.delete_feedback(
                    session, request.comment_id
                )
            return FeedbackUpsertResponse(stored=False, deleted=deleted)

        text = feedback_store.document_text(
            request.file_path, request.code_hunk, request.body, _chunk_text
        )
        if not text.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Nothing to embed: the comment has no body or code hunk.",
            )
        # Embed before opening a session, so no connection waits on the API.
        [embedding] = await vector_store.generate_embeddings(
            [text], task_type="RETRIEVAL_DOCUMENT"
        )
        async with AsyncSessionLocal() as session:
            await feedback_store.replace_feedback(
                session,
                comment_id=request.comment_id,
                repo_full_name=request.repo_full_name,
                signal=request.signal,
                file_path=request.file_path,
                category=request.category,
                severity=request.severity,
                body=request.body,
                code_hunk=request.code_hunk,
                embedding=embedding,
                embedding_model=vector_store.embedding_model,
                source_ref=_source_ref(request.pr_number),
            )
    except HTTPException:
        raise
    except Exception as exc:
        # No values in the log: the body and hunk are repository content.
        logger.error(
            "feedback.upsert_failed comment_id=%s error=%s",
            request.comment_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Feedback was not stored.",
        )

    logger.info(
        "feedback.stored comment_id=%s repo=%s signal=%s",
        request.comment_id,
        request.repo_full_name,
        request.signal,
    )
    return FeedbackUpsertResponse(stored=True)
