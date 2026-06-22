"""Structured logging (CLAUDE.md §10).

Every record is emitted as a single JSON line including a timestamp, level,
logger name, and — when supplied via ``extra`` — ``server_id`` and
``event_type``. A redaction filter defensively masks known secret values so
tokens never leak into logs, even if a future call site is careless. There are
no ``print`` statements anywhere in the project.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Iterable

_STRUCTURED_FIELDS = ("server_id", "event_type")
_REDACTION_PLACEHOLDER = "***REDACTED***"


class StructuredFormatter(logging.Formatter):
    """Render log records as compact JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class SecretRedactionFilter(logging.Filter):
    """Replace known secret substrings in a record's message before emit."""

    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        # Keep only non-trivial secrets to avoid redacting common short strings.
        self._secrets = sorted(
            {s for s in secrets if s and len(s) >= 4}, key=len, reverse=True
        )

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True
        message = record.getMessage()
        redacted = message
        for secret in self._secrets:
            if secret in redacted:
                redacted = redacted.replace(secret, _REDACTION_PLACEHOLDER)
        if redacted != message:
            # Replace the formatted message; drop args since they are baked in.
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(
    level: str = "INFO",
    *,
    secrets: Iterable[str] = (),
    debug_protobuf: bool = False,
) -> None:
    """Configure root logging once, with structured output and redaction."""
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    handler.addFilter(SecretRedactionFilter(secrets))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # The `rustplus` library attaches its own DEBUG StreamHandler and forces its
    # logger to DEBUG. Tame it so output stays structured and quiet unless we are
    # explicitly debugging the protocol. Its handlers are cleared in the client
    # after the socket is constructed; here we set the level and let it propagate.
    rp_logger = logging.getLogger("rustplus.py")
    rp_logger.setLevel(logging.DEBUG if debug_protobuf else logging.WARNING)
    rp_logger.propagate = True

    # discord.py is chatty at INFO; keep it at WARNING unless we are debugging.
    logging.getLogger("discord").setLevel(
        logging.DEBUG if level.upper() == "DEBUG" else logging.WARNING
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
