"""Persistent reference client; not Android/Room implementation."""

from .store import ClientError, Context, SyncStore
from .transport import SyncHTTP

__all__ = ["ClientError", "Context", "SyncHTTP", "SyncStore"]
