from __future__ import annotations


class SessionSharingError(Exception):
    """Base error for the session-sharing domain."""


class DecryptError(SessionSharingError):
    """Failed to decrypt cookies / master key."""


class ProfileLockedError(SessionSharingError):
    """The master profile is locked by another Chrome process."""


class ChromeNotAliveError(SessionSharingError):
    """A Chrome headless instance is not responding on its CDP port."""


class LockBusyError(SessionSharingError):
    """The session lock is held by another client (turn not granted)."""


class ChatNotReadyError(SessionSharingError):
    """The chat session (CDP) is not available / not initialized."""
