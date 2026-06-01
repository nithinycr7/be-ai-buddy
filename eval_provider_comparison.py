"""
Eval-only (NOT committed): seed a Class 9 NCERT entry + a test daily_transcripts
doc from our earlier Sarvam/Gemini run, then run the provider-comparison pipeline
end-to-end and print a report. Run from the repo root:  python3 eval_provider_comparison.py
"""
import os
import re
import json
import asyncio

from dotenv import load_dotenv
load_dotenv()

CAPTURE = "/private/tmp/claude-501/-Users-hikmat-Desktop-MyMedha-mymedha-lxp-fe/5deae615-8641-4a0f-a39b-9c165fe18f7e/tasks/bbt9319c1.output"

TEST_TRANSCRIPT_ID = "evalschool_9_Science_1717200000"   # 2024-05-31
SUBJECT = "Science"

NCERT_DOC = {
    "_id": "ncert_9_science_thermodynamics",
    "class_no": "9",
    "subject": SUBJECT,
    "chapter": "Thermodynamics",
    "chapter_summary": (
        "Thermodynamics studies heat, work and the internal energy of a system. "
        "Internal energy is the sum of the kinetic and potential energies of all the "
        "molecules of a system; for an ideal gas it depends only on temperature."
    ),
    "topics": [
        {
            "name": "Internal Energy",
            "summary": (
                "Internal energy U is the total kinetic + potential energy of a system's "
                "molecules. For an ideal gas there are no intermolecular forces, so U is "
                "purely kinetic and depends only on temperature. Change in internal energy "
                "ΔU = nCvΔT and is a state function (path independent)."
            ),
            "activities": ["Relate temperature change to internal energy change",
                           "Compare ideal vs real gas internal energy"],
        }
    ],
}


def load_capture_transcripts():
    with open(CAPTURE, "r", encoding="utf-8") as f:
        raw = f.read()
    marker = "JSON (doc['transcripts'] shape):"
    idx = raw.index(marker)
    blob = raw[idx + len(marker):]
    start = blob.index("{")
    return json.loads(blob[start:])


async def main():
    from app.db.mongo import get_db
    from app.services.provider_comparison_service import generate_comparison

    db = await get_db()

    # 1. Seed NCERT (additive upsert)
    await db.ncert_textbooks.replace_one({"_id": NCERT_DOC["_id"]}, NCERT_DOC, upsert=True)
    print(f"✓ seeded ncert_textbooks: {NCERT_DOC['chapter']} / Internal Energy (class 9, {SUBJECT})")

    # 2. Seed a test daily_transcripts doc from the captured Sarvam+Gemini run
    tmap = load_capture_transcripts()              # {sarvam:{...}, gemini:{...}}
    # stand-in whisper entry (we validate real whisper in prod) so all 3 panels populate
    tmap["faster_whisper"] = {**tmap["gemini"], "model_name": "faster-whisper (local stand-in)"}
    primary_text = tmap["gemini"]["transcript_text"]
    tdoc = {
        "_id": TEST_TRANSCRIPT_ID,
        "schoolId": "evalschool", "classId": "9", "subject": SUBJECT,
        "timestamp": 1717200000,
        "transcript_text": primary_text,
        "language_detected": "te",
        "transcripts": tmap,
    }
    await db.daily_transcripts.replace_one({"_id": TEST_TRANSCRIPT_ID}, tdoc, upsert=True)
    print(f"✓ seeded daily_transcripts: {TEST_TRANSCRIPT_ID} (providers: {list(tmap)})")

    # 3. Run the comparison end-to-end
    print("\n⏳ generating 3 summaries + 3 stories (force=True)…\n")
    result = await generate_comparison(transcript_id=TEST_TRANSCRIPT_ID, grade=9, force=True)

    print("=" * 70)
    print(f"topic   : {result.get('topic')}")
    print(f"chapter : {result.get('chapter')}")
    ncert = result.get("ncert_used") or ""
    print(f"ncert   : {'MATCHED ✅' if ncert and 'No specific' not in ncert else 'no match'} "
          f"({len(ncert)} chars)")
    print("-" * 70)
    for name, e in result["providers"].items():
        if e.get("error"):
            print(f"{name:16} ERROR: {e['error']}")
            continue
        s = e.get("summary") or ""
        panels = (e.get("story") or {}).get("panels") or []
        t = e.get("transcription") or {}
        print(f"{name:16} summary={len(s):>4} chars | story_panels={len(panels)} | "
              f"latency={t.get('latency_s')}s | ~₹{(t.get('estimated_cost_usd') or 0)*96:.2f}")
    print("=" * 70)
    print("\nfull doc stored in collection 'provider_comparisons' (_id=%s)" % result["_id"])


if __name__ == "__main__":
    asyncio.run(main())
