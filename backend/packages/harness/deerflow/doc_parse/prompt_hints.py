"""Infer markdown split patterns from segment_prompt JSON examples."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from langchain_core.utils.json import parse_json_markdown

_NUMERIC_RUN = re.compile(r"[0-9一二三四五六七八九十百千]+")
_DIGIT_RUN = re.compile(r"\d+")
_JSON_OBJECT_RE = re.compile(r"\{[^{}]*\"details\"\s*:\s*\[[\s\S]*?\]\s*[^{}]*\}")
_LABEL_FIELD_CANDIDATES = ("segment_label", "label", "clause_id", "section_id")
_PLACEHOLDER_VALUES = frozenset({"…", "...", "xxx", "XXX"})


@dataclass(frozen=True)
class PromptHints:
    split_patterns: tuple[re.Pattern[str], ...] = field(default_factory=tuple)


def _example_to_regex(example: str) -> str | None:
    example = example.strip()
    if not example or example in _PLACEHOLDER_VALUES:
        return None

    parts: list[str] = []
    index = 0
    length = len(example)
    while index < length:
        num_match = _NUMERIC_RUN.match(example, index)
        if num_match:
            parts.append("[0-9一二三四五六七八九十百千]+")
            index = num_match.end()
            continue
        digit_match = _DIGIT_RUN.match(example, index)
        if digit_match:
            parts.append(r"\d+")
            index = digit_match.end()
            continue
        next_num = length
        for pattern in (_NUMERIC_RUN, _DIGIT_RUN):
            found = pattern.search(example, index)
            if found:
                next_num = min(next_num, found.start())
        literal = example[index:next_num]
        if literal:
            parts.append(re.escape(literal))
        index = next_num if next_num > index else index + 1

    joined = "".join(parts)
    return joined or None


def _split_pattern_from_label(label_regex: str, *, ignore_case: bool = False) -> re.Pattern[str] | None:
    flags = re.MULTILINE | (re.IGNORECASE if ignore_case else 0)
    return re.compile(
        rf"(?=^(?:\*\*)?{label_regex}(?:\*\*)?(?:[\s\u3000]|$))",
        flags,
    )


def _first_str(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _pick_label_example(item: dict[str, object]) -> str | None:
    for name in _LABEL_FIELD_CANDIDATES:
        if name in item:
            found = _first_str(item[name])
            if found:
                return found
    return None


def _extract_json_example(prompt: str) -> dict[str, object] | None:
    for match in _JSON_OBJECT_RE.finditer(prompt):
        candidate = match.group(0)
        try:
            parsed = parse_json_markdown(candidate)
        except Exception:
            try:
                parsed = json.loads(candidate)
            except Exception:
                continue
        if isinstance(parsed, dict) and isinstance(parsed.get("details"), list):
            return parsed
    return None


def _english_example(example: str) -> bool:
    letters = sum(1 for ch in example if ch.isascii() and ch.isalpha())
    return letters >= 2


def extract_prompt_hints(segment_prompt: str) -> PromptHints:
    """Build line-start split patterns from the first details[] example in segment_prompt."""
    example_obj = _extract_json_example(segment_prompt)
    if not example_obj:
        return PromptHints()

    details = example_obj.get("details")
    if not isinstance(details, list) or not details:
        return PromptHints()

    first = details[0]
    if not isinstance(first, dict):
        return PromptHints()

    label_example = _pick_label_example(first)
    if not label_example:
        return PromptHints()

    label_regex = _example_to_regex(label_example)
    if not label_regex:
        return PromptHints()

    split = _split_pattern_from_label(label_regex, ignore_case=_english_example(label_example))
    if split is None:
        return PromptHints()
    return PromptHints(split_patterns=(split,))
