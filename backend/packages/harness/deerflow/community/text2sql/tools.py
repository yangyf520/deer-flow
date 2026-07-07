"""
Business-database tools (read-only SQL + Vanna NL→SQL).

Configure via project ``.env``: ``DB_DSN`` or ``DB_TYPE`` + credentials.
Scope: ``DB_SCHEMA``, ``DB_TABLE_PREFIXES``, ``DB_MAX_TABLES``, etc.
Optional extra: ``cd backend && uv sync --all-packages --extra text2sql`` (required for ``db_ask``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langchain.tools import tool

from deerflow.config import get_app_config
from deerflow.utils.database import int_env, load_schema_summary, query

logger = logging.getLogger(__name__)

_VANNA_INSTALL = "cd backend && uv sync --all-packages --extra text2sql"


def _require_business_db() -> None:
    from deerflow.utils.database import is_business_db_configured

    if not is_business_db_configured():
        raise RuntimeError(
            "Business database not configured. Set DB_DSN or DB_TYPE with DB_HOST, "
            "DB_USERNAME, DB_PASSWORD in the project .env."
        )


def _max_rows(tool_name: str, default: int = 500) -> int:
    cfg = get_app_config().get_tool_config(tool_name)
    if cfg is not None and cfg.model_extra.get("max_rows") is not None:
        try:
            return int(cfg.model_extra["max_rows"])
        except (TypeError, ValueError):
            pass
    return int_env("TEXT2SQL_MAX_ROWS", default) or default


def _model_name(tool_name: str) -> str | None:
    cfg = get_app_config().get_tool_config(tool_name)
    if cfg is None:
        return None
    raw = cfg.model_extra.get("model_name")
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return None
    return str(raw).strip()


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def _vanna_ask(question: str, *, max_rows: int, model_name: str | None) -> dict[str, Any]:
    try:
        import vanna  # noqa: F401
    except ImportError as e:
        raise RuntimeError(_VANNA_INSTALL) from e

    import pandas as pd
    from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
    from vanna import Agent
    from vanna.capabilities.sql_runner import SqlRunner
    from vanna.capabilities.sql_runner.models import RunSqlToolArgs
    from vanna.core.agent.config import AgentConfig
    from vanna.core.llm import LlmRequest, LlmResponse, LlmService, LlmStreamChunk
    from vanna.core.registry import ToolRegistry
    from vanna.core.tool import ToolCall
    from vanna.core.user import User, UserResolver
    from vanna.core.user.request_context import RequestContext
    from vanna.integrations.local.agent_memory import DemoAgentMemory
    from vanna.tools import RunSqlTool
    from vanna.tools.agent_memory import (
        SaveQuestionToolArgsTool,
        SaveTextMemoryTool,
        SearchSavedCorrectToolUsesTool,
    )

    from deerflow.models.factory import create_chat_model

    def _lc_messages(request: LlmRequest) -> list[BaseMessage]:
        out: list[BaseMessage] = []
        if request.system_prompt:
            out.append(SystemMessage(content=request.system_prompt))
        for m in request.messages:
            if m.role == "user":
                out.append(HumanMessage(content=m.content))
            elif m.role == "assistant":
                if m.tool_calls:
                    out.append(
                        AIMessage(
                            content=m.content or "",
                            tool_calls=[
                                {"name": tc.name, "id": tc.id, "args": dict(tc.arguments or {})}
                                for tc in m.tool_calls
                            ],
                        )
                    )
                else:
                    out.append(AIMessage(content=m.content or ""))
            elif m.role == "tool":
                out.append(ToolMessage(content=m.content, tool_call_id=m.tool_call_id or ""))
        return out

    def _to_llm_response(msg: AIMessage) -> LlmResponse:
        content = msg.content if isinstance(msg.content, str) else str(msg.content or "")
        tcs = []
        for tc in getattr(msg, "tool_calls", None) or []:
            args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
            if isinstance(args, str):
                args = json.loads(args) if args.startswith("{") else {"_raw": args}
            tcs.append(
                ToolCall(
                    id=str(tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "tc")),
                    name=str(tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "tool")),
                    arguments=dict(args or {}),
                )
            )
        return LlmResponse(content=content or None, tool_calls=tcs or None, finish_reason="tool_calls" if tcs else "stop")

    class _Llm(LlmService):
        def __init__(self, name: str | None) -> None:
            self._name = name

        async def send_request(self, request: LlmRequest) -> LlmResponse:
            model = create_chat_model(name=self._name, thinking_enabled=False, temperature=request.temperature)
            msgs = _lc_messages(request)
            if request.tools:
                tools = [
                    {"type": "function", "function": {"name": s.name, "description": s.description, "parameters": s.parameters}}
                    for s in request.tools
                ]
                kw = {"tool_choice": "required"} if request.metadata.get("require_tool_call") else {}
                try:
                    bound = model.bind_tools(tools, **kw)
                except TypeError:
                    bound = model.bind_tools(tools)
                resp = await bound.ainvoke(msgs)
            else:
                resp = await model.ainvoke(msgs)
            return _to_llm_response(resp) if isinstance(resp, AIMessage) else LlmResponse(content=str(resp))

        async def stream_request(self, request: LlmRequest):
            r = await self.send_request(request)
            if r.content:
                yield LlmStreamChunk(content=r.content)
            yield LlmStreamChunk(finish_reason=r.finish_reason or "stop")

        async def validate_tools(self, tools):
            return []

    class _Runner(SqlRunner):
        def __init__(self, limit: int) -> None:
            self.limit = limit
            self.last_sql: str | None = None
            self.last_preview = ""
            self.truncated = False

        async def run_sql(self, args: RunSqlToolArgs, context) -> pd.DataFrame:
            self.last_sql = str(args.sql)
            rows, self.truncated = query(self.last_sql, max_rows=self.limit)
            self.last_preview = json.dumps(rows[:10], ensure_ascii=False) if rows else "No rows returned."
            if self.truncated:
                self.last_preview += " (truncated)"
            return pd.DataFrame(rows)

    class _Users(UserResolver):
        async def resolve_user(self, ctx: RequestContext) -> User:
            return User(id="local", email="local@deerflow", group_memberships=["admin", "user"])

    schema = load_schema_summary(max_columns_per_table=int_env("DB_MAX_COLUMNS") or 200)
    if not schema.strip() or schema.strip() == "No tables found.":
        return {"sql": None, "preview": "No schema visible. Check DB_* filters.", "truncated": False}

    msg = f"Database schema:\n{schema}\n\nQuestion:\n{question}"
    runner = _Runner(max_rows)
    reg = ToolRegistry()
    reg.register_local_tool(RunSqlTool(sql_runner=runner), access_groups=["admin", "user"])
    reg.register_local_tool(SearchSavedCorrectToolUsesTool(), access_groups=["admin", "user"])
    reg.register_local_tool(SaveQuestionToolArgsTool(), access_groups=["admin", "user"])
    reg.register_local_tool(SaveTextMemoryTool(), access_groups=["admin", "user"])

    agent = Agent(
        llm_service=_Llm(model_name),
        tool_registry=reg,
        user_resolver=_Users(),
        agent_memory=DemoAgentMemory(max_items=int_env("TEXT2SQL_VANNA_MEMORY_ITEMS", 500) or 500),
        config=AgentConfig(stream_responses=False, temperature=0, auto_save_conversations=False),
    )

    parts: list[str] = []
    async for comp in agent.send_message(
        RequestContext(headers={}, cookies={}, query_params={}, path_params={}),
        msg,
    ):
        t = getattr(getattr(comp, "simple_component", None), "text", None)
        if t:
            parts.append(str(t))

    return {
        "sql": runner.last_sql,
        "preview": "\n".join(parts).strip() or runner.last_preview,
        "truncated": runner.truncated,
    }


@tool("db_schema", parse_docstring=True)
def db_schema_tool() -> str:
    """Return tables and columns for the configured business database (scope from DB_* env vars)."""
    _require_business_db()
    return load_schema_summary(max_columns_per_table=int_env("DB_MAX_COLUMNS") or 200)


@tool("db_query", parse_docstring=True)
def db_query_tool(sql: str) -> str:
    """Run one read-only SELECT or WITH on the configured business database.

    Args:
        sql: A single SELECT/WITH statement.
    """
    _require_business_db()
    try:
        rows, truncated = query(sql, max_rows=_max_rows("db_query"))
    except Exception as e:
        logger.exception("db_query failed")
        return _json({"error": str(e), "sql": sql})
    return _json({"rows": rows, "truncated": truncated, "count": len(rows)})


@tool("db_ask", parse_docstring=True)
def db_ask_tool(question: str) -> str:
    """Answer a natural-language question against the business database (generates and runs SQL via Vanna).

    Args:
        question: Full question with time range and dimensions when known.
    """
    _require_business_db()
    try:
        result = asyncio.run(
            _vanna_ask(question, max_rows=_max_rows("db_ask"), model_name=_model_name("db_ask")),
        )
    except RuntimeError as e:
        return _json({"error": str(e)})
    except Exception as e:
        logger.exception("db_ask failed")
        return _json({"error": str(e), "question": question})
    return _json(result)
