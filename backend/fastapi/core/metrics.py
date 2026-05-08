"""
Prometheus metrics for FastAPI services.
"""

from prometheus_client import Counter, Histogram, Gauge

rag_pipeline_duration_seconds = Histogram(
    "rag_pipeline_duration_seconds",
    "RAG pipeline duration in seconds",
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60],
)

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

llm_latency_seconds = Histogram(
    "llm_latency_seconds",
    "LLM API call latency in seconds",
    ["provider", "model"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60],
)

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total tokens used across LLM calls",
    ["provider", "model", "type"],
)

review_requests_total = Counter(
    "review_requests_total",
    "Total review requests",
    ["status"],
)

review_errors_total = Counter(
    "review_errors_total",
    "Review errors by type",
    ["error_type"],
)

scan_requests_total = Counter(
    "scan_requests_total",
    "Total repository scan requests",
    ["status"],
)

scan_findings_total = Counter(
    "scan_findings_total",
    "Total security/quality findings from scans",
    ["severity", "category"],
)

active_scans = Gauge(
    "active_scans",
    "Number of scans currently running",
)
