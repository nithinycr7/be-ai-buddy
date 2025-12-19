# Multi-School Support - Implementation Notes

## Overview
The Daily Quiz system has been designed with multi-school (multi-tenancy) support from the ground up.

## Key Points

### 1. School ID (Tenant) Tracking

Every quiz and related data is tagged with a `tenant` field (school_id):

- **Quiz Model**: `tenant` field identifies which school the quiz belongs to
- **Student Attempts**: `tenant` field ensures attempts are scoped to the correct school
- **Streak Tracking**: `tenant` field keeps XP/streaks separate per school
- **Analytics**: `tenant` field allows per-school analytics

### 2. Transcript Fetching (TODO)

When connecting to `mymedha_db` to fetch transcripts, **MUST** filter by:

```python
{
    "school_id": tenant,  # REQUIRED - prevents cross-school data leakage
    "class_no": class_no,
    "section": section,
    "subject": subject,
    "chapter": chapter,   # optional
    "topic": topic        # optional
}
```

### 3. Helper Function

Use the provided `fetch_transcript_from_mymedha_db()` function:

```python
from app.services.auto_quiz_generator import fetch_transcript_from_mymedha_db

# Once mymedha_db connection is set up
transcript = await fetch_transcript_from_mymedha_db(
    mymedha_db=mymedha_db,
    school_id=tenant,      # From X-Tenant-ID header
    class_no=7,
    section="A",
    subject="Science",
    chapter="Photosynthesis"  # optional
)
```

### 4. API Security

All API endpoints use the `get_tenant()` dependency:

```python
@router.post("/generate")
async def generate_quiz(tenant: str = Depends(get_tenant)):
    # tenant is automatically extracted from X-Tenant-ID header
    # All queries automatically scoped to this tenant
```

This ensures:
- No cross-school data access
- Automatic tenant filtering
- Secure multi-tenancy

### 5. Database Queries

All database queries include tenant filter:

```python
# Finding quiz
quiz = await db.quizzes.find_one({
    "daily_id": daily_id,
    "tenant": tenant  # Always include tenant
})

# Finding student attempts
attempts = await db.student_quiz_attempts.find({
    "student_id": student_id,
    "tenant": tenant  # Always include tenant
})
```

## Migration Checklist

When adding `mymedha_db` connection:

- [ ] Add connection string to `.env`
- [ ] Create `get_mymedha_db()` function in `app/db/mongo.py`
- [ ] Update `auto_quiz_generator.py` to use `fetch_transcript_from_mymedha_db()`
- [ ] Verify transcript schema in `mymedha_db` includes `school_id` field
- [ ] Test with multiple schools to ensure data isolation
- [ ] Add error handling for missing transcripts per school

## Security Notes

⚠️ **CRITICAL**: Always include `school_id`/`tenant` in queries to prevent:
- Cross-school data leakage
- Unauthorized access to other schools' data
- Data privacy violations

✅ **GOOD**:
```python
quiz = await db.quizzes.find_one({"daily_id": id, "tenant": tenant})
```

❌ **BAD** (security vulnerability):
```python
quiz = await db.quizzes.find_one({"daily_id": id})  # Missing tenant filter!
```
