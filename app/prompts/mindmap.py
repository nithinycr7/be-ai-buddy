"""Mind-map generation prompt."""
from __future__ import annotations


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
