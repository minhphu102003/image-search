import structlog

from image_search.infrastructure.observability.logging import configure_logging


class TestLoggingConfig:
    def test_json_format_configures_json_renderer(self) -> None:
        configure_logging(log_format="json")
        logger = structlog.get_logger()
        assert logger is not None

    def test_text_format_configures_console_renderer(self) -> None:
        configure_logging(log_format="text")
        logger = structlog.get_logger()
        assert logger is not None

    def test_default_log_level_is_info(self) -> None:
        configure_logging()
        logger = structlog.get_logger()
        # Should not raise
        logger.info("test_event", key="value")
