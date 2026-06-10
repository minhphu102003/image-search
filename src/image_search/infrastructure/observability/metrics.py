"""Prometheus metrics for Image Search Service."""

from prometheus_client import Counter, Gauge, Histogram

# --- Ingest Worker ---

INGEST_PROCESSED = Counter(
    "image_ingest_processed_total",
    "Total images processed",
)
INGEST_FAILED = Counter(
    "image_ingest_failed_total",
    "Total failed images",
    labelnames=["error_type"],
)
INGEST_DURATION = Histogram(
    "image_ingest_duration_seconds",
    "Processing time per image",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
INGEST_QUEUE_DEPTH = Gauge(
    "image_ingest_queue_depth",
    "Pending messages in Redis",
)

# --- Search Service ---

SEARCH_REQUESTS = Counter(
    "image_search_requests_total",
    "Total search requests",
    labelnames=["approach"],
)
SEARCH_LATENCY = Histogram(
    "image_search_latency_seconds",
    "Search latency",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
    labelnames=["approach"],
)
SEARCH_ERRORS = Counter(
    "image_search_errors_total",
    "Total search errors",
    labelnames=["error_type"],
)

# --- Gemini API ---

GEMINI_CALLS = Counter(
    "gemini_api_calls_total",
    "Gemini API calls",
    labelnames=["endpoint"],
)
GEMINI_LATENCY = Histogram(
    "gemini_api_latency_seconds",
    "Gemini API latency",
    labelnames=["endpoint"],
)
