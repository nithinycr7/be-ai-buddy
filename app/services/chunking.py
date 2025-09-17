# run this as a one-off script in your repo
# pip install pymupdf  (if not installed)

import re, fitz, asyncio
from app.services.rag import upsert_cbse_doc  # uses cosmosSearch + Azure/OpenAI
PDF_PATH   = "app/services/gecu107-chapter7heat.pdf"  # if PDF is in app/services
SUBJECT    = "Physics"
CLASS_NO   = 7
CHAPTER    = "Heat"

MAX_CHARS  = 2000   # ~800–1200 tokens depending on text
OVERLAP    = 180    # ~150–200 tokens overlap

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def chunk_text(text: str, max_chars=MAX_CHARS, overlap=OVERLAP):
    # simple sentence-ish splitter
    sents = re.split(r'(?<=[.!?])\s+', text)
    chunks, cur, cur_len = [], [], 0
    for s in sents:
        s = s.strip()
        if not s:
            continue
        if cur_len + len(s) + 1 > max_chars:
            if cur:
                chunk = " ".join(cur).strip()
                if len(chunk) > 40:
                    chunks.append(chunk)
            # start new with overlap tail
            if chunks and overlap > 0:
                tail = chunks[-1][-overlap:]
                cur, cur_len = [tail, s], len(tail) + 1 + len(s)
            else:
                cur, cur_len = [s], len(s)
        else:
            cur.append(s); cur_len += len(s) + 1
    if cur:
        chunk = " ".join(cur).strip()
        if len(chunk) > 40:
            chunks.append(chunk)
    return chunks

def extract_pages(pdf_path: str, start=1, end=None):
    doc = fitz.open(pdf_path)
    if end is None: end = doc.page_count
    for pno in range(start-1, end):
        text = doc[pno].get_text("text")
        yield pno+1, normalize(text)

async def ingest_pdf(pdf_path: str, subject: str, class_no: int, chapter: str, start=1, end=None):
    inserted = 0
    for page_no, page_text in extract_pages(pdf_path, start, end):
        for ch in chunk_text(page_text):
            _id = await upsert_cbse_doc(
                chapter=chapter,
                subject=subject,
                class_no=class_no,
                text=ch,
                source_pdf=pdf_path,
                page=page_no
            )
            inserted += 1
    print(f"Ingested {inserted} chunks.")

if __name__ == "__main__":
    asyncio.run(ingest_pdf(PDF_PATH, SUBJECT, CLASS_NO, CHAPTER, start=1, end=16))
