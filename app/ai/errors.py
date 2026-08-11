"""Model provider failures shared by the gateway and concrete adapters."""

from __future__ import annotations


class ModelUnavailable(RuntimeError):
    """The configured model endpoint cannot currently complete the request."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable
