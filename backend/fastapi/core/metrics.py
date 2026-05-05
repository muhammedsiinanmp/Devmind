"""
Prometheus metrics for FastAPI services.
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

embedding_calls = Counter(
    "embedding_calls_total",
    "Total number of embedding API calls",
)

llm_provider_requests = Counter(
    "llm_provider_requests_total",
    "LLM requests by provider",
    ["provider"],
)

review_requests_total = Counter(
    "review_requests_total",
    "Total review requests",
)

review_errors_total = Counter(
    "review_errors_total",
    "Review errors by type",
    ["error_type"],
)
