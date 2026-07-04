"""
NCERT pagedex retrieval — vectorless, deterministic metadata filter.

The teacher tags subject+chapter+topic at record time (canonical ids from the TOC),
so retrieval is an exact filter on ncert_nodes by chapter_key + section id. No model
on the hot path. Figure images come back as short-lived signed Blob URLs.
"""
from __future__ import annotations

import re
from typing import Any

from . import blob


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _match_sections(topics: list[str] | None, toc: list[dict], chapter_title: str | None) -> tuple[set[str], set[str]]:
    """Map taught topic strings → confident TOC section ids. CONSERVATIVE: only exact
    matches (canonical id, section number, or exact section name) scope; anything vague
    (e.g. the chapter title, partial words) returns nothing → whole-chapter fallback."""
    topic_ids: set[str] = set()
    subtopic_ids: set[str] = set()
    if not topics or not toc:
        return topic_ids, subtopic_ids

    by_id: dict[str, tuple[str, str]] = {}      # id -> (kind, id)
    by_number: dict[str, tuple[str, str]] = {}  # "5.3" -> (kind, id)
    by_name: dict[str, tuple[str, str]] = {}    # norm(name) -> (kind, id)
    for t in toc:
        by_id[t["topic_id"]] = ("topic", t["topic_id"])
        by_number[t["number"]] = ("topic", t["topic_id"])
        by_name[_norm(t["name"])] = ("topic", t["topic_id"])
        for s in t.get("subtopics", []):
            by_id[s["subtopic_id"]] = ("sub", s["subtopic_id"])
            by_number[s["number"]] = ("sub", s["subtopic_id"])
            by_name[_norm(s["name"])] = ("sub", s["subtopic_id"])

    chap_norm = _norm(chapter_title or "")
    for raw in topics:
        t = (raw or "").strip()
        if not t:
            continue
        hit = by_id.get(t)
        if not hit:
            m = re.match(r"^\d+(?:\.\d+)+", t)
            if m and m.group(0) in by_number:
                hit = by_number[m.group(0)]
        if not hit:
            tn = _norm(t)
            if tn and tn == chap_norm:
                continue  # the taught "topic" is the whole chapter → don't scope
            hit = by_name.get(tn)
        if hit:
            (subtopic_ids if hit[0] == "sub" else topic_ids).add(hit[1])
    return topic_ids, subtopic_ids


def _split_canonical_ids(topic_ids: list[str] | None, toc: list[dict]) -> tuple[set[str], set[str]]:
    """Partition selector-provided canonical ids into known topic vs subtopic ids."""
    topics_set: set[str] = set()
    subs_set: set[str] = set()
    if not topic_ids or not toc:
        return topics_set, subs_set
    known_topics = {t["topic_id"] for t in toc}
    known_subs = {s["subtopic_id"] for t in toc for s in t.get("subtopics", [])}
    for tid in topic_ids:
        if tid in known_topics:
            topics_set.add(tid)
        elif tid in known_subs:
            subs_set.add(tid)
    return topics_set, subs_set


