"""Thread context propagation for cross-agent conversation continuity.

Uses Python ContextVar so the client UUID set at the API layer is
automatically available inside delegation tools — no LLM involvement.

Naming convention:
    Portfolio Manager : <client_uuid>
    Backtester        : bt-<client_uuid>
    Quant Analyst     : qa-<client_uuid>
"""

from contextvars import ContextVar, Token

_client_thread_id: ContextVar[str] = ContextVar("client_thread_id", default="default")


def set_thread_id(thread_id: str) -> Token:
    """Set the active client thread ID for the current async context.

    Args:
        thread_id: Client-generated UUID from the UI

    Returns:
        Token that can be passed to reset() to restore the previous value
    """
    return _client_thread_id.set(thread_id)


def reset_thread_id(token: Token) -> None:
    """Restore the previous thread ID using the token from set_thread_id().

    Args:
        token: Token returned by set_thread_id()
    """
    _client_thread_id.reset(token)


def get_pm_thread_id() -> str:
    """Return the Portfolio Manager thread ID (same as client UUID)."""
    return _client_thread_id.get()


def get_bt_thread_id() -> str:
    """Return the Backtester thread ID derived from the client UUID."""
    return f"bt-{_client_thread_id.get()}"


def get_qa_thread_id() -> str:
    """Return the Quant Analyst thread ID derived from the client UUID."""
    return f"qa-{_client_thread_id.get()}"
