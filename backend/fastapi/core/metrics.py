"""
Prometheus metrics for FastAPI services.

Only metrics that are actually recorded live here; HTTP request metrics come
from prometheus-fastapi-instrumentator (see main.py).
"""

from prometheus_client import Counter, Histogram

rag_pipeline_duration = Histogram(
    "rag_pipeline_duration_ms",
    "RAG pipeline duration in milliseconds",
    buckets=[100, 250, 500, 1000, 2500, 5000, 10000],
)

agent_iterations = Counter(
    "agent_iterations_total",
    "Total number of agent iteration attempts",
)

review_errors_total = Counter(
    "review_errors_total",
    "Review errors by type",
    ["error_type"],
)
