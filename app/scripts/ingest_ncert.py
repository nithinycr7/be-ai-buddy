"""
NCERT pagedex ingestion CLI (structure → nodes → blob).

Builds the real-TOC content nodes for a chapter PDF via app.services.ncert.pipeline.
The CLI and the (future) queue worker call the same `ingest_chapter`.

Usage:
    python -m app.scripts.ingest_ncert \
        --pdf data/ncert_pdfs/iesc105.pdf \
        --chapter-key science_class9_ch05 \
        --class-no 9 --subject Science \
        --chapter-title "Exploring Mixtures and their Separation" --chapter-number 5
"""
from __future__ import annotations

import argparse
import asyncio
import json

from app.services.ncert.pipeline import ingest_chapter


async def _run(args: argparse.Namespace) -> None:
    with open(args.pdf, "rb") as fh:
        pdf_bytes = fh.read()

    result = await ingest_chapter(
        pdf_bytes=pdf_bytes,
        chapter_key=args.chapter_key,
        class_no=args.class_no,
        subject=args.subject,
        chapter_title=args.chapter_title,
        chapter_number=args.chapter_number,
        source_name=args.pdf.rsplit("/", 1)[-1],
    )
    print(json.dumps(result, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Build the NCERT pagedex for a chapter PDF.")
    p.add_argument("--pdf", required=True)
    p.add_argument("--chapter-key", required=True)
    p.add_argument("--class-no", type=int, required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--chapter-title", default="")
    p.add_argument("--chapter-number", type=int, default=0)
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
