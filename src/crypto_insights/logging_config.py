"""structlog configuration: JSON para batch (queryable), console para CLI/UI.

Configurar una sola vez en main() — NO en cada módulo (R10).
Patrón correcto: log.warning("connector_failed", project=..., source=...) NO f-strings.
"""

from __future__ import annotations

import logging
import sys

import structlog

from .config import get_settings


def configure_logging(*, force_console: bool = False) -> None:
    """Inicializa structlog. Idempotente — llamarse desde main() del CLI."""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    use_json = settings.log_format == "json" and not force_console

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if use_json:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
