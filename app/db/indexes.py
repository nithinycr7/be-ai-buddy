from motor.motor_asyncio import AsyncIOMotorDatabase

async def ensure(db: AsyncIOMotorDatabase):
    # Students
    await db.students.create_index("student_id", unique=True, name="ux_student_id")
    await db.students.create_index([("class_no", 1), ("section", 1)], name="ix_students_class_section")

    # Teachers
    await db.teachers.create_index("email", unique=True, name="ux_teacher_email")

    # Parents
    await db.parents.create_index("email", unique=True, name="ux_parent_email")
    await db.parents.create_index("student_id", name="ix_parent_student")

    # Schools
   # await db.schools.create_index([("tenant", 1), ("branch", 1)], unique=True, name="ux_school_tenant_branch")

    # Daily Classes
    await db.classes_daily.create_index([("date", -1), ("class_no", 1), ("section", 1), ("subject", 1)], name="ix_daily_composite")

    # Quizzes
    await db.quizzes.create_index("daily_id", name="ix_quiz_daily")
    await db.quizzes.create_index("class_no", name="ix_quiz_class")
    await db.quiz_responses.create_index([("quiz_id", 1), ("student_id", 1)], unique=True, name="ux_quiz_student")

    # Transcripts & Summaries
    await db.transcripts.create_index("daily_id", name="ix_transcript_daily")
    await db.summaries.create_index("daily_id", name="ix_summary_daily")
    await db.stories.create_index("daily_id", name="ix_story_daily")

    # CBSE RAG docs
    # NOTE: For MongoDB Atlas Vector Search, create a Search Index in Atlas UI named "vector_index" on cbse_docs.embedding
    await db.cbse_docs.create_index("chapter", name="ix_docs_chapter")
