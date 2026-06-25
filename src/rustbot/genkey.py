"""Tiny helper: ``python -m rustbot.genkey`` prints a fresh Fernet key.

Kept separate from the bot entrypoint so generating a key never requires a full
config to be present.
"""

from __future__ import annotations

from .crypto import TokenCipher


def main() -> None:
    """Generate and print a fresh Fernet encryption key to stdout.
    
    This is an operator utility for initial setup (run: python -m rustbot.genkey).
    Output should be saved as the FERNET_KEY environment variable.
    
    :return: None (prints key to stdout).
    """
    # Intentionally printed to stdout: this is an operator CLI utility, not part
    # of the running bot's logging path.
    print(TokenCipher.generate_key())


if __name__ == "__main__":
    main()
