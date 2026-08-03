"""Attach structured delivery payloads onto API channel values snapshots."""

from __future__ import annotations

from typing import Any

from deerflow.policy_review.contract import LEGAL_REVIEW_V1
from deerflow.policy_review.flow import extract_legal_review_artifact


def attach_structured_delivery(response: dict[str, Any]) -> dict[str, Any]:
    """If checkpoint messages contain a terminal legal-review artifact, expose it.

    No-op when ``messages`` is missing or no review artifact is found.
    """
    messages = response.get("messages") if isinstance(response, dict) else None
    if not isinstance(messages, list):
        return response

    artifact = extract_legal_review_artifact(messages)
    if not isinstance(artifact, dict):
        return response

    schema = str(artifact.get("schema_hint") or LEGAL_REVIEW_V1)
    response["structured_delivery"] = {
        "status": "ok",
        "schema": schema,
        "payload": artifact,
    }
    return response
