"""Exceptions raised by pyharmonyng."""

from __future__ import annotations


class HarmonyNgError(Exception):
    """Base class for every pyharmonyng error."""


class HarmonyNgConnectionError(HarmonyNgError):
    """The Hub could not be reached, or the connection dropped."""


class HarmonyNgAuthError(HarmonyNgError):
    """The Hub refused the credentials."""


class HarmonyNgBusyError(HarmonyNgError):
    """The orchestrator holds the interlock (HTTP 409 or a busy acknowledgement)."""


class HarmonyNgApiError(HarmonyNgError):
    """The Hub answered with an error."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        """Store the Hub's error text and the status code, when there is one."""
        super().__init__(message)
        self.message = message
        self.code = code


class HarmonyNgUnsupportedError(HarmonyNgError):
    """The firmware predates the API this library speaks."""


class HarmonyNgProtocolError(HarmonyNgError):
    """The Hub sent something the protocol does not allow."""
