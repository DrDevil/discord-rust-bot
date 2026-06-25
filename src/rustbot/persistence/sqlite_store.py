"""SQLite implementation of the persistence ``Repository``.

Notes:
* SQLite calls are synchronous; each runs via ``asyncio.to_thread`` and is
  serialised behind an ``asyncio.Lock`` so the Discord event loop is never
  blocked (CLAUDE.md §13) and the single connection is used safely.
* Every statement is parameterised — no SQL is built by string concatenation
  (security: SQL injection).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Optional

from .base import Repository, ServerStateRecord


def _load_schema() -> str:
    """Load SQL schema from package resources.
    
    :return: SQL schema text from schema.sql.
    """
    # Load schema.sql from the package data directory
    schema_text = resources.files("rustbot.persistence").joinpath("schema.sql").read_text(encoding="utf-8")
    return schema_text


def _now_iso() -> str:
    """Get current UTC time as ISO 8601 string.
    
    :return: Current UTC timestamp formatted as ISO 8601 string.
    """
    return datetime.now(tz=timezone.utc).isoformat()


class SqliteRepository(Repository):
    def __init__(self, database_path: str) -> None:
        """Initialize SQLite repository with a database path.
        
        Does not open the connection; call connect() first.
        
        :param database_path: Filesystem path to SQLite database file (created if missing).
        :return: None (initializes repository instance).
        """
        self._path = database_path
        self._lock = asyncio.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    async def connect(self) -> None:
        """Open a connection to the SQLite database and initialize schema.
        
        Creates the database file and parent directories if they don't exist.
        Initializes the schema and enables foreign key constraints.
        
        :return: None (opens connection as side effect; must be called before other methods).
        """
        async with self._lock:
            await asyncio.to_thread(self._connect_sync)

    def _connect_sync(self) -> None:
        """Synchronous connection helper (runs via asyncio.to_thread).
        
        :return: None (opens and initializes connection).
        """
        db_path = Path(self._path)
        if db_path.parent and not db_path.parent.exists():
            db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False because to_thread may use different threads;
        # all access is serialised by self._lock so this is safe.
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.executescript(_load_schema())
        self._conn.commit()

    async def close(self) -> None:
        """Close the SQLite database connection.
        
        :return: None (closes connection as side effect).
        """
        async with self._lock:
            await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        """Synchronous close helper (runs via asyncio.to_thread).
        
        :return: None (closes connection).
        """
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _require_conn(self) -> sqlite3.Connection:
        """Require the connection to be open; raise if not.
        
        :return: The open sqlite3.Connection.
        :raises RuntimeError: If connect() has not been called or connection is closed.
        """
        if self._conn is None:
            raise RuntimeError("Repository is not connected; call connect() first.")
        return self._conn

    async def upsert_server(
        self,
        server_id: str,
        ip: str,
        port: int,
        steam_id: int,
        encrypted_player_token: str,
    ) -> None:
        """Create or update server connection details.
        
        Stores Rust+ server IP, port, pairing info, and encrypted player token.
        Idempotent; subsequent calls with same server_id overwrite previous data.
        
        :param server_id: Unique server identifier.
        :param ip: Rust+ server hostname or IP.
        :param port: Rust+ server port (typically 6500).
        :param steam_id: Your Steam64 ID (for pairing).
        :param encrypted_player_token: Encrypted Rust+ player token (from TokenCipher).
        :return: None (upserts record as side effect).
        """
        async with self._lock:
            await asyncio.to_thread(
                self._upsert_server_sync,
                server_id,
                ip,
                port,
                steam_id,
                encrypted_player_token,
            )

    def _upsert_server_sync(
        self,
        server_id: str,
        ip: str,
        port: int,
        steam_id: int,
        encrypted_player_token: str,
    ) -> None:
        """Synchronous upsert helper (runs via asyncio.to_thread).
        
        :param server_id: Unique server identifier.
        :param ip: Rust+ server hostname or IP.
        :param port: Rust+ server port.
        :param steam_id: Steam ID.
        :param encrypted_player_token: Encrypted token.
        :return: None (upserts record).
        """
        conn = self._require_conn()
        conn.execute(
            """
            INSERT INTO servers
                (server_id, ip, port, steam_id, player_token_encrypted, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
                ip = excluded.ip,
                port = excluded.port,
                steam_id = excluded.steam_id,
                player_token_encrypted = excluded.player_token_encrypted,
                updated_at = excluded.updated_at
            """,
            (server_id, ip, port, steam_id, encrypted_player_token, _now_iso()),
        )
        conn.commit()

    async def get_encrypted_player_token(self, server_id: str) -> Optional[str]:
        """Retrieve the encrypted player token for a server.
        
        :param server_id: Unique server identifier.
        :return: Encrypted player token if the server exists; None otherwise.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._get_encrypted_player_token_sync, server_id
            )

    def _get_encrypted_player_token_sync(self, server_id: str) -> Optional[str]:
        """Synchronous token retrieval helper (runs via asyncio.to_thread).
        
        :param server_id: Unique server identifier.
        :return: Encrypted token or None.
        """
        conn = self._require_conn()
        row = conn.execute(
            "SELECT player_token_encrypted FROM servers WHERE server_id = ?",
            (server_id,),
        ).fetchone()
        return row["player_token_encrypted"] if row else None

    async def load_server_state(self, server_id: str) -> Optional[ServerStateRecord]:
        """Load the last-known server state from the database.
        
        Includes online status, wipe time, and team member roster. Returns None if
        no state has been persisted for this server (first run).
        
        :param server_id: Unique server identifier.
        :return: ServerStateRecord with persisted state, or None if not found.
        """
        async with self._lock:
            return await asyncio.to_thread(self._load_server_state_sync, server_id)

    def _load_server_state_sync(self, server_id: str) -> Optional[ServerStateRecord]:
        """Synchronous state load helper (runs via asyncio.to_thread).
        
        Gracefully handles corrupt JSON in the members column by treating it as
        an empty roster (does not raise or crash).
        
        :param server_id: Unique server identifier.
        :return: ServerStateRecord with persisted state, or None if not found.
        """
        conn = self._require_conn()
        row = conn.execute(
            "SELECT online, wipe_time, members_json FROM server_state WHERE server_id = ?",
            (server_id,),
        ).fetchone()
        if row is None:
            return None

        members: dict[int, bool] = {}
        member_names: dict[int, str] = {}
        try:
            raw = json.loads(row["members_json"] or "{}")
            for steam_id, info in raw.items():
                members[int(steam_id)] = bool(info.get("online", False))
                member_names[int(steam_id)] = str(info.get("name", ""))
        except (ValueError, AttributeError):
            # Corrupt JSON should not crash startup; treat as no roster.
            members, member_names = {}, {}

        online = row["online"]
        return ServerStateRecord(
            server_id=server_id,
            online=None if online is None else bool(online),
            wipe_time=row["wipe_time"],
            members=members,
            member_names=member_names,
        )

    async def save_server_state(self, record: ServerStateRecord) -> None:
        """Persist the current server state to the database.
        
        Stores online status, wipe time, and team member roster (with names).
        Idempotent; overwrites previous state for the same server_id.
        
        :param record: ServerStateRecord to persist.
        :return: None (upserts state as side effect).
        """
        async with self._lock:
            await asyncio.to_thread(self._save_server_state_sync, record)

    def _save_server_state_sync(self, record: ServerStateRecord) -> None:
        """Synchronous state save helper (runs via asyncio.to_thread).
        
        Serializes team roster as JSON: {steam_id: {online: bool, name: str}, ...}
        
        :param record: ServerStateRecord to persist.
        :return: None (upserts state).
        """
        conn = self._require_conn()
        members_json = json.dumps(
            {
                str(steam_id): {
                    "online": bool(online),
                    "name": record.member_names.get(steam_id, ""),
                }
                for steam_id, online in record.members.items()
            }
        )
        online_value = None if record.online is None else int(record.online)
        conn.execute(
            """
            INSERT INTO server_state (server_id, online, wipe_time, members_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
                online = excluded.online,
                wipe_time = excluded.wipe_time,
                members_json = excluded.members_json,
                updated_at = excluded.updated_at
            """,
            (record.server_id, online_value, record.wipe_time, members_json, _now_iso()),
        )
        conn.commit()
