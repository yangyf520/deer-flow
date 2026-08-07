"""Agent tools for enterprise knowledge retrieval."""

from __future__ import annotations

import json

from langchain.tools import tool


@tool("search", parse_docstring=True)
async def search_tool(
    query: str,
    spaces: list[str] | None = None,
    top_k: int | None = None,
    scenario: str | None = None,
) -> str:
    """Search enterprise knowledge and return an Evidence Pack as JSON.

    Results respect the current user's ACL and the Agent's bound spaces.

    Args:
        query: Natural-language query or keywords.
        spaces: Optional space ids. Agent-bound spaces are always enforced globally.
        top_k: Optional maximum evidence items.
        scenario: Optional retrieval scenario. Agent-bound scenario takes precedence.
    """
    from deerflow.config.knowledge_config import get_knowledge_config
    from deerflow.knowledge.app.query import search
    from deerflow.knowledge.runtime import knowledge_extra_available
    from deerflow.persistence.engine import get_session_factory
    from deerflow.runtime.user_context import get_current_user

    if not get_knowledge_config().enabled:
        return json.dumps({"error": "knowledge disabled"}, ensure_ascii=False)
    if not knowledge_extra_available():
        return json.dumps(
            {"error": "knowledge extra not installed", "hint": "uv sync --extra knowledge"},
            ensure_ascii=False,
        )
    user = get_current_user()
    if user is None:
        return json.dumps({"error": "not authenticated"}, ensure_ascii=False)
    factory = get_session_factory()
    if factory is None:
        return json.dumps({"error": "database not configured"}, ensure_ascii=False)

    system_role = getattr(user, "system_role", None) or "user"
    async with factory() as session:
        pack = await search(
            session,
            user_id=str(user.id),
            system_role=system_role,
            query=query,
            spaces=spaces,
            top_k=top_k,
            scenario=scenario,
        )
    return pack.model_dump_json(exclude_none=True)
