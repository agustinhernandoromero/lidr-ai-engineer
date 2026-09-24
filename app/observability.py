"""Configuración de structlog para el servicio IA."""

import logging
import sys

import structlog


def configure_logging(env: str = "development") -> None:
    """Configura structlog una sola vez al arrancar la aplicación.

    En desarrollo se usa salida coloreada y legible; en cualquier otro entorno,
    JSON de una línea por evento, que es lo que esperan los agregadores de logs.
    """
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)

    renderer = (
        structlog.dev.ConsoleRenderer()
        if env == "development"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
