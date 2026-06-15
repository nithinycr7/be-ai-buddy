# app/services/mindmap.py
"""
Mind-map generation.

Turns a class's already-distilled vocabulary (the concept titles + the `terms`
block from summary_blocks) into a clean hierarchical TREE — a taxonomy the
student can explore: topic -> category branches -> the real terms as leaves,
with sub-leaves where one idea contains others (e.g. Filtration -> Residue,
Filtrate). Each leaf carries a SHORT note (reusing the real term meaning) so the
UI can reveal a one-line explanation on tap.

Generated lazily from summary_blocks (cheap, focused prompt) so every existing
class gets a map without re-running summary generation, and so leaf notes stay
grounded in the meanings the student already sees.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import settings
from .ai import get_chat_client

logger = logging.getLogger(__name__)

MINDMAP_PROMPT = """You turn a class's vocabulary into a clean MIND MAP (a hierarchy / taxonomy) for a Class {class_no} student.

You are given the topic, the concept titles taught, and the key terms with their meanings.

BUILD A TREE:
- root: the single topic name (short).
- 2-4 branch categories that group the ideas logically (e.g. "Types of Mixtures", "Methods for Solids", "Methods for Liquids"). Invent clear, short category names even if they were not given.
- Under each branch, place the relevant terms / techniques as child nodes.
- A child may itself have children when one idea contains others (e.g. Filtration -> Residue, Filtrate).
- Every leaf (and any term node) gets a "note": a SHORT meaning, max 12 words, child-friendly. Reuse the provided term meanings (shortened) when the label matches a given term.
- Branch categories usually have NO note (or a 4-6 word one).
- Labels MUST be short: 1-3 words. Never put a sentence in a label.
- Cover the given terms. You may add one obvious missing sibling a student clearly needs, but do not invent unrelated content.

Return ONLY valid JSON in EXACTLY this shape:
{{
  "root": "Topic Name",
  "branches": [
    {{ "label": "Category", "children": [
        {{ "label": "Term", "note": "short meaning" }},
        {{ "label": "Term", "note": "short meaning", "children": [
            {{ "label": "Sub-term", "note": "short meaning" }}
        ] }}
    ] }}
  ]
}}
No markdown, no commentary, no extra keys."""

# Sanitisation limits — keep the tree small enough for a calm canvas.
_MAX_BRANCHES = 6
_MAX_CHILDREN = 10
_MAX_DEPTH = 4
_MAX_LABEL = 60
_MAX_NOTE = 140


def _clean_node(raw: Any, depth: int) -> dict[str, Any] | None:
    """Recursively validate one node: {label, note?, children?}."""
    if not isinstance(raw, dict):
        return None
    label = str(raw.get("label", "")).strip()
    if not label:
        return None
    node: dict[str, Any] = {"label": label[:_MAX_LABEL]}

    note = raw.get("note")
    if isinstance(note, str) and note.strip():
        node["note"] = note.strip()[:_MAX_NOTE]

    children_raw = raw.get("children")
    if isinstance(children_raw, list) and depth < _MAX_DEPTH:
        children = []
        for c in children_raw[:_MAX_CHILDREN]:
            cleaned = _clean_node(c, depth + 1)
            if cleaned:
                children.append(cleaned)
        if children:
            node["children"] = children
    return node


def _validate_tree(data: Any, fallback_root: str) -> dict[str, Any]:
    """Coerce LLM output into a clean {root, branches:[...]} tree or raise."""
    if not isinstance(data, dict):
        raise ValueError("mind map is not an object")

    root = str(data.get("root", "") or fallback_root).strip() or fallback_root

    branches_raw = data.get("branches")
    if not isinstance(branches_raw, list):
        # Some models nest the list under another key.
        branches_raw = next(
            (v for v in data.values() if isinstance(v, list)), []
        )

    branches = []
    for b in branches_raw[:_MAX_BRANCHES]:
        cleaned = _clean_node(b, depth=1)
        if cleaned:
            branches.append(cleaned)

    if not branches:
        raise ValueError("mind map has no usable branches")

    return {"root": root[:_MAX_LABEL], "branches": branches}


def _extract_sources(summary_blocks: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, str]]]:
    """Pull concept titles and term {term, meaning} pairs from summary_blocks."""
    concepts: list[str] = []
    terms: list[dict[str, str]] = []
    for b in summary_blocks or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "concept" and b.get("title"):
            concepts.append(str(b["title"]))
        elif b.get("type") == "terms":
            for it in b.get("items", []) or []:
                if isinstance(it, dict) and it.get("term"):
                    terms.append(
                        {"term": str(it["term"]), "meaning": str(it.get("meaning", ""))}
                    )
    return concepts, terms


def _fallback_tree(topic: str, concepts: list[str], terms: list[dict[str, str]]) -> dict[str, Any]:
    """Used when the LLM is unavailable or returns junk — still a usable map.
    Groups every term as a leaf under a single 'Key Words' branch."""
    leaves = [
        {"label": t["term"], "note": (t.get("meaning") or "")[:_MAX_NOTE]}
        for t in terms
    ] or [{"label": c} for c in concepts]
    return {
        "root": topic or "Today's Topic",
        "branches": [{"label": "Key Words", "children": leaves[:_MAX_CHILDREN]}],
    }


async def generate_mindmap(
    *,
    class_no: int,
    subject: str,
    topic: str,
    summary_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate a hierarchical mind-map tree from existing summary_blocks.

    Returns { "root": str, "branches": [ {label, note?, children?}, ... ] }.
    Never raises for content reasons — falls back to a flat term map.
    """
    concepts, terms = _extract_sources(summary_blocks)
    if not concepts and not terms:
        return _fallback_tree(topic, concepts, terms)

    concepts_text = "\n".join(f"- {c}" for c in concepts) or "(none provided)"
    terms_text = "\n".join(
        f"- {t['term']}: {t['meaning']}" for t in terms
    ) or "(none provided)"
    user_message = (
        f"Class {class_no} {subject} — {topic}\n\n"
        f"Concepts taught:\n{concepts_text}\n\n"
        f"Key terms:\n{terms_text}"
    )

    try:
        client = get_chat_client()
        resp = client.chat.completions.create(
            model=settings.GEMINI_CHAT_MODEL,
            messages=[
                {"role": "system", "content": MINDMAP_PROMPT.format(class_no=class_no)},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        raw = resp.choices[0].message.content
        return _validate_tree(json.loads(raw), fallback_root=topic)
    except Exception as e:  # noqa: BLE001 — never break the tab over a bad generation
        logger.error(f"Mind map generation failed for topic='{topic}': {e}")
        return _fallback_tree(topic, concepts, terms)
