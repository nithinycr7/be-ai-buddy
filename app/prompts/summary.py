"""Summary-blocks prompt + its output contract.

The prompt defines the block format; validate_blocks() enforces it. Both the
regenerate-summary path (daily_class_service) and the transcript path
(services/summary_blocks) import these — one source of truth.
"""
from __future__ import annotations


SUMMARY_PROMPT = """You are creating a revision summary for a Class {class_no} student who attended this class today.
You have two sources. Blend them into ONE confident voice per concept.
Never show them as separate competing paragraphs.

BLENDING RULES:
- Use teacher analogies and examples — keep their phrasing
- Use NCERT for precise facts, formulas, definitions
- Write ONE explanation per concept that honours both sources naturally
- If teacher simplified something NCERT states precisely: keep teacher framing, add NCERT precision
- Never write "teacher said X, NCERT says Y" — student reads ONE clear thing

CLASS LEVEL GUIDE:
- Class 3-5: Simple everyday words. Max 3 key terms. No formulas.
- Class 6-7: Simple scientific vocabulary. Max 5 key terms. Basic formulas.
- Class 8-9: Standard terminology. Concise definitions. Include formulas.

REQUIRED BLOCK ORDER:
1. concept blocks (2-4) — each must have:
   {{ "type": "concept", "title": "...", "content": "...", "icon": "<1 emoji that represents this concept visually>",
      "sources": ["teacher", "ncert"] }}
   sources options: ["teacher","ncert"] if both used | ["ncert"] if teacher didn't cover it | ["teacher"] if not in NCERT

2. analogy block — REQUIRED. Create a vivid real-world comparison that makes the concept memorable.
   If the teacher used one, keep their exact words. Otherwise invent a strong one.
   {{ "type": "analogy", "content": "..." }}

3. formula block — ONLY for Math/Science with an equation:
   {{ "type": "formula", "label": "The equation", "expression": "...", "note": "..." }}

4. terms block — key vocabulary, always visible with definition:
   {{ "type": "terms", "items": [{{ "term": "...", "meaning": "..." }}] }}

OPTIONAL additional types (use only if they genuinely fit):
- "fact":     {{"type":"fact","items":["..."]}}
- "timeline": {{"type":"timeline","items":[{{"date":"1857","event":"..."}}]}}
- "rule":     {{"type":"rule","title":"...","content":"...","example":"..."}}
- "steps":    {{"type":"steps","title":"...","steps":["...","..."]}}

Return ONLY valid JSON. 4-7 blocks total. NEVER include a checkpoint block. NEVER show NCERT quotes separately."""

VALID_BLOCK_TYPES = {"concept", "terms", "steps", "analogy", "formula", "fact", "timeline", "rule"}


def validate_blocks(data) -> list[dict]:
    """Validate/sanitize LLM JSON (list, {"blocks":[...]}, or nested-list dict)."""
    if isinstance(data, list):
        blocks = data
    elif isinstance(data, dict):
        blocks = data.get("blocks")
        if not isinstance(blocks, list):
            blocks = next((v for v in data.values() if isinstance(v, list)), [])
    else:
        blocks = []
    if not isinstance(blocks, list) or len(blocks) == 0:
        raise ValueError("No blocks in response")

    cleaned = []
    for b in blocks[:10]:
        if not isinstance(b, dict) or "type" not in b:
            continue
        if b["type"] not in VALID_BLOCK_TYPES:
            continue
        cleaned.append(b)

    if "concept" not in {b["type"] for b in cleaned}:
        raise ValueError("Missing required 'concept' block")
    return cleaned

