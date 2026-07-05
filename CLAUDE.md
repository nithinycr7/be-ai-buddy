# MyMedha LXP — Backend (FastAPI + Motor/MongoDB)

Multi-tenant K-12 learning platform. These are the **non-negotiable engineering
principles**. New code MUST follow them. Detailed references:
[`docs/BACKEND-ARCHITECTURE.md`](docs/BACKEND-ARCHITECTURE.md),
[`app/db/repositories/README.md`](app/db/repositories/README.md),
[`app/prompts/README.md`](app/prompts/README.md).

---

## 1. Layering (the non-negotiable) — `router → service → repository`

Dependencies flow **one direction only**. A repository never imports a service; a
service never imports a router; nothing skips a layer or calls "backwards".

### Router (`app/routers/<x>.py`) — HTTP only, zero logic
- Parse request → call **one** service method → return. That's it.
- Declarative auth via `Depends(require_role(...))` / `require_fresh_auth(...)` is fine.
- **Never** in a router: `get_db()` + a query, `db.<collection>`, `ObjectId`, business
  rules, or `raise HTTPException`. If you typed one of those, it belongs a layer down.
  (Exception: `auth`/`devices` inject `db` via `Depends(get_db)` only to hand to the
  functional `auth_service`/`device_service` — they never query in the router.)

### Service (`app/services/<x>_service.py`) — business rules only
- One service per feature. Holds rules: ownership, not-found, uniqueness, scoring,
  orchestration. Calls repositories.
- **Never** touches Motor and **never** imports FastAPI / raises `HTTPException`.
- On failure raises a **domain exception** (see §2).
- Constructed via a `get_<x>_service(repo = Depends(get_<x>_repo))` provider.
- Takes the acting `CurrentUser` as a method arg when it needs ownership checks.
- `db` is injected into a service **only** to hand to a legacy engine that still takes a
  raw client (AutoQuizGenerator, SummaryService, resolve_grounding, AutoQuizGenerator).

### Repository (`app/db/repositories/<x>.py`) — the ONLY layer touching collections
- Subclass `BaseRepository(db, tenant)`. Every query is **tenant-scoped automatically**
  via `_scoped()` — this is what structurally prevents cross-tenant data leaks.
- Convert `str → ObjectId` at the boundary (`find_by_id`, raising `InvalidObjectId`).
- Return plain dicts. The service/schema boundary turns `ObjectId → str` (see §4).
- Global (un-tenanted) content overrides `_scoped()` to a no-op and says why in a
  docstring (curriculum/ncert/transcripts/simulations).

---

## 2. Errors — domain exceptions + ONE handler
- Services/repositories raise `AppError` subclasses from `app/core/exceptions.py`:
  `NotFoundError` (404), `ConflictError` (409), `ForbiddenError` (403),
  `BadRequestError` (400). `InvalidObjectId` is an `AppError` (→ 400).
- **One** handler (`register_exception_handlers` in `main.py`) maps them to HTTP.
- No `try/except HTTPException` in routers; no status codes in services.

## 3. Tenant isolation + ownership
- Tenant scoping is enforced by the repo layer (never hand-write `{"tenant": tenant}`).
- Resource ownership (student/parent scoping) is a **service** concern:
  `assert_can_access_student(user, student_id)` (raises `ForbiddenError`).

## 4. ObjectId
- Schemas type `id` as `PyObjectId` (an `Annotated[str, BeforeValidator(str)]` in
  `app/models/schemas.py`) → models accept a raw `ObjectId` and emit a `str`.
- **Routes and handlers never see or hand-stringify an ObjectId.**

## 5. Prompts — all in `app/prompts/`, never inline
- `.py` modules for prompt strings / builder functions; `.txt` for the biggest system
  prompts (loaded via `read_text()`). A service imports its prompt; it never defines one.
- Small per-request user-message assembly (interpolating today's topic into a `messages`
  list) stays in the service — that's request shaping, not a reusable prompt.

## 6. LLD / program to interfaces — but never speculatively
- Use a `Protocol` (Strategy/Factory) **only where real, interchangeable implementations
  exist**. Justify each abstract type in a comment with the concrete variation it enables.
- Live examples: `app/services/llm/` (`LLMTextProvider` + Gemini/Anthropic/Azure +
  `generate_text()` fallback chain), `app/services/notifications/` (`OtpSender`/`EmailSender`
  Protocols + Dev/Null senders + `get_*_sender()` factory).
- Composition over inheritance; max inheritance depth 1 (base → concrete). If a class
  holds no state and enables no polymorphism, make it a module of functions.

## 7. Data-access hygiene
- **Pagination**: no unbounded `to_list(None)`. List queries take a `limit` (user-facing
  lists have skip/limit; bounded content reads cap via a constant, e.g. `MAX_CONTENT_DOCS`).
- **One Motor client**, created in the `lifespan` context manager in `main.py`
  (never per-request, never at import time). `close_client()` on shutdown.
- **Config** only via `pydantic-settings` (`app/core/config.py`). No hardcoded secrets or
  connection strings, ever. `assert_production_ready()` fails fast in prod.

## 8. Structure — shared layered repos, NOT feature folders
Repositories live in `app/db/repositories/` and are **shared** (the core entities — daily
class, student, progress, quiz — are touched by 5-6 features each). We deliberately did
**not** adopt `app/features/<x>/` because feature folders assume a feature owns its data,
which is false here. See the ADR in `docs/BACKEND-ARCHITECTURE.md`. Only colocate a
feature under `app/features/<x>/` if it grows genuinely feature-private data.

## 9. Testing
- Integration tests run against a throwaway DB via `MONGODB_DB=mymedha_repo_test`
  (`./venv/bin/python -m tests.<name>`). Drive the **service** directly, assert
  behavior + DB side-effects + **tenant isolation**.
- Pure logic (chains, factories, validators) gets fast unit tests (no DB/LLM).
- Existing: `test_daily_quiz_submit`, `test_content_service`, `test_content_repos`,
  `test_llm_and_notifications`.

## 10. Workers vs users
- Machine-to-machine worker endpoints carry `Depends(api_key_guard)` explicitly; they
  still go through services (repos for data; `db` injected only for legacy engines).

---

## Adding a new feature — the checklist
1. **Repository** (only if it needs new data access): subclass `BaseRepository`, add a
   `get_<x>_repo` provider in `app/db/repositories/__init__.py`. Reuse existing repos
   when the data is shared.
2. **Service** `app/services/<x>_service.py`: business rules, domain exceptions, a
   `get_<x>_service(...)` provider. No Motor, no FastAPI.
3. **Router** `app/routers/<x>.py`: thin — `require_role` gate, parse, call service, return.
   Register in `app/main.py`.
4. **Prompt** (if it calls an LLM): put it in `app/prompts/` and import it.
5. **Test**: a service-level integration test incl. a cross-tenant assertion.

**Reference vertical slice to copy:** `students` — [router](app/routers/students.py) →
[service](app/services/student_service.py) → [repository](app/db/repositories/student.py).
