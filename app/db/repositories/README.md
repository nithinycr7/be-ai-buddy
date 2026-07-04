# Repository layer

Tenant-scoped data access between routers and Mongo. Introduced to stop routers
hand-writing collection queries (the source of the cross-tenant leak bug, where a
handler forgot `"tenant": tenant` in a filter).

## The rule
- **Routers never call `get_db()` or touch `db.<collection>` directly.** They
  depend on a repository via a `get_*_repo` provider and call its methods.
- Every repo is constructed bound to `(db, tenant)`; `BaseRepository._scoped()`
  forces the tenant filter onto **every** query and insert. Tenant isolation can't
  be forgotten per-query.
- **Ownership** (student/parent scoping) stays in the router via
  `assert_can_access_student(user, student_id)` — it needs the `CurrentUser`.
- Invalid `_id` input raises `InvalidObjectId`; the router maps it to HTTP 400.

## Layout
| Repo | Collection | Notes |
|------|-----------|-------|
| `DailyClassRepository` | `classes_daily` | |
| `QuizRepository` | `quizzes` | |
| `QuizResponseRepository` | `quiz_responses` | |
| `QuizAttemptRepository` | `student_quiz_attempts` | |
| `StudentProgressRepository` | `student_progress` | quiz-completion progress |
| `StudentDailyProgressRepository` | `student_daily_progress` | activity tracking |
| `InterventionRepository` | `student_interventions` | |
| `StudentRepository` | `students` | |
| `TranscriptRepository` | `transcripts` | **NOT** tenant-scoped (keyed by globally-unique `daily_id`) |

## Migrated so far (live, using repos)
`students.py`, `progress.py`, `intervention.py`, `daily_quiz.py`.

`daily_quiz.py` is the live quiz path — its migration is guarded by
`tests/test_daily_quiz_submit.py` (seed → submit → assert score/XP/streak +
tenant isolation; run with `MONGODB_DB=mymedha_repo_test python -m tests.test_daily_quiz_submit`).

## Deleted as dead (FE never called them; not mounted in main.py)
- `quiz.py` (`/api/quiz/*`) and `quizzes.py` (`/api/quizzes/*`) — duplicate of the
  live `/api/daily-quiz/*` path; were imported but never `include_router`'d.
- `question.py` (`/api/questions/*`) + its `services/question.py` + `models/question.py`
  — generic CRUD the FE never used.

## Not yet migrated (still call `get_db()` directly)
- `classes.py` — 16 data calls, intertwined with worker endpoints + LLM logic.
- `leaderboard.py`, `admin.py`, `ai.py` (god-router, separate track),
  `audio_upload.py` (worker), `auth.py`/`devices.py` (already use service layers).

## Debt status
1. ~~`calculate_completion` undefined~~ — **resolved**: only `quiz.py` referenced it; deleted.
2. ~~`daily_id` ObjectId-vs-str split~~ — **resolved**: the `str` consumer (`quiz.py`) is
   gone; only `daily_quiz.py`'s ObjectId form remains live.
3. **Duplicate `class QuizResponse`** in `models/schemas.py` (line ~73 and ~207) still
   present but now low-priority (its dead consumers are removed). Dedupe when convenient.

## Remaining FE-dead endpoints (candidates for the ai.py / engine pass)
- `POST /api/ai/story` — live story path is `/api/classes/story/generate` (this is the
  ~2000-line handler inside the 154KB `ai.py` god-router; remove during that pass).
- `GET /api/ai/rag/answer`, `GET /api/engine/cache-status` — no FE caller.
