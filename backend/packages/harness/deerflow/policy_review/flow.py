"""Keep an in-flight policy review from ending as prose.

Mounted when ``config.tools`` registers ``deerflow.policy_review.*``. Activates
only after this user turn has already called a policy tool — the agent chooses
when to start via Skill / SOUL; this middleware only ensures the turn finishes
through ``policy_finalize`` (or a hard ``machine_failed`` after reminders).

Root causes of flaky / slow reviews:
1. Model writes Markdown instead of calling finalize → force ``tool_choice``.
2. Model emits finalize with invalid nested args → ``invalid_tool_calls`` /
   dangling placeholders → wasted LLM rounds. Salvage raw arguments once and
   deliver in-process (no more LLM) when evidence is ready.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelCallResult,
    ModelRequest,
    ModelResponse,
    hook_config,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.tool_call_metadata import clone_ai_message_with_tool_calls
from deerflow.policy_review.contract import LEGAL_REVIEW_V1, machine_failed_result

logger = logging.getLogger(__name__)

POLICY_TOOLS = frozenset({"policy_prepare", "policy_retrieve", "policy_finalize"})
TOOL_USE_PREFIX = "deerflow.policy_review."
REMINDER_NAME = "policy_flow_reminder"
# tool_choice + salvage should make prose rare; one silent rebind then hard fail.
MAX_REMINDERS = 1
_TERMINAL_REVIEW = frozenset({"machine_passed", "machine_failed"})
_DELIVER_MSG_PREFIX = "structured-deliver:legal-review:"


def _finalize_delivered(messages: list) -> bool:
    for msg in messages:
        if getattr(msg, "name", None) != "policy_finalize":
            continue
        artifact = getattr(msg, "artifact", None)
        if isinstance(artifact, dict) and artifact.get("schema_hint") == LEGAL_REVIEW_V1:
            if str(artifact.get("review_status") or "") in _TERMINAL_REVIEW:
                return True
    return False


def config_has_policy_tools(app_config: Any) -> bool:
    return any(str(getattr(tool, "use", "") or "").startswith(TOOL_USE_PREFIX) for tool in getattr(app_config, "tools", None) or [])


def turn_messages(messages: list) -> list:
    """Messages from the latest unnamed HumanMessage onward (current user turn)."""
    start = 0
    for i, msg in enumerate(messages or []):
        if isinstance(msg, HumanMessage) and not getattr(msg, "name", None):
            start = i
    return list((messages or [])[start:])


def flow_active(messages: list) -> bool:
    for msg in turn_messages(messages):
        if getattr(msg, "name", None) in POLICY_TOOLS:
            return True
        for call in getattr(msg, "tool_calls", None) or []:
            if call_name(call) in POLICY_TOOLS:
                return True
        for call in getattr(msg, "invalid_tool_calls", None) or []:
            if call_name(call) in POLICY_TOOLS:
                return True
    return False


def _message_field(message: Any, key: str) -> Any:
    value = getattr(message, key, None)
    if value is not None:
        return value
    if isinstance(message, dict):
        return message.get(key)
    return None


def extract_legal_review_artifact(messages: list) -> dict[str, Any] | None:
    """Return the latest terminal ``legal-review.v1`` payload from checkpoint messages."""
    for message in reversed(messages or []):
        if _message_field(message, "name") != "policy_finalize":
            continue
        artifact = _message_field(message, "artifact")
        if not isinstance(artifact, dict):
            continue
        if artifact.get("schema_hint") != LEGAL_REVIEW_V1:
            continue
        if str(artifact.get("review_status") or "") in _TERMINAL_REVIEW:
            return artifact
    return None


def finalize_delivered(messages: list) -> bool:
    turn = turn_messages(messages)
    if _finalize_delivered(turn):
        return True
    # Legacy retry gate: finalize ToolMessage.content was JSON before structured delivery.
    for msg in turn:
        if getattr(msg, "name", None) != "policy_finalize":
            continue
        raw = getattr(msg, "content", None)
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("retry") is True:
            continue
        if data.get("retry") is False or "result" in data or data.get("ok") is not None:
            return True
    return False


def reminder_count(messages: list) -> int:
    return sum(1 for msg in turn_messages(messages) if isinstance(msg, HumanMessage) and getattr(msg, "name", None) == REMINDER_NAME)


def has_evidence_session(messages: list) -> bool:
    """True when prepare (auto-retrieve) or retrieve left a usable artifact."""
    for msg in turn_messages(messages):
        if not isinstance(msg, ToolMessage):
            continue
        if getattr(msg, "name", None) not in ("policy_prepare", "policy_retrieve"):
            continue
        artifact = getattr(msg, "artifact", None)
        if isinstance(artifact, dict) and (isinstance(artifact.get("scaffold"), dict) or isinstance(artifact.get("packs"), list)):
            return True
    return False


def next_step(messages: list) -> str:
    names = {getattr(msg, "name", None) for msg in turn_messages(messages)}
    if has_evidence_session(messages) or "policy_retrieve" in names:
        return "policy_finalize"
    # prepare_tool batch-retrieves; skip standalone retrieve when prepare already ran.
    if "policy_prepare" in names:
        return "policy_finalize"
    return "policy_prepare"


def call_name(call: Any) -> str:
    if isinstance(call, dict):
        return str(call.get("name") or "")
    return str(getattr(call, "name", "") or "")


def flow_messages(request: ModelRequest) -> list:
    state = request.state if isinstance(request.state, dict) else {}
    messages = state.get("messages")
    if isinstance(messages, list) and messages:
        return messages
    return list(request.messages or [])


def bind_next_step(request: ModelRequest) -> ModelRequest:
    """Once a policy tool has started, force the next required tool only."""
    messages = flow_messages(request)
    if not flow_active(messages) or finalize_delivered(messages):
        return request

    step = next_step(messages)
    matched = [t for t in request.tools if getattr(t, "name", None) == step]
    if not matched:
        logger.warning("Policy flow: next tool %s missing from request.tools", step)
        return request

    settings = dict(request.model_settings or {})
    settings["parallel_tool_calls"] = False
    logger.info("Policy flow: forcing tool_choice=%s", step)
    return request.override(tools=matched, tool_choice=step, model_settings=settings)


def extract_finalize_raw(ai: AIMessage) -> tuple[str, str] | None:
    """Pull raw policy_finalize arguments from provider payload / invalid calls."""
    kwargs = getattr(ai, "additional_kwargs", None) or {}
    for raw in kwargs.get("tool_calls") or []:
        if not isinstance(raw, dict):
            continue
        function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
        name = str(raw.get("name") or function.get("name") or "")
        if name != "policy_finalize":
            continue
        args = function.get("arguments")
        if args is None:
            args = raw.get("arguments") or raw.get("args")
        if isinstance(args, dict):
            args = json.dumps(args, ensure_ascii=False)
        if isinstance(args, str) and args.strip():
            return str(raw.get("id") or "salvage-finalize"), args

    for inv in getattr(ai, "invalid_tool_calls", None) or []:
        if not isinstance(inv, dict) or call_name(inv) != "policy_finalize":
            continue
        args = inv.get("args") or inv.get("arguments")
        if isinstance(args, dict) and args:
            draft = args.get("draft", args)
            if not isinstance(draft, str):
                draft = json.dumps(draft, ensure_ascii=False)
            if draft.strip():
                return str(inv.get("id") or "salvage-finalize"), draft
        if isinstance(args, str) and args.strip():
            return str(inv.get("id") or "salvage-finalize"), args

    for call in getattr(ai, "tool_calls", None) or []:
        if call_name(call) != "policy_finalize":
            continue
        args = call.get("args") if isinstance(call, dict) else getattr(call, "args", None)
        if not isinstance(args, dict):
            continue
        draft = args.get("draft")
        if draft is None:
            continue
        if not isinstance(draft, str):
            draft = json.dumps(draft, ensure_ascii=False)
        if draft.strip():
            call_id = ""
            if isinstance(call, dict):
                call_id = str(call.get("id") or "")
            else:
                call_id = str(getattr(call, "id", "") or "")
            return call_id or "salvage-finalize", draft
    return None


def has_broken_finalize(ai: AIMessage) -> bool:
    if any(call_name(c) == "policy_finalize" for c in (getattr(ai, "invalid_tool_calls", None) or [])):
        return True
    kwargs = getattr(ai, "additional_kwargs", None) or {}
    for raw in kwargs.get("tool_calls") or []:
        if not isinstance(raw, dict):
            continue
        function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
        name = str(raw.get("name") or function.get("name") or "")
        if name == "policy_finalize":
            return True
    return False


def command_to_end(cmd: Any) -> dict[str, Any]:
    update = getattr(cmd, "update", None) or {}
    out: dict[str, Any] = {"jump_to": "end", "messages": list(update.get("messages") or [])}
    if update.get("artifacts"):
        out["artifacts"] = update["artifacts"]
    return out


def salvage_or_fail(state: AgentState, last_ai: AIMessage) -> dict[str, Any] | None:
    """When evidence is ready, salvage broken finalize args once — never re-prompt LLM."""
    messages = list(state.get("messages") or [])
    if not has_evidence_session(messages):
        return None

    raw = extract_finalize_raw(last_ai)
    if raw is None:
        if not has_broken_finalize(last_ai):
            return None
        logger.warning("Policy flow: broken policy_finalize with no salvageable args — fail fast")
        return hard_fail(last_ai, "policy_finalize arguments were invalid and could not be recovered")

    tool_call_id, draft_raw = raw
    logger.info("Policy flow: salvaging policy_finalize args (%s chars)", len(draft_raw))
    from deerflow.policy_review.tools import run_finalize

    runtime = SimpleNamespace(state=state)
    cmd = run_finalize(
        runtime=runtime,
        draft=draft_raw,
        tool_call_id=tool_call_id,
        allow_retry=False,
    )
    return command_to_end(cmd)


def hard_fail(last_ai: AIMessage, detail: str) -> dict[str, Any]:
    from deerflow.policy_review.render import humanize_error, render_report

    result = machine_failed_result(detail=humanize_error(detail))
    result["report"] = render_report(result)
    delivered = clone_ai_message_with_tool_calls(
        last_ai,
        [],
        content=str(result.get("report") or ""),
    )
    return {"jump_to": "end", "messages": [delivered]}


class PolicyFlowMiddleware(AgentMiddleware[AgentState]):
    """After a policy tool starts, require finalize (or machine_failed) — never prose exit."""

    state_schema = AgentState

    def nudge(self, *, last_ai: AIMessage, messages: list, count: int) -> dict[str, Any]:
        step = next_step(messages)
        if count >= MAX_REMINDERS:
            detail = f"Policy review incomplete: model exited before policy_finalize after {MAX_REMINDERS} reminders (next expected: {step})."
            logger.warning(detail)
            return hard_fail(last_ai, detail)

        # Silent rebind: tool_choice already forces the next tool; avoid token-heavy reminders.
        logger.info("Policy flow incomplete — silent rebind to %s (%s/%s)", step, count + 1, MAX_REMINDERS)
        reminder = HumanMessage(
            name=REMINDER_NAME,
            content=(f"<system_reminder>\nCall `{step}` now. For policy_finalize pass draft as a JSON string with summary + findings[{{risk,text,quote,citation_ids,section,suggestion}}].\n</system_reminder>"),
            additional_kwargs={"hide_from_ui": True},
        )
        cleared = clone_ai_message_with_tool_calls(last_ai, [], content="")
        return {"jump_to": "model", "messages": [cleared, reminder]}

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(bind_next_step(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(bind_next_step(request))

    @hook_config(can_jump_to=["model", "end"])
    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = list(state.get("messages") or [])
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)

        if finalize_delivered(messages):
            if last_ai and not last_ai.tool_calls and not str(getattr(last_ai, "id", "") or "").startswith(_DELIVER_MSG_PREFIX) and str(getattr(last_ai, "content", "") or "").strip():
                cleared = clone_ai_message_with_tool_calls(last_ai, [], content="")
                return {"jump_to": "end", "messages": [cleared]}
            return None

        if not flow_active(messages):
            return None

        if not last_ai:
            return None

        # Valid tool calls still executing — do not intercept.
        if last_ai.tool_calls:
            return None

        # Broken finalize args (invalid_tool_calls / raw provider payload) →
        # salvage once in-process or fail-fast. Never burn another LLM round.
        salvaged = salvage_or_fail(state, last_ai)
        if salvaged is not None:
            return salvaged

        return self.nudge(
            last_ai=last_ai,
            messages=messages,
            count=reminder_count(messages),
        )

    @hook_config(can_jump_to=["model", "end"])
    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self.after_model(state, runtime)
