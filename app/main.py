import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.config import settings
from .core.exceptions import register_exception_handlers
from .db.mongo import init_indexes
from .routers import students, classes, ai, admin, chat, progress, daily_quiz, leaderboard, audio_upload, ncert, intervention, auth, devices
from .routers.teacher import lesson_plan, quiz as teacher_quiz, insights as teacher_insights, interventions as teacher_interventions

from .db.sqlite_db import init_learning_db
from .routers.learning_engine import router as learning_engine_router
from .routers.engine import router as engine_router

# Configure logging to show in console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

app = FastAPI(title=settings.PROJECT_NAME, version="1.0.0")

# CORS — locked to known origins. Auth uses bearer tokens (not cookies), so we
# don't need credentialed CORS. In dev we allow any localhost port + the
# Capacitor app scheme; in prod only the configured origins.
_cors_origins = [o.rstrip("/") for o in settings.CORS_ORIGINS] + ["capacitor://localhost"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=None if settings.is_production() else r"^(http://localhost(:\d+)?|capacitor://localhost)$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Domain exceptions -> HTTP, in one place (keeps routers/services framework-agnostic)
register_exception_handlers(app)

# Routers
app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(devices.router, prefix=settings.API_PREFIX)
app.include_router(students.router, prefix=settings.API_PREFIX)
app.include_router(classes.router, prefix=settings.API_PREFIX)
app.include_router(ai.router, prefix=settings.API_PREFIX)
app.include_router(admin.router, prefix=settings.API_PREFIX)
app.include_router(chat.router, prefix=settings.API_PREFIX)
app.include_router(progress.router, prefix=settings.API_PREFIX)
app.include_router(lesson_plan.router, prefix=settings.API_PREFIX)
app.include_router(daily_quiz.router, prefix=settings.API_PREFIX)
app.include_router(leaderboard.router, prefix=settings.API_PREFIX)
app.include_router(audio_upload.router, prefix=settings.API_PREFIX)
app.include_router(ncert.router, prefix=settings.API_PREFIX)
app.include_router(teacher_quiz.router, prefix=f"{settings.API_PREFIX}/teacher/quiz", tags=["Teacher Quiz"])
app.include_router(teacher_insights.router, prefix=f"{settings.API_PREFIX}/teacher/insights", tags=["Teacher Insights"])
app.include_router(intervention.router, prefix=settings.API_PREFIX)
app.include_router(teacher_interventions.router, prefix=f"{settings.API_PREFIX}/teacher/interventions", tags=["Teacher Interventions"])
app.include_router(learning_engine_router, prefix=settings.API_PREFIX)
app.include_router(engine_router, prefix=settings.API_PREFIX)

@app.on_event("startup")
async def on_startup():
    settings.assert_production_ready()  # fail fast in prod on missing secrets/placeholders
    await init_indexes()
    init_learning_db()

@app.get("/")
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


