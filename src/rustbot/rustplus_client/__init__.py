"""Rust+ client layer: authentication, websocket, and protobuf.

Wraps the third-party ``rustplus`` library behind our own interface so the rest
of the app never imports ``rustplus`` types directly (CLAUDE.md §4). The library
is treated as unstable/unofficial: every call result is checked, and failures are
turned into ``online=False`` observations rather than exceptions that escape (§7).
"""

from .client import RustClient

__all__ = ["RustClient"]
