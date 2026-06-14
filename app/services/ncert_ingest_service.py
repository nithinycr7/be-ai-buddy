"""
NCERT chapter ingestion (figures + text + tables → MongoDB).

Separate from the text-only RAG pipeline in `chunking.py`. This pipeline is the
source of truth for the *exam-centric* SILF story generator: it pulls the real
NCERT textbook figures so a story can display the exact diagram a student will
see on their exam paper — never an LLM-invented image.

Each labelled figure ("Fig. 5.6: ...") gets a stable signature id, e.g.
    NCERT_SCI_9_CH05_FIG_5_6
That id is generated *here* (the DB is the authority) and later handed to the
LLM as a catalog to pick from — the model never invents figure ids.

Collections written:
  ncert_figures        one doc per labelled figure (base64 PNG + caption + id)
  ncert_chapter_text   one doc per page (plain text + extracted tables)
"""
from __future__ import annotations

import base64
import logging
import re
from typing import Any

import fitz  # PyMuPDF

from app.db.mongo import get_db

logger = logging.getLogger(__name__)

# "Fig. 5.6: Solubility curves ..." — the colon form is the authoritative caption
_CAPTION_RE = re.compile(r"Fig(?:ure)?\.?\s*(\d+\.\d+)\s*:\s*(.+)", re.IGNORECASE)

_MIN_DIM = 80  # px — drop icons / rules / decorative slivers

_SUBJECT_CODE = {
    "science": "SCI",
    "mathematics": "MAT",
    "maths": "MAT",
    "social science": "SST",
    "social sciences": "SST",
    "english": "ENG",
    "hindi": "HIN",
}


def _subject_code(subject: str) -> str:
    return _SUBJECT_CODE.get((subject or "").strip().lower(), (subject or "GEN")[:3].upper())


def _chapter_code(chapter_key: str) -> str:
    """science_class9_ch05 -> CH05 ; fallback to a cleaned key."""
    m = re.search(r"ch(\d+)", chapter_key or "", re.IGNORECASE)
    if m:
        return f"CH{int(m.group(1)):02d}"
    return re.sub(r"[^A-Za-z0-9]+", "", (chapter_key or "CH")).upper()[:8] or "CH"


def _figure_id(subject: str, class_no: int, chapter_key: str, figure_number: str) -> str:
    num = figure_number.replace(".", "_")
    return f"NCERT_{_subject_code(subject)}_{class_no}_{_chapter_code(chapter_key)}_FIG_{num}"


def _clean_caption(text: str) -> str:
    # collapse whitespace and trim at a sentence/paren boundary so captions stay short
    text = re.sub(r"\s+", " ", text).strip()
    # cut trailing body text that sometimes runs on after the caption
    text = re.split(r"(?<=[a-z])\.\s+[A-Z]", text)[0]
    return text[:200].strip(" .")


def _pix_to_b64(pix: fitz.Pixmap) -> tuple[str | None, int, int]:
    try:
        if pix.n - pix.alpha >= 4:  # CMYK / other -> convert to RGB
            pix = fitz.Pixmap(fitz.csRGB, pix)
        data = pix.tobytes("png")
        return "data:image/png;base64," + base64.b64encode(data).decode("ascii"), pix.width, pix.height
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("[NCERT] pixmap encode failed: %s", e)
        return None, 0, 0


def _render_clip(page: fitz.Page, clip: fitz.Rect, zoom: float = 2.0) -> tuple[str | None, int, int]:
    """Rasterize a sub-region of the page (used to crop figures out of full-page scans)."""
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
        return _pix_to_b64(pix)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("[NCERT] clip render failed: %s", e)
        return None, 0, 0


