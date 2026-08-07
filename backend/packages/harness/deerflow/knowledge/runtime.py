"""Agent binding and optional dependency checks for knowledge."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

from fastapi import HTTPException

_agent_knowledge_defaults: ContextVar[dict[str, Any] | None] = ContextVar("agent_knowledge_defaults", default=None)


def knowledge_extra_available() -> bool:
    """True when LlamaIndex core is installed (store-specific deps checked at use time)."""
    try:
        import llama_index.core  # noqa: F401
    except ImportError:
        return False
    return True


def docling_extra_available() -> bool:
    try:
        import docling  # noqa: F401

        return True
    except ImportError:
        return False


def require_knowledge_extra() -> None:
    if not knowledge_extra_available():
        raise HTTPException(
            status_code=501,
            detail={
                "code": "not_implemented",
                "message": "Knowledge extra not installed. Run: uv sync --extra knowledge",
            },
        )


def set_agent_knowledge_defaults(*, spaces: list[str] | None, scenario: str | None) -> Token | None:
    payload: dict[str, Any] = {}
    if spaces is not None:
        payload["spaces"] = spaces
    if scenario:
        payload["scenario"] = scenario
    return _agent_knowledge_defaults.set(payload)


def reset_agent_knowledge_defaults(token: Token | None) -> None:
    if token is not None:
        _agent_knowledge_defaults.reset(token)


def get_agent_knowledge_defaults() -> dict[str, Any]:
    return dict(_agent_knowledge_defaults.get() or {})


def resolve_agent_knowledge_scope(
    spaces: list[str] | None,
    scenario: str | None,
) -> tuple[list[str] | None, str | None]:
    """Restrict retrieval to the current Agent's knowledge binding.

    Outside an Agent run the request is unchanged. Within an Agent run, bound
    spaces are a hard ceiling (not merely defaults), and a bound scenario
    cannot be overridden by a tool call.
    """
    bound = _agent_knowledge_defaults.get()
    if bound is None:
        return spaces, scenario

    bound_spaces = bound.get("spaces")
    if bound_spaces is not None:
        allowed = set(bound_spaces)
        spaces = list(bound_spaces) if spaces is None else [space for space in spaces if space in allowed]

    bound_scenario = bound.get("scenario")
    if bound_scenario:
        scenario = str(bound_scenario)
    return spaces, scenario
