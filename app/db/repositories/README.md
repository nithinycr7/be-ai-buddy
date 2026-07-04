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
`students.py`, `progress.py`, `intervention.py`, `daily_quiz.py`, and the
**content endpoints of `classes.py`** (comic / story / guru / silf).

Guarded by tests (run with `MONGODB_DB=mymedha_repo_test python -m tests.<name>`):
- `tests/test_daily_quiz_submit.py` — daily-quiz submit: score/XP/streak + tenant isolation.
- `tests/test_content_repos.py` — story/guru/silf/comic repos: **closes the write-gap**
  (writes used to omit tenant in the replace_one filter → two tenants sharing a
  (daily_id, student_id) could overwrite each other) + silf per-format cache + curriculum global.

### classes.py is partially migrated — by design
It's a service-orchestration router: many endpoints hand a raw `db` to content
services (`resolve_grounding`, `generate_mindmap`, `SummaryService`, `_eager_generate_quiz`,
`insert_daily_transcript`). So `classes.py` keeps `from ..db.mongo import get_db` for
those handoffs + the global NCERT reads. What moved to repos: the **content
generation/caching endpoints** (the ones with the real tenant write-gap). What stayed
on `db`: the daily-CRUD / summarize / mindmap / transcript / widget endpoints — audited
tenant-correct already (they update by `_id` fetched under a tenant filter, or include
tenant in the filter). Global NCERT collections use the non-scoped
`CurriculumRepository` / `NcertContentRepository`.

## Deleted as dead (FE never called them; not mounted in main.py)
- `quiz.py` (`/api/quiz/*`) and `quizzes.py` (`/api/quizzes/*`) — duplicate of the
  live `/api/daily-quiz/*` path; were imported but never `include_router`'d.
- `question.py` (`/api/questions/*`) + its `services/question.py` + `models/question.py`
  — generic CRUD the FE never used.

## Not yet migrated (still call `get_db()` directly)
- `classes.py` daily-CRUD/summarize/mindmap/transcript/widget endpoints (service-coupled;
  already tenant-correct — see note above).
- `leaderboard.py`, `admin.py`, `ai.py` (god-router, separate track),
  `audio_upload.py` (worker), `auth.py`/`devices.py` (already use service layers).

## Debt status
1. ~~`calculate_completion` undefined~~ — **resolved**: only `quiz.py` referenced it; deleted.
2. ~~`daily_id` ObjectId-vs-str split~~ — **resolved**: the `str` consumer (`quiz.py`) is
   gone; only `daily_quiz.py`'s ObjectId form remains live.
3. ~~Duplicate `class QuizResponse`~~ — **resolved**: both defs were dead (only the
   deleted quiz routers used them); removed from `models/schemas.py`.
4. ~~`create_daily` inserted a `datetime.date` (not bson-encodable)~~ — **resolved**:
   `create_daily` now uses `model_dump(mode="json")`, storing `date` as an ISO string.

## Remaining FE-dead endpoints (candidates for the ai.py / engine pass)
- `POST /api/ai/story` — live story path is `/api/classes/story/generate` (this is the
  ~2000-line handler inside the 154KB `ai.py` god-router; remove during that pass).
- `GET /api/ai/rag/answer`, `GET /api/engine/cache-status` — no FE caller.
