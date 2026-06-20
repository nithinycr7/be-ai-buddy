"""
NCERT ingestion pipeline — extract → structure → store.

The single entry point the CLI and (future) queue worker both call. Idempotent and
re-runnable: nodes upsert by stable id, the TOC replaces in place. Communicates only
via shared Mongo + Blob, so it can be lifted into a standalone worker unchanged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import fitz  # PyMuPDF

from app.db.mongo import get_db
from app.services.ncert_ingest_service import _extract  # reuse the proven extractor
from . import blob
from .nodes import build_nodes
from .structure import build_toc, detect_headings

logger = logging.getLogger(__name__)

EXTRACTOR_VERSION = "v1"


async def ingest_chapter(
    *,
    pdf_bytes: bytes,
    chapter_key: str,
    class_no: int,
    subject: str,
    chapter_title: str = "",
    chapter_number: int = 0,
    board: str = "NCERT",
    source_name: str = "uploaded.pdf",
) -> dict[str, Any]:
    """Full pagedex build for one chapter PDF. Returns a summary dict."""
    # 1) TOC from real section headings
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_count = doc.page_count
    headings = detect_headings(doc)
    doc.close()
    toc = build_toc(headings, chapter_key=chapter_key, page_count=page_count)

    # 2) raw extraction (text + tables + figures) — reuse the proven extractor
    figures, pages = _extract(
        pdf_bytes, chapter_key=chapter_key, class_no=class_no,
        subject=subject, source_name=source_name,
    )

    # 3) figure binaries → Blob (fallback to base64 in-node if unconfigured)
    def figure_sink(figure_id: str, png: bytes) -> str | None:
        if not blob.is_configured():
            return None
        try:
            key = blob.figure_blob_key(
                class_no=class_no, subject=subject, chapter_key=chapter_key, figure_id=figure_id
            )
            return blob.upload_figure_png(key, png)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("[NCERT] figure blob upload failed (%s): %s", figure_id, e)
            return None

    ingested_at = datetime.now(timezone.utc).isoformat()
    nodes = build_nodes(
        chapter_key=chapter_key, board=board, class_no=class_no, subject=subject,
        chapter_number=chapter_number, pages=pages, figures=figures, toc=toc,
        extractor_version=EXTRACTOR_VERSION, source_pdf=source_name,
        ingested_at=ingested_at, figure_sink=figure_sink,
    )

    # 4) persist — nodes upsert by id; TOC + status on the chapter doc
    db = await get_db()
    for n in nodes:
        await db.ncert_nodes.replace_one({"_id": n["_id"]}, n, upsert=True)

    # backward-compat: keep ncert_chapter_text (text+tables) so the existing
    # resolve_ncert_content() path keeps working for new chapters too.
    for pg in pages:
        await db.ncert_chapter_text.replace_one(
            {"chapter_key": chapter_key, "page": pg["page"]}, pg, upsert=True
        )

    now = datetime.now(timezone.utc)
    await db.curriculum_chapters.update_one(
        {"chapter_key": chapter_key},
        {
            "$set": {
                "chapter_key": chapter_key,
                "board": board,
                "class": class_no,
                "subject": subject,
                "chapter_number": chapter_number or _chapter_no_from_toc(toc),
                "toc": toc,
                "status": "structured",
                "extractor_version": EXTRACTOR_VERSION,
                "updated_at": now,
            },
            "$setOnInsert": {
                "chapter_title": chapter_title or chapter_key,
                "created_at": now,
            },
        },
        upsert=True,
    )

    counts = {t: 0 for t in ("text", "table", "figure")}
    for n in nodes:
        counts[n["type"]] = counts.get(n["type"], 0) + 1
    logger.info(
        "[NCERT] structured chapter_key=%s topics=%d nodes=%d %s",
        chapter_key, len(toc), len(nodes), counts,
    )
    return {
        "chapter_key": chapter_key,
        "pages": page_count,
        "topics": [{"number": t["number"], "name": t["name"],
                    "subtopics": len(t["subtopics"])} for t in toc],
        "node_counts": counts,
        "blob": blob.is_configured(),
    }


def _chapter_no_from_toc(toc: list[dict[str, Any]]) -> int:
    for t in toc:
        head = t.get("number", "").split(".")[0]
        if head.isdigit():
            return int(head)
    return 0
