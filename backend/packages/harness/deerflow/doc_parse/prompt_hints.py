"""Derive segmentation hints from caller-supplied segment_prompt (JSON examples)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from langchain_core.utils.json import parse_json_markdown

_NUMERIC_RUN = re.compile(r"[0-9一二三四五六七八九十百千]+")
_DIGIT_RUN = re.compile(r"\d+")
_JSON_OBJECT_RE = re.compile(r"\{[^{}]*\"details\"\s*:\s*\[[\s\S]*?\]\s*[^{}]*\}")

_LABEL_FIELD_CANDIDATES = ("segment_label", "label", "clause_id", "section_id")
_CHAPTER_FIELD_CANDIDATES = ("chapter_path", "chapter", "section_path")
_BODY_FIELD_CANDIDATES = ("body", "text", "content")

_PLACEHOLDER_VALUES = frozenset({"…", "...", "…", "xxx", "XXX"})


@dataclass(frozen=True)
class PromptHints:
    """Patterns inferred from segment_prompt JSON examples."""

    label_field: str = "segment_label"
    chapter_field: str = "chapter_path"
    body_field: str = "body"
    label_pattern: re.Pattern[str] | None = None
    chapter_pattern: re.Pattern[str] | None = None
    split_patterns: tuple[re.Pattern[str], ...] = field(default_factory=tuple)

    def matches_label(self, text: str) -> bool:
        value = text.strip()
        if not value or self.label_pattern is None:
            return False
        return self.label_pattern.fullmatch(value) is not None

    def looks_like_chapter(self, chapter: str, *, label: str = "") -> bool:
        value = chapter.strip()
        if not value or value == label.strip():
            return False
        if self.matches_label(value):
            return False
        if self.chapter_pattern is not None and self.chapter_pattern.search(value):
            return True
        return False


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


def _chapter_prefix_example(example: str) -> str:
    parts = example.strip().split()
    if not parts:
        return example.strip()
    if len(parts) >= 2 and (_DIGIT_RUN.fullmatch(parts[1]) or _NUMERIC_RUN.fullmatch(parts[1])):
        return f"{parts[0]} {parts[1]}"
    return parts[0]


def _compile_pattern(example: str, *, fullmatch: bool = False, ignore_case: bool = False) -> re.Pattern[str] | None:
    body = _example_to_regex(example)
    if not body:
        return None
    flags = re.IGNORECASE if ignore_case else 0
    if fullmatch:
        return re.compile(rf"^{body}$", flags)
    return re.compile(body, flags)


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


def _pick_field(item: dict[str, object], candidates: tuple[str, ...]) -> tuple[str, str | None]:
    for name in candidates:
        if name in item:
            return name, _first_str(item[name])
    return candidates[0], None


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
    """Parse JSON shape/examples embedded in segment_prompt."""
    example_obj = _extract_json_example(segment_prompt)
    if not example_obj:
        return PromptHints()

    details = example_obj.get("details")
    if not isinstance(details, list) or not details:
        return PromptHints()

    first = details[0]
    if not isinstance(first, dict):
        return PromptHints()

    label_field, label_example = _pick_field(first, _LABEL_FIELD_CANDIDATES)
    chapter_field, chapter_example = _pick_field(first, _CHAPTER_FIELD_CANDIDATES)
    body_field, _ = _pick_field(first, _BODY_FIELD_CANDIDATES)

    ignore_case = bool(label_example and _english_example(label_example))
    label_pattern = _compile_pattern(label_example, fullmatch=True, ignore_case=ignore_case) if label_example else None
    chapter_pattern = None
    if chapter_example:
        chapter_prefix = _chapter_prefix_example(chapter_example)
        chapter_pattern = _compile_pattern(chapter_prefix, fullmatch=False, ignore_case=ignore_case)

    split_patterns: list[re.Pattern[str]] = []
    if label_example:
        label_regex = _example_to_regex(label_example)
        if label_regex:
            split = _split_pattern_from_label(label_regex, ignore_case=ignore_case)
            if split is not None:
                split_patterns.append(split)

    return PromptHints(
        label_field=label_field,
        chapter_field=chapter_field,
        body_field=body_field,
        label_pattern=label_pattern,
        chapter_pattern=chapter_pattern,
        split_patterns=tuple(split_patterns),
    )
