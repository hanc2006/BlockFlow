from __future__ import annotations


class CatalogUpstreamError(RuntimeError):
    """CivitAI / Hugging Face request failed.

    `status` is the upstream HTTP status, or None for network-level failures
    (DNS, TLS, timeout, connection reset).
    """

    def __init__(self, source: str, status: int | None, message: str) -> None:
        super().__init__(f"{source}: {status or 'network error'}: {message}")
        self.source = source
        self.status = status
        self.message = message
