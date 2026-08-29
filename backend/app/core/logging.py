import logging
from collections.abc import MutableMapping
from typing import Any

import structlog

SENSITIVE_FRAGMENTS = (
    "password",
    "token",
    "secret",
    "authorization",
    "refresh",
    "api_key",
    "card",
    "cvv",
    "pin",
)


def redact_sensitive(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        normalized = key.lower()
        if any(fragment in normalized for fragment in SENSITIVE_FRAGMENTS):
            event_dict[key] = "[REDACTED]"
        elif isinstance(event_dict[key], dict):
            event_dict[key] = _redact_mapping(event_dict[key])
    return event_dict


def _redact_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: "[REDACTED]"
        if any(fragment in key.lower() for fragment in SENSITIVE_FRAGMENTS)
        else _redact_mapping(item)
        if isinstance(item, dict)
        else item
        for key, item in value.items()
    }


def configure_logging(level: str, console: bool = False) -> None:
    renderer: structlog.types.Processor = (
        structlog.dev.ConsoleRenderer() if console else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_sensitive,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
    )
