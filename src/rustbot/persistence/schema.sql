-- SQLite schema for the Rust+ Discord bot (Phase 1).
-- All writes use parameterised queries in sqlite_store.py (no string-built SQL).

CREATE TABLE IF NOT EXISTS servers (
    server_id              TEXT PRIMARY KEY,
    ip                     TEXT NOT NULL,
    port                   INTEGER NOT NULL,
    steam_id               INTEGER NOT NULL,
    -- Fernet ciphertext of the Rust+ player token (encrypted at rest, §8).
    player_token_encrypted TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS server_state (
    server_id    TEXT PRIMARY KEY,
    online       INTEGER,            -- 0/1/NULL
    wipe_time    INTEGER,            -- epoch seconds, nullable
    members_json TEXT NOT NULL DEFAULT '{}',  -- {steam_id: {"online": bool, "name": str}}
    updated_at   TEXT NOT NULL,
    FOREIGN KEY (server_id) REFERENCES servers(server_id)
);
