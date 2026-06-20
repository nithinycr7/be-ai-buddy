"""
NCERT "pagedex" — vectorless structured retrieval.

Self-contained, separable-in-backend module: extracts NCERT chapter PDFs into
typed content nodes (text / table / figure / exercise) tagged with the real
NCERT TOC section (topic/subtopic) + page + reading order, so retrieval is a
deterministic metadata filter — no embeddings, no model on the hot path.

Communicates only via shared Mongo + Azure Blob + Queue with stable ids, so it
can later be lifted verbatim into a `ncert-ingest` worker.
"""
