# AI Buddy Backend (FastAPI + MongoDB)

Production-ready boilerplate tailored to:
- Student, Teacher, Parent, School entities
- Daily class records
- Quiz generation + responses
- Voice-to-Text (Azure Speech)
- Summaries, stories, and RAG answers (Azure OpenAI + MongoDB Atlas Vector Search)

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env  # fill keys
python run.py
```

OpenAPI docs: http://localhost:8000/docs

### Env Notes
- Configure `MONGODB_URI`, `MONGODB_DB`.
- For vector search, create an Atlas Search Index named `vector_index` on collection `cbse_docs` with `embedding` field.
- Set `AZURE_OPENAI_*` and `AZURE_SPEECH_*` for AI features.

### Security
- Simple API Key guard via `x-api-key` header. Rotate in prod and/or add JWT.

### Collections
- students, teachers, parents, schools
- classes_daily, transcripts, summaries, stories
- quizzes, quiz_responses
- cbse_docs (for RAG)
