from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.config import settings
from .db.mongo import init_indexes
from .routers import students, classes, quizzes, ai, admin, question,quiz

app = FastAPI(title=settings.PROJECT_NAME, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(students.router, prefix=settings.API_PREFIX)
app.include_router(classes.router, prefix=settings.API_PREFIX)
app.include_router(quizzes.router, prefix=settings.API_PREFIX)
app.include_router(ai.router, prefix=settings.API_PREFIX)
app.include_router(admin.router, prefix=settings.API_PREFIX)
app.include_router(question.router, prefix=settings.API_PREFIX)
app.include_router(quiz.router, prefix=settings.API_PREFIX)

@app.on_event("startup")
async def on_startup():
    await init_indexes()

@app.get("/healthz")
async def health():
    return {"status":"ok"}

"""
routers (REST, ready for your React UI):

POST /api/students / GET /api/students/{student_id}

POST /api/classes/daily → create daily lesson (date, class, section, subject, topics, summary)

POST /api/classes/daily/{daily_id}/transcribe → upload audio (Azure Speech)

POST /api/classes/daily/{daily_id}/summarize → combine summary+transcript → bullets (Azure OpenAI)

POST /api/quizzes/from-daily/{daily_id} → auto-generate 5 MCQs from the day’s content

POST /api/quizzes/{quiz_id}/responses?student_id=... → submit answers, auto-grade, score stored

GET /api/ai/rag/answer?query=...&class_no=8&subject=Maths → CBSE RAG answer

POST /api/ai/story (body: daily_id, student_id) → persona-based short story

GET /api/admin/teacher-performance?teacher_email=... → stub metrics
"""

@app.get("/debug/config")
def dbg():
    def mask(s): 
        return s[:12] + "…" if s else None
    return {
        "api_prefix": settings.API_PREFIX,
        "blob_conn_str_set": bool(settings.AZURE_BLOB_CONN_STR),
        "blob_conn_str_preview": mask(settings.AZURE_BLOB_CONN_STR),
    }