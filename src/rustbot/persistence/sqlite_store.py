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
from pathlib import Path
from typing import Optional

from .base import Repository, ServerStateRecord

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class SqliteRepository(Repository):
    def __init__(self, database_path: str) -> None:
        self._path = database_path
        self._lock = asyncio.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    async def connect(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._connect_sync)

    def _connect_sync(self) -> None:
        db_path = Path(self._path)
        if db_path.parent and not db_path.parent.exists():
            db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False because to_thread may use different threads;
        # all access is serialised by self._lock so this is safe.
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        self._conn.commit()

    async def close(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _require_conn(self) -> sqlite3.Connection:
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
        async with self._lock:
            return await asyncio.to_thread(
                self._get_encrypted_player_token_sync, server_id
            )

    def _get_encrypted_player_token_sync(self, server_id: str) -> Optional[str]:
        conn = self._require_conn()
        row = conn.execute(
            "SELECT player_token_encrypted FROM servers WHERE server_id = ?",
            (server_id,),
        ).fetchone()
        return row["player_token_encrypted"] if row else None

    async def load_server_state(self, server_id: str) -> Optional[ServerStateRecord]:
        async with self._lock:
            return await asyncio.to_thread(self._load_server_state_sync, server_id)

    def _load_server_state_sync(self, server_id: str) -> Optional[ServerStateRecord]:
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
        async with self._lock:
            await asyncio.to_thread(self._save_server_state_sync, record)

    def _save_server_state_sync(self, record: ServerStateRecord) -> None:
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
