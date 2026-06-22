"""Persistence layer: tokens, pairing info, and last-known state.

The rest of the app depends only on the abstract ``Repository`` interface, so the
SQLite backend can later be swapped (CLAUDE.md §9) without touching callers.
"""

from .base import Repository, ServerStateRecord
from .sqlite_store import SqliteRepository

__all__ = ["Repository", "ServerStateRecord", "SqliteRepository"]