async def resolve_grounding(
    db,
    *,
    class_no: int,
    subject: str,
    chapter_key: str | None = None,
    topics: list[str] | None = None,
    topic_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Best NCERT grounding for generation, scoped to the taught section when possible.

    Returns { content, chapter_key, figures, scope } where scope ∈ {section, chapter, concepts}.
    Prefers canonical `topic_ids` (exact id match) when present; else matches `topics`
    (names/numbers) conservatively. Uses the pagedex (ncert_nodes) when the chapter is
    structured; otherwise falls back to the legacy whole-chapter / concept snippet."""
    proj = {"chapter_key": 1, "toc": 1, "chapter_title": 1, "chapter_summary": 1, "concepts": 1}
    ch = None
    if chapter_key:
        ch = await db.curriculum_chapters.find_one({"chapter_key": chapter_key}, proj)
    if not ch:
        ch = await db.curriculum_chapters.find_one(
            {"class": class_no, "subject": {"$regex": f"^{subject}$", "$options": "i"}}, proj
        )
    if ch:
        chapter_key = ch.get("chapter_key", chapter_key)
    toc = (ch or {}).get("toc")

    # Pagedex path (chapter is structured)
    if chapter_key and toc:
        # Canonical ids (from the selectors) win — exact match, no guessing.
        sel_topic_ids, sel_sub_ids = _split_canonical_ids(topic_ids, toc)
        if sel_topic_ids or sel_sub_ids:
            topic_ids_set, subtopic_ids = sel_topic_ids, sel_sub_ids
        else:
            topic_ids_set, subtopic_ids = _match_sections(topics, toc, (ch or {}).get("chapter_title"))
        topic_ids = topic_ids_set
        query: dict[str, Any] = {"chapter_key": chapter_key}
        scope = "chapter"
        if topic_ids or subtopic_ids:
            query["$or"] = [
                {"topic_id": {"$in": list(topic_ids)}},
                {"subtopic_id": {"$in": list(subtopic_ids)}},
            ]
            scope = "section"
        nodes = await db.ncert_nodes.find(query).sort("order", 1).to_list(length=2000)
        if nodes:
            text = "\n".join(n["text"] for n in nodes if n.get("type") == "text" and n.get("text"))[:6000]
            figures = [_figure_item(n) for n in nodes if n.get("type") == "figure"]
            if text:
                return {"content": text, "chapter_key": chapter_key, "figures": figures, "scope": scope}

    # Legacy fallback — whole-chapter text, then concept snippet
    content = ""
    if chapter_key:
        pages = await db.ncert_chapter_text.find(
            {"chapter_key": chapter_key}, {"text": 1, "page": 1, "_id": 0}
        ).sort("page", 1).to_list(length=2000)
        content = "\n".join(p.get("text", "") for p in pages)[:6000]
    if not content and ch:
        concepts = "\n".join(
            f"- {c.get('name','')}: {c.get('explanation','') or c.get('description','')}"
            for c in ch.get("concepts", [])[:6]
        )
        content = (
            f"Chapter: {ch.get('chapter_title','')}\n"
            f"Summary: {ch.get('chapter_summary','')}\nConcepts:\n{concepts}"
        )
    return {"content": content, "chapter_key": chapter_key, "figures": [], "scope": "concepts" if content else "none"}


def _figure_item(n: dict) -> dict[str, Any]:
    fig = n.get("figure") or {}
    item = {
        "figure_id": n["_id"],
        "figure_number": fig.get("figure_number"),
        "caption": fig.get("caption"),
        "page": n.get("page_start"),
    }
    if fig.get("blob_key"):
        item["url"] = blob.figure_url(fig["blob_key"])
    elif fig.get("image_b64"):
        item["image_b64"] = fig["image_b64"]
    return item


async def resolve_ncert_nodes(
    db,
    *,
    chapter_key: str,
    topic_id: str | None = None,
    subtopic_id: str | None = None,
    types: list[str] | None = None,
) -> dict[str, Any]:
    """Return ordered content for a chapter, optionally narrowed to a topic/subtopic.

    { chapter_key, topic_id, subtopic_id, text, tables, figures, nodes_count }
    - text:    concatenated text nodes in reading order
    - tables:  [{markdown, rows, page}]
    - figures: [{figure_number, caption, url|image_b64, page}]
    """
    query: dict[str, Any] = {"chapter_key": chapter_key}
    if subtopic_id:
        query["subtopic_id"] = subtopic_id
    elif topic_id:
        query["topic_id"] = topic_id
    if types:
        query["type"] = {"$in": types}

    cursor = db.ncert_nodes.find(query).sort("order", 1)
    nodes = await cursor.to_list(length=2000)

    text_parts: list[str] = []
    tables: list[dict[str, Any]] = []
    figures: list[dict[str, Any]] = []
    for n in nodes:
        t = n.get("type")
        if t == "text" and n.get("text"):
            text_parts.append(n["text"])
        elif t == "table":
            tbl = n.get("table") or {}
            tables.append({"markdown": tbl.get("markdown", ""), "rows": tbl.get("rows", []),
                           "page": n.get("page_start")})
        elif t == "figure":
            fig = n.get("figure") or {}
            item = {
                "figure_id": n["_id"],
                "figure_number": fig.get("figure_number"),
                "caption": fig.get("caption"),
                "page": n.get("page_start"),
            }
            if fig.get("blob_key"):
                item["url"] = blob.figure_url(fig["blob_key"])
            elif fig.get("image_b64"):
                item["image_b64"] = fig["image_b64"]
            figures.append(item)

    return {
        "chapter_key": chapter_key,
        "topic_id": topic_id,
        "subtopic_id": subtopic_id,
        "text": "\n".join(text_parts),
        "tables": tables,
        "figures": figures,
        "nodes_count": len(nodes),
    }
