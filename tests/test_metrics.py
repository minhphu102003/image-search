from image_search.infrastructure.observability.metrics import (
    GEMINI_CALLS,
    GEMINI_LATENCY,
    INGEST_DURATION,
    INGEST_FAILED,
    INGEST_PROCESSED,
    INGEST_QUEUE_DEPTH,
    SEARCH_ERRORS,
    SEARCH_LATENCY,
    SEARCH_REQUESTS,
)


def _counter_value(counter: object) -> float:
    """Get current value of a prometheus_client Counter (no labels)."""
    return float(counter._value.get())  # type: ignore[union-attr]


def _labeled_counter_value(counter: object, **labels: str) -> float:
    """Get current value of a labeled prometheus_client Counter."""
    return float(counter.labels(**labels)._value.get())  # type: ignore[union-attr]


def _histogram_count(histogram: object) -> float:
    """Get total count of observations (no labels)."""
    return float(histogram._sum.get())  # type: ignore[union-attr]


class TestIngestMetrics:
    def test_processed_counter_increments(self) -> None:
        before = _counter_value(INGEST_PROCESSED)
        INGEST_PROCESSED.inc()
        after = _counter_value(INGEST_PROCESSED)
        assert after == before + 1.0

    def test_failed_counter_increments_with_label(self) -> None:
        before = _labeled_counter_value(INGEST_FAILED, error_type="TestError")
        INGEST_FAILED.labels(error_type="TestError").inc()
        after = _labeled_counter_value(INGEST_FAILED, error_type="TestError")
        assert after == before + 1.0

    def test_duration_histogram_records(self) -> None:
        INGEST_DURATION.observe(0.5)
        # Should not raise — just verify the metric is functional
        assert INGEST_DURATION._sum.get() > 0

    def test_queue_depth_gauge(self) -> None:
        INGEST_QUEUE_DEPTH.set(42)
        assert INGEST_QUEUE_DEPTH._value.get() == 42.0


class TestSearchMetrics:
    def test_requests_counter_increments(self) -> None:
        before = _labeled_counter_value(SEARCH_REQUESTS, approach="1")
        SEARCH_REQUESTS.labels(approach="1").inc()
        after = _labeled_counter_value(SEARCH_REQUESTS, approach="1")
        assert after == before + 1.0

    def test_latency_histogram_records(self) -> None:
        SEARCH_LATENCY.labels(approach="1").observe(0.05)
        assert SEARCH_LATENCY.labels(approach="1")._sum.get() > 0

    def test_errors_counter_increments(self) -> None:
        before = _labeled_counter_value(SEARCH_ERRORS, error_type="test")
        SEARCH_ERRORS.labels(error_type="test").inc()
        after = _labeled_counter_value(SEARCH_ERRORS, error_type="test")
        assert after == before + 1.0


class TestGeminiMetrics:
    def test_calls_counter_increments(self) -> None:
        before = _labeled_counter_value(GEMINI_CALLS, endpoint="generate_content")
        GEMINI_CALLS.labels(endpoint="generate_content").inc()
        after = _labeled_counter_value(GEMINI_CALLS, endpoint="generate_content")
        assert after == before + 1.0

    def test_latency_histogram_records(self) -> None:
        GEMINI_LATENCY.labels(endpoint="generate_content").observe(0.3)
        assert GEMINI_LATENCY.labels(endpoint="generate_content")._sum.get() > 0
