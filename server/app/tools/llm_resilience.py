from __future__ import annotations

import time
from typing import Any, Sequence


def _is_transient_llm_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    transient_markers = (
        "remoteprotocolerror",
        "server disconnected",
        "readtimeout",
        "timeout",
        "connecterror",
        "connectionerror",
        "apiconnectionerror",
        "serviceunavailable",
        "rate limit",
        "ratelimit",
        "temporarily unavailable",
    )
    return any(marker in text for marker in transient_markers)


def normalize_exception_message(exc: Exception) -> str:
    """Return a user-safe, stable error message for API/UI surfaces."""
    if _is_transient_llm_error(exc):
        return "Temporary upstream model connection issue. Please retry."
    text = str(exc).strip()
    return text or "Unexpected processing error"


def invoke_with_retry(
    runnable: Any,
    messages: Sequence[dict[str, str]],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 0.7,
) -> Any:
    """Invoke a LangChain runnable with retries for transient transport failures."""
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return runnable.invoke(list(messages))
        except Exception as exc:
            last_exc = exc
            if not _is_transient_llm_error(exc) or attempt >= max_attempts:
                break
            time.sleep(base_delay_seconds * attempt)

    assert last_exc is not None
    raise RuntimeError(normalize_exception_message(last_exc)) from last_exc
