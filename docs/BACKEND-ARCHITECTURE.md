# Backend architecture — the non-negotiable layering

**Every feature flows in ONE direction:**

```
router  →  service  →  repository  →  (Motor / MongoDB)
 HTTP        rules       queries
```

Dependencies point downward only. A repository never imports a service; a service
never imports a router; nothing calls "backwards" or skips a layer.

## Layer contracts

### Router (`app/routers/<x>.py`) — HTTP only, zero logic
- Parse the request, call one service method, return the result.
- Declarative auth via `Depends(require_role(...))` is allowed (it's HTTP-layer).
- **Never**: `get_db()`, `db.<collection>`, `ObjectId`, business rules, or
  `raise HTTPException`. If you typed any of those in a router, it's in the wrong layer.

### Service (`app/services/<x>_service.py`) — business rules only
- Holds the rules: uniqueness, ownership, not-found, orchestration, scoring, etc.
- Calls repositories; **never touches Motor** and **never imports FastAPI/HTTPException**.
- On failure raises a **domain exception** from `app/core/exceptions.py`
  (`NotFoundError`, `ConflictError`, `ForbiddenError`, `BadRequestError`).
- Injected via a `get_<x>_service(repo = Depends(get_<x>_repo))` provider.
- May take the acting `CurrentUser` as a method arg for ownership checks.

### Repository (`app/db/repositories/<x>.py`) — the ONLY layer touching collections
- Subclasses `BaseRepository(db, tenant)`; every query is tenant-scoped automatically.
- Converts `str → ObjectId` at its boundary (`find_by_id`, raising `InvalidObjectId`).
- Returns plain dicts. The service/schema boundary converts `ObjectId → str`
  (routes never see an ObjectId).

## Errors
Services/repositories raise `AppError` subclasses. **One** global handler
(`register_exception_handlers` in `main.py`) maps them to HTTP. No `try/except
HTTPException` in routers, no status codes in services.

## Reference implementation
`students` is the canonical vertical slice — copy its shape:
- [routers/students.py](../app/routers/students.py) — thin
- [services/student_service.py](../app/services/student_service.py) — rules + domain exceptions
- [db/repositories/student.py](../app/db/repositories/student.py) — Motor only

## Status (migrating existing code to this shape)
- ✅ Full 3-layer: `students`, `progress`, `intervention`, `daily_quiz`, `leaderboard`,
  `admin`, and **all of `classes`** (content → `ContentService`; daily-CRUD / summarize /
  mindmap / transcript / widget / compare → `DailyClassService`).
  Services: `student_service`, `progress_service`, `intervention_service`,
  `daily_quiz_service`, `content_service`, `daily_class_service`, `leaderboard_service`,
  `admin_service`. Tests: `test_daily_quiz_submit`, `test_content_service`, `test_content_repos`.
- ✅ `ai` — dead `/story` + `/rag-answer` removed; `/tts` + `/simulation` → `AiService`
  (`SimulationRepository`); prompt templates in the pure `services/simulation_prompts.py`.
  ai.py went 2970 → ~40 lines (thin router).
- ✅ `ncert` → `NcertService` (global repos), `chat` → `ChatService` (no data layer),
  and all `teacher/*` (`quiz`/`insights`/`interventions` → services; `lesson_plan` via a
  DI provider). Services under `app/services/teacher/`.
- ✅ `engine` → `EngineService`, `learning_engine` → `LearningEngineService`
  (+ a SQLite `repository.py` — the engine uses SQLite, not Mongo),
  `audio_upload` → `AudioIngestService`, `auth`/`devices` thinned (delegate to the
  functional `auth_service`/`device_service`; db injected via `Depends(get_db)`).

**Every router is now thin**: no router calls `get_db()` imperatively, runs a query,
or raises `HTTPException`. Two honest caveats:
1. `auth`/`devices` still *receive* a `db` handle (injected) to pass to their functional
   services, which themselves still raise `HTTPException` (FastAPI's built-in handler
   covers it). Fully hiding db + converting those services to domain errors is a larger,
   security-sensitive follow-up.
2. The FastAPI `HTTPException` handler stays registered alongside our `AppError` handler,
   so legacy service-raised `HTTPException`s keep working during the transition.
- Worker endpoints (`api_key_guard`, no user token) go through the same services;
  the service uses repositories, `db` is injected only to hand to legacy engines
  (AutoQuizGenerator, SummaryService, resolve_grounding, insert_daily_transcript).

New features MUST start at the reference shape — do not add a router that talks to a
repository (or a db) directly.
