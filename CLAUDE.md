# You are implementing a self-hosted Discord bot for the game Rust that replicates the core functionality of paid “Rust Plus Bots”.

# 1. The bot:

* Emulates a Rust+ Companion App client
* Connects to a Rust server using the Rust+ protocol
* Receives real-time push events
* Sends alerts and status messages to Discord
* Accepts Discord slash commands for querying status and controlling smart devices

This project is non-commercial, self-hosted, and intended for personal or community use.

# 2. Primary Objectives

Claude should optimize for:

* Correctness over cleverness
* Protocol stability
* Incremental feature delivery
* Clear, debuggable code
* Minimal assumptions

Avoid over-engineering or premature optimization.

# 3. Technical Constraints

* Language: Python 3.11+
* Async runtime: asyncio
* Discord SDK: discord.py (slash commands only)
* No RCON for Rust+ features
* No web dashboard
* No monetization logic
* No obfuscation

# 4. Architecture Rules

Mandatory Separation of Concerns

Do not mix these layers:

| Layer         | Responsibility                               |
| ------------- | ---------------------------------------------|
| Rust+ Client	| Authentication, pairing, WebSocket, Protobuf |
| Event Router	| Normalizing Rust+ events                     |
| Discord Layer	| Commands, embeds, permissions                |
| Domain Logic	| Alerts, rules, thresholds                    |
| Persistence	| Tokens, pairing info, configs                |

Each must be implemented as separate modules.

# 5. Feature Phasing Rules

*Described in PROJECT_PLAN.md*

Do not skip phases.

# 6. Discord UX Rules

* Use slash commands only

All commands must:
* Respond within 3 seconds
* Use embeds
* Be permission-aware
* No prefix commands
* No DM-only commands

# 7. Rust+ Protocol Rules

* Treat Rust+ as unstable and unofficial
* Prefer clarity over compression
* Log raw messages in debug mode
* Fail gracefully on unknown messages
* Never assume field presence in Protobuf

# 8. Configuration Rules

* All secrets via environment variables
* No hardcoded tokens
* Support .env
* Store pairing tokens encrypted at rest (simple encryption acceptable)

# 9. Persistence Rules

## Initial:

JSON or SQLite

## Later:

Abstract persistence layer
No cloud dependencies.

# 10. Logging & Debugging

Use structured logging

Include:
* Timestamp
* Server ID
* Event type
* No print statements
* Debug logging toggleable via env

# 11. Legal & Ethical Boundaries

This project is:
* Non-commercial
* Not redistributed as a hosted service

Do not include:
* Anti-ban techniques
* Account sharing logic
* Abuse mitigation bypasses

# 12. Claude Execution Guidelines

When implementing:
* Ask before introducing new dependencies
* Ask before implementing protocol decoding beyond Phase scope
* Provide small, testable increments
* Prefer explicit types and schemas
* Explain why something is done if non-obvious

# 13. Definition of Done

A feature is complete only if:
* It works after restart
* It logs meaningful errors
* It fails safely
* It does not block Discord event loop
* It follows the architecture rules
