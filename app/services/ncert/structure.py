"""
Structure resolution — turn a chapter PDF into the real NCERT TOC.

NCERT section headings are numbered ("5.1 …", "5.3.1 …") and set in a larger bold
font, so the hierarchy is *encoded in the numbering* and detectable deterministically
— no LLM. We detect headings, build a topic/subtopic tree with page ranges, and give
a page→section index so content nodes can be assigned by page-range lookup.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# "5.1 Title", "5.3.1 Title" — number encodes depth. Excludes "Fig. 5.6" (no leading digit-dot-digit at line start after strip) and bare numbers.
_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)+)\s+(\S.*)$")
_MIN_HEADING_SIZE = 13.0  # body text is ~10-11pt; section headings ~14-15pt


def _line_text(line: dict) -> str:
    return "".join(s.get("text", "") for s in line.get("spans", [])).strip()


def _line_is_bold(line: dict) -> bool:
    return any("bold" in (s.get("font", "").lower()) for s in line.get("spans", []))


def _line_size(line: dict) -> float:
    return max((s.get("size", 0.0) for s in line.get("spans", [])), default=0.0)


def detect_headings(doc) -> list[dict[str, Any]]:
    """Return ordered numbered section headings: {number, level, title, page, y0, size}.
    `level` = numbering depth - 1  (5.1 → 0 = topic, 5.1.1 → 1 = subtopic)."""
    headings: list[dict[str, Any]] = []
    for pno in range(doc.page_count):
        for block in doc[pno].get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                txt = _line_text(line)
                if len(txt) < 4:
                    continue
                m = _HEADING_RE.match(txt)
                if not m:
                    continue
                size = _line_size(line)
                if size < _MIN_HEADING_SIZE or not _line_is_bold(line):
                    continue
                number = m.group(1)
                title = re.sub(r"\s+", " ", m.group(2)).strip(" .:")
                headings.append({
                    "number": number,
                    "level": number.count(".") - 1,  # "5.1"→0, "5.1.1"→1
                    "title": title[:120],
                    "page": pno + 1,                  # 1-indexed
                    "y0": line["spans"][0].get("bbox", [0, 0, 0, 0])[1],
                    "size": size,
                })
    headings.sort(key=lambda h: (h["page"], h["y0"]))
    return headings


def build_toc(headings: list[dict[str, Any]], *, chapter_key: str, page_count: int) -> list[dict[str, Any]]:
    """Build the topic→subtopic tree with page ranges from ordered headings.

    topic_id / subtopic_id = f"{chapter_key}::{number}" — stable and aligned with the
    ids the curriculum selectors emit (`/ncert/topics`).
    """
    topics = [h for h in headings if h["level"] == 0]
    toc: list[dict[str, Any]] = []

    for i, h in enumerate(topics):
        page_start = h["page"]
        page_end = (topics[i + 1]["page"] - 1) if i + 1 < len(topics) else page_count
        if page_end < page_start:
            page_end = page_start
        node = {
            "topic_id": f"{chapter_key}::{h['number']}",
            "number": h["number"],
            "name": h["title"],
            "page_start": page_start,
            "page_end": page_end,
            "subtopics": [],
        }
        # subtopics = level-1 headings inside this topic's page span, in order
        subs = [
            s for s in headings
            if s["level"] == 1 and page_start <= s["page"] <= page_end
        ]
        subs.sort(key=lambda s: (s["page"], s["y0"]))
        for j, s in enumerate(subs):
            s_start = s["page"]
            s_end = (subs[j + 1]["page"] - 1) if j + 1 < len(subs) else page_end
            if s_end < s_start:
                s_end = s_start
            node["subtopics"].append({
                "subtopic_id": f"{chapter_key}::{s['number']}",
                "number": s["number"],
                "name": s["title"],
                "page_start": s_start,
                "page_end": s_end,
            })
        toc.append(node)
    return toc


class TocIndex:
    """page → (topic, subtopic) lookup for assigning content nodes by page range."""

    def __init__(self, toc: list[dict[str, Any]]):
        self._toc = toc or []

    def assign(self, page: int) -> dict[str, Any]:
        """Return {topic_id, topic, subtopic_id, subtopic} for a 1-indexed page.
        Fields are None when the page falls outside any detected section (e.g. intro)."""
        out = {"topic_id": None, "topic": None, "subtopic_id": None, "subtopic": None}
        for t in self._toc:
            if t["page_start"] <= page <= t["page_end"]:
                out["topic_id"], out["topic"] = t["topic_id"], t["name"]
                for s in t.get("subtopics", []):
                    if s["page_start"] <= page <= s["page_end"]:
                        out["subtopic_id"], out["subtopic"] = s["subtopic_id"], s["name"]
                        break
                break
        return out
