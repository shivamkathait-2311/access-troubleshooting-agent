import json
import logging
import sys
from datetime import UTC, datetime

from app.core.config import settings


class JSONFormatter(logging.Formatter):
    """Structured JSON formatter for production log shipping."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        for field in ("correlation_id", "requester", "diagnostic_subject", "request_id"):
            if hasattr(record, field):
                log_data[field] = getattr(record, field)

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


class ColoredFormatter(logging.Formatter):
    """Colored formatter for local/console development output."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
        "RESET": "\033[0m",
    }

    _BUILTIN_KEYS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
        "message",
        "asctime",
    }

    def format(self, record: logging.LogRecord) -> str:
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.COLORS['RESET']}"

        message = super().format(record)

        extras = {k: v for k, v in record.__dict__.items() if k not in self._BUILTIN_KEYS}
        if extras:
            message += " | " + " ".join(f"{k}={v}" for k, v in extras.items())

        return message


def setup_logging() -> None:
    """Configure root + app loggers. Call once at process startup."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.WARNING)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    if settings.ENV == "production":
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(ColoredFormatter("%(levelname)s | %(name)s | %(message)s"))

    root_logger.addHandler(console_handler)

    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    app_logger.info(
        "Logging configured environment=%s level=%s",
        settings.ENV,
        settings.LOG_LEVEL,
    )


logger = logging.getLogger("app")

_RESERVED_LOG_KEYS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName",
    }
)


class LoggerAdapter:
    """Structured-logging convenience wrapper: logger.info("msg", key=value)."""

    def __init__(self, wrapped: logging.Logger):
        self.logger = wrapped

    def debug(self, message: str, **kwargs: object) -> None:
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs: object) -> None:
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs: object) -> None:
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs: object) -> None:
        self._log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs: object) -> None:
        self._log(logging.CRITICAL, message, **kwargs)

    def _log(self, level: int, message: str, **kwargs: object) -> None:
        extra = {}
        for key, value in kwargs.items():
            safe_key = f"extra_{key}" if key in _RESERVED_LOG_KEYS else key
            extra[safe_key] = value
        self.logger.log(level, message, extra=extra)


logger_adapter = LoggerAdapter(logger)
