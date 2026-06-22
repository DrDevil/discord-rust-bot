"""Self-hosted Rust+ Discord bot (Phase 1 — Foundation/MVP).

Layered per CLAUDE.md §4:
  - rustplus_client : Rust+ auth/websocket/protobuf (wraps the `rustplus` library)
  - event_router    : normalises Rust+ observations into internal events
  - domain          : alert rules and current-state tracking
  - discord_layer   : slash commands, embeds, permissions
  - persistence     : tokens, pairing info, configs (SQLite)
"""

__version__ = "0.1.0"
