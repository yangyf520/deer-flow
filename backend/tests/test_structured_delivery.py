"""Tests for deerflow.agents.structured_delivery."""

from __future__ import annotations

from deerflow.agents.structured_delivery import attach_structured_delivery
from deerflow.policy_review.flow import extract_legal_review_artifact


def test_extract_legal_review_artifact_from_serialized_messages() -> None:
    payload = {"schema_hint": "legal-review.v1", "review_status": "machine_passed", "summary": "ok"}
    messages = [
        {"type": "tool", "name": "policy_finalize", "artifact": payload},
    ]
    assert extract_legal_review_artifact(messages) == payload

    response = attach_structured_delivery({"messages": messages})
    assert response["structured_delivery"]["status"] == "ok"
    assert response["structured_delivery"]["schema"] == "legal-review.v1"
    assert response["structured_delivery"]["payload"] == payload


def test_attach_structured_delivery_noop_without_messages() -> None:
    response = {"title": "demo"}
    assert attach_structured_delivery(response) is response


def test_attach_structured_delivery_noop_without_review_artifact() -> None:
    response = {"messages": [{"type": "ai", "content": "hello"}]}
    assert attach_structured_delivery(response) is response
