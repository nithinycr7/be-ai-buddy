"""
Instant, audio-free summary flow for demos.

Drop a transcript (inline, from a file, or already in the DB) and generate the
approved summary_blocks straight into a classes_daily document.

Examples:
    # paste transcript text and summarize
    python -m app.scripts.gen_summary_from_transcript \
        --daily-id 6a2edcec8627d7d26b7ed77b --file transcript.txt

    # use a transcript already stamped (transcripts[daily_id] or daily_transcripts[id])
    python -m app.scripts.gen_summary_from_transcript --daily-id 6a2edcec...
    python -m app.scripts.gen_summary_from_transcript --daily-id 6a2edcec... --transcript-id <id>
"""
from __future__ import annotations

import argparse
import asyncio

from app.db.mongo import get_db
from app.services.summary_blocks import summarize_daily_from_transcript


async def _run(args: argparse.Namespace) -> None:
    text = None
    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            text = fh.read()
    elif args.text:
        text = args.text

    db = await get_db()

    # Ensures the classes_daily record (creates it if --daily-id is omitted and
    # class/subject are given), persists the transcript, and stamps summary_blocks.
    result = await summarize_daily_from_transcript(
        db, daily_id=args.daily_id, class_no=args.class_no, section=args.section,
        subject=args.subject, date=args.date, topics=args.topics.split(",") if args.topics else None,
        transcript_text=text, transcript_id=args.transcript_id,
        chapter_key=args.chapter_key, force=args.force,
    )
    if result.get("skipped"):
        print(f"Skipped {result['daily_id']} — {result['reason']} ({result['blocks_count']} blocks). Use --force to regenerate.")
    else:
        print(
            f"daily_id={result['daily_id']} | {result['blocks_count']} blocks "
            f"({', '.join(result['block_types'])}) | topic '{result['topic']}' "
            f"| used_transcript={result['used_transcript']} ({result['transcript_chars']} chars) "
            f"| chapter_key={result['chapter_key']}"
        )


def main() -> None:
    p = argparse.ArgumentParser(description="Generate summary_blocks for a classes_daily doc from a transcript.")
    p.add_argument("--daily-id", help="existing classes_daily _id (omit to create-if-missing)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--file", help="path to a transcript .txt file")
    g.add_argument("--text", help="inline transcript text")
    p.add_argument("--transcript-id", help="daily_transcripts _id (audio pipeline)")
    p.add_argument("--chapter-key", help="optional NCERT chapter override")
    p.add_argument("--force", action="store_true", help="regenerate even if summary_blocks exist")
    # create-if-missing fields (used when --daily-id is omitted)
    p.add_argument("--class-no", type=int)
    p.add_argument("--section", default="A")
    p.add_argument("--subject")
    p.add_argument("--date", help="ISO date; defaults to today")
    p.add_argument("--topics", help="comma-separated topics")
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
