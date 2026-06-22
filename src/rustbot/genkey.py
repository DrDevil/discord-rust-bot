"""Tiny helper: ``python -m rustbot.genkey`` prints a fresh Fernet key.

Kept separate from the bot entrypoint so generating a key never requires a full
config to be present.
"""

from __future__ import annotations

from .crypto import TokenCipher


def main() -> None:
    # Intentionally printed to stdout: this is an operator CLI utility, not part
    # of the running bot's logging path.
    print(TokenCipher.generate_key())


if __name__ == "__main__":
    main()
