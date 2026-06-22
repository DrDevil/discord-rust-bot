"""Abstract persistence interface.

Defined as an ABC so a non-SQLite backend can be added later without changing
callers (CLAUDE.md §9 — "Abstract persistence layer"). The player token is always
handled as ciphertext at this boundary; encryption/decryption is the caller's
responsibility (see ``crypto.TokenCipher``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ServerStateRecord:
    """Persisted last-known state for one server (survives restart)."""

    server_id: str
    online: Optional[bool] = None
    wipe_time: Optional[int] = None
    # steam_id -> is_online
    members: Dict[int, bool] = field(default_factory=dict)
    # steam_id -> display name
    member_names: Dict[int, str] = field(default_factory=dict)


class Repository(ABC):
    """Storage contract for tokens, pairing info, and server state."""

    @abstractmethod
    async def connect(self) -> None:
        """Open the store and ensure the schema exists."""

    @abstractmethod
    async def close(self) -> None:
        """Close the store and release resources."""

    @abstractmethod
    async def upsert_server(
        self,
        server_id: str,
        ip: str,
        port: int,
        steam_id: int,
        encrypted_player_token: str,
    ) -> None:
        """Insert/update pairing info. ``encrypted_player_token`` is ciphertext."""

    @abstractmethod
    async def get_encrypted_player_token(self, server_id: str) -> Optional[str]:
        """Return the stored ciphertext token, or ``None`` if not stored yet."""

    @abstractmethod
    async def load_server_state(self, server_id: str) -> Optional[ServerStateRecord]:
        """Return persisted state for a server, or ``None`` if unknown."""

    @abstractmethod
    async def save_server_state(self, record: ServerStateRecord) -> None:
        """Persist the last-known state for a server."""
