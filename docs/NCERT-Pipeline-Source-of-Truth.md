# NCERT as the Source of Truth — Pipeline Overview

*A short, shareable explainer of what we built and why. For deeper engineering
decisions see [ADR-pagedex-and-pilot.md](./ADR-pagedex-and-pilot.md).*

---

## TL;DR

We turned NCERT textbooks into the platform's **single source of truth** for content.

- Every chapter PDF is parsed once into **structured, addressable pieces** — text,
  tables, and figures — each tagged with its exact **chapter → topic → subtopic** and
  page.
- When a teacher teaches a topic, the system pulls back **only the NCERT content for
  that exact section** and uses it to ground the summary, mind map, quiz and story.
- This is **deterministic and auditable** — we can point to "NCERT page 84, Figure
  5.11" behind any generated answer. No vector search, no guessing.

We call this structured index the **"Pagedex."**

---

## Why a source of truth at all?

The product promise is: *"We don't replace the teacher. We reinforce what the teacher
taught — grounded in the textbook."*

For that to be trustworthy, every AI-generated artifact (summary, mind map, quiz,
story) must be **anchored to the official NCERT text** — not to whatever the LLM
happens to remember. So we need NCERT stored in a form the system can retrieve from
**precisely and provably**.

A flat "dump the whole chapter into the prompt" approach (what we had before) is
neither precise (it can't focus on the taught subtopic) nor provable (you can't cite
the exact source). The Pagedex fixes both.

---

## The big idea: structure, don't embed

NCERT is **small and highly structured** — about 600 chapters total across classes
3–12, each with a numbered table of contents (5.1, 5.2, 5.3.1 …). The retrieval need
is simply: *"give me the content for this chapter/topic the teacher taught."*

That is a **lookup**, not a fuzzy search. So we deliberately chose **NOT to use
embeddings / vector RAG**:

| | Vector RAG | Our Pagedex |
|---|---|---|
| Retrieval | similarity search (approximate) | exact metadata filter (deterministic) |
| Can cite the exact page/figure? | no | **yes** |
| Cost / infra | embeddings + vector index | none — plain Mongo filter |
| Right tool when… | huge, unstructured corpus | small, TOC-structured corpus ✅ |

The NCERT TOC already gives us the structure for free. We just make it machine-usable.

---

## The pipeline (ingestion → source of truth)

```
NCERT chapter PDF
      │
      │  ① EXTRACT  (PyMuPDF)
      ▼
text per page · tables · figure images
      │
      │  ② STRUCTURE  (detect numbered headings → real TOC + page ranges)
      ▼
Topic/Subtopic tree:  5.1, 5.2 → 5.2.1/5.2.2, 5.3 → 5.3.1 …  with page ranges
      │
      │  ③ ASSIGN  (each piece → the section whose page range contains it)
      ▼
ncert_nodes  — typed, section-tagged content
   { type: text|table|figure, topic_id, subtopic_id, page, order, … }
      │
      │  ④ STORE
      ▼
• ncert_nodes            (the addressable content — the source of truth)
• curriculum_chapters.toc (the topic/subtopic map the teacher selects from)
• figure images → Azure Blob (not bloating the DB)
```

**Everything here is deterministic — no LLM.** The section headings are numbered and
bold, so the hierarchy is read straight from the PDF; each block is filed under a
section by simple page-range math. That means ingestion can't hallucinate structure,
and re-running it is safe (idempotent, stable IDs).

Run it with:
```
python -m app.scripts.ingest_ncert \
    --pdf data/ncert_pdfs/iesc105.pdf \
    --chapter-key science_class9_ch05 --class-no 9 --subject Science
```

---

## How it acts as the source of truth (retrieval)

The teacher selects a chapter + topic when they record — and those choices are the
**same canonical IDs** the Pagedex is keyed on (e.g. `science_class9_ch05::5.3`). So
retrieval is an **exact match**, with no model involved:

```
Teacher taught  →  chapter_key + topic_id
                          │
                          ▼
   ncert_nodes.find({ chapter_key, topic_id })   ← deterministic filter
                          │
                          ▼
   exactly that section's  text + tables + figures (signed image URLs)
                          │
                          ▼
   feeds Summary · Mind Map · Quiz · Story generation
```

So when the teacher teaches **Filtration**, the summary is grounded in NCERT's
filtration text and its real diagrams — not the whole chapter, and not the model's
memory. If a topic isn't tagged precisely, the system **safely falls back** to the
whole chapter (never the wrong section).

`resolve_grounding(...)` returns the scoped content plus a `scope` flag
(`section` / `chapter` / `concepts`) so we always know how precisely an answer was
grounded.

---

## Worked example — "Separation of Mixtures" (Class 9 Science)

Ingesting the chapter PDF auto-produced this real TOC and content:

```
science_class9_ch05
├─ 5.1 How Can We Classify Mixtures?
├─ 5.2 Solutions
│    ├─ 5.2.1 Concentration of a solution
│    ├─ 5.2.2 How do we express concentration?
│    └─ 5.2.3 Solubility of substances
├─ 5.3 Methods of Separation of Homogeneous Mixtures
│    ├─ 5.3.1 Crystallization
│    ├─ 5.3.2 Distillation          ← Figs 5.11–5.14
│    └─ 5.3.3 Paper Chromatography
├─ 5.4 How Can We Separate (Heterogeneous) …
└─ 5.5 Tyndall Effect
```

→ 53 content nodes (22 text, 6 tables, 25 figures), figures stored in Azure Blob.

Asking for the **Distillation** subtopic (`…::5.3.2`) returns **only** the
distillation text + its 4 figures — exactly the slice the teacher taught.

---

## What this unlocks

- **Trustworthy AI** — every summary/quiz/story is backed by the actual textbook,
  and we can show the source ("verified against NCERT, p.84, Fig 5.11"). This is the
  trust badge the student UI already promises.
- **Sharper content** — generation focuses on the taught subtopic instead of a whole
  chapter dump, so summaries and quizzes are tighter and more relevant.
- **Real textbook diagrams** — stories/explanations can show the exact figure a
  student will see on their exam paper, never an AI-invented image.
- **Cheap and scalable** — ~15k nodes total is trivial for Mongo; no vector infra,
  no per-query model cost for retrieval.
- **Auditable & reproducible** — deterministic ingestion + exact-match retrieval means
  the same input always gives the same, explainable output.

---

## Status & what's next

**Done & verified** (end-to-end on the Separation-of-Mixtures chapter):
- Ingestion pipeline (PDF → TOC → nodes), figures in Azure Blob, deterministic
  section-scoped retrieval, and summary generation grounded in the taught section.

**Next:**
- **Bulk-ingest** the NCERT chapters for the pilot classes (the pipeline is ready;
  this is mainly sourcing the PDFs).
- **Migrate** legacy figures out of Mongo into Blob.
- Point **story (SILF)** generation at the same scoped retrieval (summary already uses it).

---

## One-paragraph version (for a Slack message)

> We made NCERT the source of truth. Each chapter PDF is parsed once into structured,
> page-tagged pieces (text/tables/figures) filed under the real TOC sections —
> deterministically, no AI guesswork. When a teacher teaches a topic, we fetch exactly
> that section's NCERT content (and real figures) and use it to ground the summary,
> mind map, quiz and story. It's precise, citable ("NCERT p.84, Fig 5.11"), cheap
> (plain DB filter, no vector search), and reproducible. Proven end-to-end on Class 9
> "Separation of Mixtures"; next is bulk-ingesting the pilot chapters.
