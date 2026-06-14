"""
One-off / re-ingestion CLI for NCERT chapter figures.

Wraps the same `ncert_ingest_service.ingest_chapter_pdf` used by the upload
endpoint, so the CLI and the API path stay identical.

Usage:
    python -m app.scripts.ingest_ncert_figures \
        --pdf data/ncert_pdfs/iesc105.pdf \
        --chapter-key science_class9_ch05 \
        --class-no 9 --subject Science \
        --chapter-title "Exploring Mixtures and their Separation" --chapter-number 5
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

from app.db.mongo import get_db
from app.services.ncert_ingest_service import ingest_chapter_pdf


async def _run(args: argparse.Namespace) -> None:
    with open(args.pdf, "rb") as fh:
        pdf_bytes = fh.read()

    result = await ingest_chapter_pdf(
        pdf_bytes=pdf_bytes,
        chapter_key=args.chapter_key,
        class_no=args.class_no,
        subject=args.subject,
        source_name=args.pdf.rsplit("/", 1)[-1],
    )

    db = await get_db()
    if not await db.curriculum_chapters.find_one({"chapter_key": args.chapter_key}, {"_id": 1}):
        now = datetime.now(timezone.utc)
        await db.curriculum_chapters.insert_one({
            "chapter_key": args.chapter_key,
            "board": "NCERT",
            "class": args.class_no,
            "subject": args.subject,
            "chapter_number": args.chapter_number,
            "chapter_title": args.chapter_title or args.chapter_key,
            "concepts": [],
            "created_at": now,
            "updated_at": now,
            "source": "ncert_chapter_cli",
        })
        print(f"Seeded curriculum_chapters row for {args.chapter_key}")

    print(f"Ingested {result['figures_count']} figures, {result['pages_count']} pages.")
    for f in result["figure_catalog"]:
        print(f"  {f['id']}  |  Fig {f['figure_number']}  |  {f['caption']}")


def main() -> None:
    p = argparse.ArgumentParser(description="Ingest an NCERT chapter PDF into MongoDB.")
    p.add_argument("--pdf", required=True)
    p.add_argument("--chapter-key", required=True)
    p.add_argument("--class-no", type=int, required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--chapter-title", default="")
    p.add_argument("--chapter-number", type=int, default=0)
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
