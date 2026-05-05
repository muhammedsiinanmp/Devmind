"""
Embeddings router for vector store operations.

Endpoints for storing and searching code embeddings.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from core.database import AsyncSessionLocal
from services.vector_store import (
    vector_store,
    VectorStoreError,
    SimilarChunk,
)

router = APIRouter(prefix="/embeddings", tags=["embeddings"])


class StoreEmbeddingRequest(BaseModel):
    """Request to store code embedding."""

    repo_full_name: str
    file_path: str
    chunk_text: str
    language: str = "python"
    chunk_type: str = "function"


class StoreEmbeddingResponse(BaseModel):
    """Response after storing embedding."""

    id: int
    repo_full_name: str
    file_path: str
    chunk_text: str
    language: str
    chunk_type: str


class SearchRequest(BaseModel):
    """Request to search embeddings."""

    q: str
    repo: str
    top_k: int = 5
    threshold: float = 0.6


class SearchResponse(BaseModel):
    """Search results response."""

    results: list[dict]


@router.post("/store", response_model=StoreEmbeddingResponse)
async def store_embedding(request: StoreEmbeddingRequest):
    """
    Store code chunk embedding.

    Takes a code chunk and stores its embedding in pgvector.
    """
    try:
        from core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            embedding = await vector_store.store_code_embedding(
                session=session,
                repo_full_name=request.repo_full_name,
                file_path=request.file_path,
                chunk_text=request.chunk_text,
                language=request.language,
                chunk_type=request.chunk_type,
            )

            return StoreEmbeddingResponse(
                id=embedding.id,
                repo_full_name=embedding.repo_full_name,
                file_path=embedding.file_path,
                chunk_text=embedding.chunk_text[:100],
                language=embedding.language,
                chunk_type=embedding.chunk_type,
            )

    except VectorStoreError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/search", response_model=SearchResponse)
async def search_embeddings(request: SearchRequest):
    """
    Search for similar code chunks.

    Takes a query text and returns top-k similar chunks with similarity scores.
    """
    try:
        from core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            results = await vector_store.search_similar(
                session=session,
                query_text=request.q,
                repo_full_name=request.repo,
                top_k=request.top_k,
                threshold=request.threshold,
            )

            return SearchResponse(
                results=[
                    {
                        "chunk_text": r.chunk_text,
                        "file_path": r.file_path,
                        "language": r.language,
                        "similarity": r.similarity,
                        "chunk_type": r.chunk_type,
                    }
                    for r in results
                ]
            )

    except VectorStoreError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/search", response_model=SearchResponse)
async def search_get(
    q: str,
    repo: str,
    top_k: int = 5,
    threshold: float = 0.6,
):
    """
    Search for similar code chunks (GET version).

    Takes a query text and returns top-k similar chunks with similarity scores.
    """
    try:
        from core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            results = await vector_store.search_similar(
                session=session,
                query_text=q,
                repo_full_name=repo,
                top_k=top_k,
                threshold=threshold,
            )

            return SearchResponse(
                results=[
                    {
                        "chunk_text": r.chunk_text,
                        "file_path": r.file_path,
                        "language": r.language,
                        "similarity": r.similarity,
                        "chunk_type": r.chunk_type,
                    }
                    for r in results
                ]
            )

    except VectorStoreError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
