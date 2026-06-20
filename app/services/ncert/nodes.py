"""
Build `ncert_nodes` — the typed, section-tagged content nodes (the pagedex).

One node per text page / table / figure, each assigned to its TOC topic+subtopic by
page-range lookup, in reading order. Figure binaries go to Blob (blob_key), never
base64 — with a base64 fallback only when Blob isn't configured (local dev).
"""
from __future__ import annotations

import base64
from typing import Any, Callable

from .structure import TocIndex


def _png_bytes(image_b64: str | None) -> bytes | None:
    if not image_b64:
        return None
    raw = image_b64.split(",", 1)[1] if image_b64.startswith("data:") else image_b64
    try:
        return base64.b64decode(raw)
    except Exception:
        return None


def build_nodes(
    *,
    chapter_key: str,
    board: str,
    class_no: int,
    subject: str,
    chapter_number: int,
    pages: list[dict[str, Any]],
    figures: list[dict[str, Any]],
    toc: list[dict[str, Any]],
    extractor_version: str,
    source_pdf: str,
    ingested_at: str,
    figure_sink: Callable[[str, bytes], str | None] | None = None,
) -> list[dict[str, Any]]:
    """Assemble ncert_nodes docs (idempotent stable ids). `figure_sink(figure_id, png)`
    uploads bytes and returns a blob_key; if absent/None we keep base64 as fallback."""
    idx = TocIndex(toc)
    figs_by_page: dict[int, list[dict]] = {}
    for f in figures:
        figs_by_page.setdefault(f.get("page", 0), []).append(f)

    nodes: list[dict[str, Any]] = []
    order = 0

    def base(node_id: str, node_type: str, page: int) -> dict[str, Any]:
        a = idx.assign(page)
        return {
            "_id": node_id,
            "chapter_key": chapter_key,
            "board": board,
            "class": class_no,
            "subject": subject,
            "chapter_number": chapter_number,
            "type": node_type,
            "topic": a["topic"],
            "topic_id": a["topic_id"],
            "subtopic": a["subtopic"],
            "subtopic_id": a["subtopic_id"],
            "order": None,  # set below
            "page_start": page,
            "page_end": page,
            "source_pdf": source_pdf,
            "extractor_version": extractor_version,
            "ingested_at": ingested_at,
        }

    for pg in sorted(pages, key=lambda p: p.get("page", 0)):
        page = pg.get("page", 0)

        text = (pg.get("text") or "").strip()
        if text:
            n = base(f"{chapter_key}::text::{page}", "text", page)
            n["text"] = text
            nodes.append(n)

        for i, tbl in enumerate(pg.get("tables") or []):
            n = base(f"{chapter_key}::table::{page}::{i}", "table", page)
            n["table"] = {"rows": tbl, "markdown": _table_md(tbl)}
            nodes.append(n)

        for f in figs_by_page.get(page, []):
            n = base(f["_id"], "figure", page)
            fig = {
                "figure_number": f.get("figure_number"),
                "caption": f.get("caption"),
                "width": f.get("width"),
                "height": f.get("height"),
            }
            png = _png_bytes(f.get("image_b64"))
            blob_key = figure_sink(f["_id"], png) if (figure_sink and png) else None
            if blob_key:
                fig["blob_key"] = blob_key
            else:
                fig["image_b64"] = f.get("image_b64")  # local-dev fallback
            n["figure"] = fig
            nodes.append(n)

    # reading order: page, then text < table < figure
    rank = {"text": 0, "table": 1, "figure": 2}
    nodes.sort(key=lambda n: (n["page_start"], rank.get(n["type"], 9), n["_id"]))
    for n in nodes:
        n["order"] = order
        order += 1
    return nodes


def _table_md(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    out = [" | ".join(rows[0])]
    out.append(" | ".join("---" for _ in rows[0]))
    for r in rows[1:]:
        out.append(" | ".join(r))
    return "\n".join(out)
