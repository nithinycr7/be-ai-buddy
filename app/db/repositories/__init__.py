"""Repository layer — tenant-scoped data access between routers and Mongo.

Routers depend on a repository via the `get_*_repo` providers below instead of
calling `get_db()` and hand-writing collection queries. Each provider binds the
repo to the request's tenant (resolved from the token/header by `get_tenant`), so
tenant isolation is guaranteed at construction and cannot be forgotten per-query.

Usage in a router:

    from ..db.repositories import DailyClassRepository, get_daily_repo

    @router.get("/daily")
    async def list_daily(daily: DailyClassRepository = Depends(get_daily_repo), ...):
        return await daily.list_for_class(class_no=..., section=...)
"""
from __future__ import annotations

from fastapi import Depends

from ..mongo import get_db
from ...core.security import get_tenant
from .base import BaseRepository, InvalidObjectId
from .content import (
    ComicStoryRepository, GuruStoryRepository, SilfStoryRepository,
    StoryGenerationRepository, SummaryRepository,
)
from .curriculum import (
    CurriculumRepository, NcertContentRepository,
    NcertTextbookRepository, NcertFigureRepository,
)
from .daily import DailyClassRepository
from .engagement import QuizAnalyticsRepository, StreakRepository
from .intervention import InterventionRepository
from .leaderboard import LeaderboardRepository
from .progress import StudentDailyProgressRepository, StudentProgressRepository
from .quiz import QuizAttemptRepository, QuizRepository, QuizResponseRepository
from .simulation import SimulationRepository
from .student import StudentRepository
from .transcript import TranscriptRepository

__all__ = [
    "BaseRepository",
    "InvalidObjectId",
    "DailyClassRepository",
    "InterventionRepository",
    "StudentProgressRepository",
    "StudentDailyProgressRepository",
    "QuizRepository",
    "QuizResponseRepository",
    "QuizAttemptRepository",
    "StudentRepository",
    "TranscriptRepository",
    "StreakRepository",
    "QuizAnalyticsRepository",
    "SummaryRepository",
    "ComicStoryRepository",
    "StoryGenerationRepository",
    "GuruStoryRepository",
    "SilfStoryRepository",
    "CurriculumRepository",
    "NcertContentRepository",
    "LeaderboardRepository",
    "SimulationRepository",
    "NcertTextbookRepository",
    "NcertFigureRepository",
    # providers
    "get_daily_repo",
    "get_quiz_repo",
    "get_quiz_response_repo",
    "get_quiz_attempt_repo",
    "get_progress_repo",
    "get_daily_progress_repo",
    "get_intervention_repo",
    "get_student_repo",
    "get_transcript_repo",
    "get_streak_repo",
    "get_quiz_analytics_repo",
    "get_summary_repo",
    "get_comic_repo",
    "get_story_repo",
    "get_guru_story_repo",
    "get_silf_story_repo",
    "get_curriculum_repo",
    "get_ncert_content_repo",
    "get_leaderboard_repo",
    "get_simulation_repo",
    "get_ncert_textbook_repo",
    "get_ncert_figure_repo",
]


def _provider(repo_cls):
    """Build a FastAPI dependency that yields ``repo_cls`` bound to (db, tenant)."""
    async def _dep(tenant: str = Depends(get_tenant)):
        db = await get_db()
        return repo_cls(db, tenant)
    _dep.__name__ = f"get_{repo_cls.__name__}"
    return _dep


get_daily_repo = _provider(DailyClassRepository)
get_quiz_repo = _provider(QuizRepository)
get_quiz_response_repo = _provider(QuizResponseRepository)
get_quiz_attempt_repo = _provider(QuizAttemptRepository)
get_progress_repo = _provider(StudentProgressRepository)
get_daily_progress_repo = _provider(StudentDailyProgressRepository)
get_intervention_repo = _provider(InterventionRepository)
get_student_repo = _provider(StudentRepository)
get_transcript_repo = _provider(TranscriptRepository)
get_streak_repo = _provider(StreakRepository)
get_quiz_analytics_repo = _provider(QuizAnalyticsRepository)
get_summary_repo = _provider(SummaryRepository)
get_comic_repo = _provider(ComicStoryRepository)
get_story_repo = _provider(StoryGenerationRepository)
get_guru_story_repo = _provider(GuruStoryRepository)
get_silf_story_repo = _provider(SilfStoryRepository)
get_curriculum_repo = _provider(CurriculumRepository)
get_ncert_content_repo = _provider(NcertContentRepository)
get_leaderboard_repo = _provider(LeaderboardRepository)
get_simulation_repo = _provider(SimulationRepository)
get_ncert_textbook_repo = _provider(NcertTextbookRepository)
get_ncert_figure_repo = _provider(NcertFigureRepository)