def _extract(pdf_bytes: bytes, *, chapter_key: str, class_no: int, subject: str, source_name: str):
    """Pure PyMuPDF extraction. Returns (figures, pages)."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    pages: list[dict[str, Any]] = []
    # figure_number -> {caption, page, caption_rect}
    captioned: dict[str, dict[str, Any]] = {}

    for pno in range(doc.page_count):
        page = doc[pno]
        text = page.get_text("text")

        # page text + tables -> ncert_chapter_text
        tables: list[list[list[str]]] = []
        try:
            for tbl in page.find_tables().tables:
                rows = [[("" if c is None else str(c)) for c in row] for row in tbl.extract()]
                if rows:
                    tables.append(rows)
        except Exception:
            pass
        pages.append({
            "chapter_key": chapter_key,
            "page": pno + 1,
            "text": re.sub(r"\s+", " ", text).strip(),
            "tables": tables,
        })

        # authoritative captions on this page (first occurrence wins)
        for line in text.split("\n"):
            m = _CAPTION_RE.search(line)
            if not m:
                continue
            fignum = m.group(1)
            if fignum in captioned:
                continue
            rects = page.search_for(f"Fig. {fignum}:") or page.search_for(f"Fig {fignum}") or []
            captioned[fignum] = {
                "caption": _clean_caption(m.group(2)),
                "page_index": pno,
                "caption_rect": rects[0] if rects else None,
            }

    # caption rects grouped by page — used to bound a figure's top by the figure above it
    page_caps: dict[int, list[fitz.Rect]] = {}
    for info in captioned.values():
        if info["caption_rect"] is not None:
            page_caps.setdefault(info["page_index"], []).append(info["caption_rect"])

    figures: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for fignum, info in sorted(captioned.items(), key=lambda kv: [int(x) for x in kv[0].split(".")]):
        page = doc[info["page_index"]]
        cap_rect = info["caption_rect"]
        if cap_rect is None:
            continue
        W, H = page.rect.width, page.rect.height
        page_area = W * H

        # image bboxes on this page (location only — we RENDER, never extract pixels,
        # so soft-masked images don't come out black and we always get the real figure)
        boxes: list[fitz.Rect] = []
        try:
            for im in page.get_image_info(xrefs=True):
                bbox = im.get("bbox")
                if not bbox:
                    continue
                r = fitz.Rect(bbox)
                if r.width >= _MIN_DIM and r.height >= _MIN_DIM:
                    boxes.append(r)
        except Exception:
            pass

        # top bound: just under the previous figure's caption on this page (else header)
        prev_bottoms = [r.y1 for r in page_caps.get(info["page_index"], []) if r.y1 <= cap_rect.y0 - 4]
        band_top = (max(prev_bottoms) + 4) if prev_bottoms else (page.rect.y0 + 0.09 * H)

        left, right, top = page.rect.x0 + 0.06 * W, page.rect.x1 - 0.06 * W, band_top
        bottom = cap_rect.y0 - 2

        # tighten to the embedded image bbox sitting in this band, horizontally aligned
        # with the caption (fixes side-by-side sub-figures); skip full-page scans.
        cx = (cap_rect.x0 + cap_rect.x1) / 2
        in_band = [
            r for r in boxes
            if r.y1 <= cap_rect.y0 + 6 and r.y0 >= band_top - 6
            and (r.width * r.height) < 0.80 * page_area
        ]
        if in_band:
            in_band.sort(key=lambda r: (abs((r.x0 + r.x1) / 2 - cx), -(r.width * r.height)))
            b = in_band[0]
            left, right, top = b.x0 - 8, b.x1 + 8, b.y0 - 8

        clip = fitz.Rect(left, top, right, bottom) & page.rect
        if clip.is_empty or clip.height < _MIN_DIM:
            continue
        img_b64, w, h = _render_clip(page, clip)
        if not img_b64:
            continue

        fid = _figure_id(subject, class_no, chapter_key, fignum)
        if fid in seen_ids:
            continue
        seen_ids.add(fid)

        figures.append({
            "_id": fid,
            "chapter_key": chapter_key,
            "class": class_no,
            "subject": subject,
            "figure_number": fignum,
            "caption": info["caption"],
            "image_b64": img_b64,
            "width": w,
            "height": h,
            "source_pdf": source_name,
            "page": info["page_index"] + 1,
        })

    doc.close()
    return figures, pages


async def ingest_chapter_pdf(
    *,
    pdf_bytes: bytes,
    chapter_key: str,
    class_no: int,
    subject: str,
    source_name: str = "uploaded.pdf",
) -> dict[str, Any]:
    """
    Extract figures + page text/tables from a chapter PDF and upsert into Mongo.
    Idempotent: figures keyed by stable signature id, pages keyed by (chapter_key, page).
    """
    figures, pages = _extract(
        pdf_bytes, chapter_key=chapter_key, class_no=class_no, subject=subject, source_name=source_name
    )

    db = await get_db()
    for fig in figures:
        await db.ncert_figures.replace_one({"_id": fig["_id"]}, fig, upsert=True)
    for pg in pages:
        await db.ncert_chapter_text.replace_one(
            {"chapter_key": chapter_key, "page": pg["page"]}, pg, upsert=True
        )

    logger.info(
        "[NCERT] ingested chapter_key=%s figures=%d pages=%d", chapter_key, len(figures), len(pages)
    )
    return {
        "chapter_key": chapter_key,
        "figures_count": len(figures),
        "pages_count": len(pages),
        "figure_catalog": [
            {"id": f["_id"], "figure_number": f["figure_number"], "caption": f["caption"]}
            for f in figures
        ],
    }
