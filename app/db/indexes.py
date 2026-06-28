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

    # Curriculum Chapters
    await db.curriculum_chapters.create_index("chapter_key", unique=True, name="ux_curriculum_chapter_key")
    await db.curriculum_chapters.create_index([("board", 1), ("class", 1)], name="ix_curriculum_board_class")
    await db.curriculum_chapters.create_index([("board", 1), ("class", 1), ("subject", 1), ("chapter_number", 1)], name="ix_curriculum_lookup")

    # NCERT ingested figures + chapter text (exam-centric SILF story pipeline)
    await db.ncert_figures.create_index("chapter_key", name="ix_ncert_figures_chapter")
    await db.ncert_chapter_text.create_index([("chapter_key", 1), ("page", 1)], name="ix_ncert_text_chapter_page")

    # NCERT pagedex content nodes (vectorless structured retrieval)
    await db.ncert_nodes.create_index([("chapter_key", 1), ("order", 1)], name="ix_ncert_nodes_chapter_order")
    await db.ncert_nodes.create_index([("chapter_key", 1), ("topic_id", 1), ("subtopic_id", 1), ("type", 1)], name="ix_ncert_nodes_section")
    await db.ncert_nodes.create_index([("class", 1), ("subject", 1), ("chapter_number", 1)], name="ix_ncert_nodes_lookup")

    # SILF story cache
    await db.silf_story_generations.create_index([("daily_id", 1), ("student_id", 1)], name="ix_silf_story_daily_student")

    # Capture metadata — canonical chapter/topic ids stashed at audio-upload time
    await db.capture_meta.create_index([("tenant", 1), ("class_no", 1), ("section", 1), ("subject", 1)], name="ux_capture_meta_class", unique=True)

    # --- Auth / identity (SPEC §4) -------------------------------------------
    # users — one collection, all roles. Identifiers are sparse (students may
    # have none of email/phone), so uniqueness is partial on field presence.
    await db.users.create_index(
        [("tenant", 1), ("email", 1)], unique=True, name="ux_users_tenant_email",
        partialFilterExpression={"email": {"$type": "string"}},
    )
    await db.users.create_index(
        [("tenant", 1), ("phone", 1)], unique=True, name="ux_users_tenant_phone",
        partialFilterExpression={"phone": {"$type": "string"}},
    )
    await db.users.create_index(
        [("tenant", 1), ("student_code", 1)], unique=True, name="ux_users_tenant_student_code",
        partialFilterExpression={"student_code": {"$type": "string"}},
    )
    await db.users.create_index(
        [("tenant", 1), ("student_id", 1)], unique=True, name="ux_users_tenant_student_id",
        partialFilterExpression={"student_id": {"$type": "string"}},
    )
    await db.users.create_index([("tenant", 1), ("role", 1)], name="ix_users_tenant_role")

    # tenants (schools)
    await db.tenants.create_index("tenant", unique=True, name="ux_tenants_tenant")
    await db.tenants.create_index("school_code", unique=True, name="ux_tenants_school_code")

    # parent_links (parent ↔ student)
    await db.parent_links.create_index(
        [("tenant", 1), ("parent_id", 1), ("student_id", 1)], unique=True, name="ux_parent_link",
    )
    await db.parent_links.create_index([("tenant", 1), ("parent_id", 1)], name="ix_parent_link_parent")
    await db.parent_links.create_index([("tenant", 1), ("student_id", 1)], name="ix_parent_link_student")

    # sessions (refresh tokens — rotation + revocation)
    await db.sessions.create_index("refresh_token_hash", unique=True, name="ux_session_refresh_hash")
    await db.sessions.create_index([("tenant", 1), ("user_id", 1)], name="ix_session_user")

    # otp_codes — TTL auto-cleans expired codes
    await db.otp_codes.create_index([("tenant", 1), ("phone", 1), ("created_at", -1)], name="ix_otp_lookup")
    await db.otp_codes.create_index("expires_at", expireAfterSeconds=0, name="ttl_otp_expiry")

    # audit_log
    await db.audit_log.create_index([("tenant", 1), ("at", -1)], name="ix_audit_tenant_at")

    # devices — trusted learning devices paired to a family (parent account)
    await db.devices.create_index([("tenant", 1), ("device_id", 1)], unique=True, name="ux_device_id")
    await db.devices.create_index([("tenant", 1), ("parent_id", 1)], name="ix_device_parent")

    # pairing_grants — one-time device-pairing grant (QR + numeric code), TTL'd
    await db.pairing_grants.create_index("code", name="ix_pairing_code")
    await db.pairing_grants.create_index("qr_token_hash", name="ix_pairing_qr")
    await db.pairing_grants.create_index("expires_at", expireAfterSeconds=0, name="ttl_pairing_expiry")

    # invites — parent invitation links (roster import → SMS claim)
    await db.invites.create_index("token_hash", unique=True, name="ux_invite_token")
    await db.invites.create_index([("tenant", 1), ("student_id", 1)], name="ix_invite_student")
    await db.invites.create_index([("tenant", 1), ("parent_phone", 1)], name="ix_invite_phone")
