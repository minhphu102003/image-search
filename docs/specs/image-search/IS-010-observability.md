# Spec: Observability and Monitoring

> Specification for Prometheus metrics, structured logging, and Grafana dashboards.

---

## Metadata

| Field        | Value                      |
|-------------|----------------------------|
| **ID**      | IS-010                     |
| **Title**   | Observability and Monitoring |
| **Phase**   | 4 — Integration            |
| **Status**  | Draft                      |
| **Depends** | IS-004, IS-005             |

---

## 1. Objective

Provide operational visibility through Prometheus metrics, structured JSON logging (structlog), Grafana dashboards, and health check endpoints.

---

## 2. Tech Stack

| Tool              | Purpose                    |
|------------------|----------------------------|
| prometheus-client | Metrics collection         |
| structlog         | Structured JSON logging    |
| Grafana           | Dashboard visualization    |

---

## 3. Detailed Design

### 3.1 Prometheus Metrics

#### Ingest Worker

```python
from prometheus_client import Counter, Histogram, Gauge

INGEST_PROCESSED = Counter("image_ingest_processed_total", "Total images processed")
INGEST_FAILED = Counter("image_ingest_failed_total", "Total failed images", ["error_type"])
INGEST_DURATION = Histogram("image_ingest_duration_seconds", "Processing time per image",
                            buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0])
INGEST_QUEUE_DEPTH = Gauge("image_ingest_queue_depth", "Pending messages in Redis")
```

#### Search Service

```python
SEARCH_REQUESTS = Counter("image_search_requests_total", "Total search requests", ["approach"])
SEARCH_LATENCY = Histogram("image_search_latency_seconds", "Search latency",
                           buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
                           ["approach"])
SEARCH_ERRORS = Counter("image_search_errors_total", "Total search errors", ["error_type"])
GEMINI_CALLS = Counter("gemini_api_calls_total", "Gemini API calls", ["endpoint"])
GEMINI_LATENCY = Histogram("gemini_api_latency_seconds", "Gemini API latency", ["endpoint"])
```

### 3.2 Structured Logging (structlog)

```python
import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
)

logger = structlog.get_logger()

# Usage
logger.info("image_processed", image_id="img-001", latency_ms=1234, status="INDEXED")
logger.info("search_completed", approach=1, results=10, latency_ms=45.2)
logger.error("ingest_failed", image_id="img-001", error="file not found")
```

### 3.3 Health Check Endpoint

```python
@app.get("/health")
async def health():
    checks = {}

    # Redis
    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"

    # PostgreSQL
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        checks["postgresql"] = "ok"
    except Exception:
        checks["postgresql"] = "error"

    # SigLIP
    checks["siglip"] = "ok" if embedding_service.model else "not_loaded"

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
```

### 3.4 Grafana Dashboard Panels

| Panel                    | Query                                           | Type        |
|-------------------------|------------------------------------------------|-------------|
| Ingest Throughput        | `rate(image_ingest_processed_total[5m])`        | Time series |
| Ingest Failures          | `rate(image_ingest_failed_total[5m])`           | Time series |
| Ingest Latency P95       | `histogram_quantile(0.95, ...)`                 | Time series |
| Ingest Queue Depth       | `image_ingest_queue_depth`                      | Gauge       |
| Search Request Rate      | `rate(image_search_requests_total[5m])`         | Time series |
| Search Latency by Approach | `histogram_quantile(0.95, ..., by approach)`  | Time series |
| Search Error Rate        | `rate(image_search_errors_total[5m])`           | Time series |
| Gemini API Calls         | `rate(gemini_api_calls_total[5m])`              | Time series |

---

## 4. Configuration

```python
# In Settings class
metrics_enabled: bool = True
log_level: str = "INFO"
log_format: str = "json"  # "json" or "text"
```

---

## 5. Acceptance Criteria

- [x] `/metrics` returns valid Prometheus text format
- [x] `image_ingest_processed_total` increments after each image
- [x] `image_search_latency_seconds` records correct latency
- [x] `/health` returns `{"status": "ok"}` when all services connected
- [x] `/health` returns `{"status": "degraded"}` when Redis/PG unreachable
- [x] Logs are valid JSON with `timestamp`, `level`, `event` fields
- [ ] Grafana dashboard loads with all panels

---

## 6. Testing Strategy

### Unit Tests
- Metrics increment correctly
- Health check returns correct status
- Log output contains expected fields

### Integration Tests
- Prometheus scrape endpoint works
- Health check with real Redis/PostgreSQL
