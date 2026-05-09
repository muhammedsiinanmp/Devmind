from prometheus_client import Counter, Histogram, Gauge

review_requests_total = Counter(
    "devmind_review_requests_total",
    "Total number of review requests",
    ["status"],
)

review_duration_seconds = Histogram(
    "devmind_review_duration_seconds",
    "Time taken to complete a review",
    buckets=[1, 5, 10, 30, 60, 120, 300, 600],
)

llm_latency_seconds = Histogram(
    "devmind_llm_latency_seconds",
    "LLM API call latency",
    ["provider", "model"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60],
)

llm_tokens_total = Counter(
    "devmind_llm_tokens_total",
    "Total tokens used across LLM calls",
    ["provider", "model", "type"],
)

llm_requests_total = Counter(
    "devmind_llm_requests_total",
    "Total LLM API requests",
    ["provider", "model", "status"],
)

celery_task_duration_seconds = Histogram(
    "devmind_celery_task_duration_seconds",
    "Celery task execution time",
    ["task_name"],
    buckets=[0.1, 0.5, 1, 5, 10, 30, 60],
)

celery_queue_depth = Gauge(
    "devmind_celery_queue_depth",
    "Number of pending tasks in Celery queue",
    ["queue"],
)

active_reviews = Gauge(
    "devmind_active_reviews",
    "Number of reviews currently being processed",
)

reviews_by_status = Gauge(
    "devmind_reviews_by_status",
    "Number of reviews by status",
    ["status"],
)

risk_score_distribution = Histogram(
    "devmind_risk_score_distribution",
    "Distribution of risk scores",
    buckets=[0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
)

github_comments_posted_total = Counter(
    "devmind_github_comments_posted_total",
    "Total comments posted to GitHub",
    ["status"],
)

kafka_messages_produced_total = Counter(
    "devmind_kafka_messages_produced_total",
    "Total Kafka messages produced",
    ["topic", "status"],
)

kafka_messages_consumed_total = Counter(
    "devmind_kafka_messages_consumed_total",
    "Total Kafka messages consumed",
    ["topic", "status"],
)

error_count_total = Counter(
    "devmind_error_count_total",
    "Total number of errors",
    ["service", "error_type"],
)

scan_requests_total = Counter(
    "devmind_scan_requests_total",
    "Total repository scan requests",
    ["status"],
)

scan_duration_seconds = Histogram(
    "devmind_scan_duration_seconds",
    "Time taken to complete a repository scan",
    buckets=[5, 10, 30, 60, 120, 300, 600, 1800],
)

scan_findings_total = Counter(
    "devmind_scan_findings_total",
    "Total security/quality findings from scans",
    ["severity", "category"],
)

webhook_events_total = Counter(
    "devmind_webhook_events_total",
    "Total GitHub webhook events received",
    ["event_type", "status"],
)


def record_llm_call(
    provider: str, model: str, latency: float, tokens: int, success: bool
):
    status = "success" if success else "error"
    llm_requests_total.labels(provider=provider, model=model, status=status).inc()
    if success:
        llm_latency_seconds.labels(provider=provider, model=model).observe(latency)
        llm_tokens_total.labels(provider=provider, model=model, type="prompt").inc(
            tokens // 2
        )
        llm_tokens_total.labels(provider=provider, model=model, type="completion").inc(
            tokens // 2
        )


def record_review_complete(duration: float, risk_score: int):
    review_duration_seconds.observe(duration)
    risk_score_distribution.observe(risk_score)
    active_reviews.dec()


def record_celery_task(task_name: str, duration: float):
    celery_task_duration_seconds.labels(task_name=task_name).observe(duration)
