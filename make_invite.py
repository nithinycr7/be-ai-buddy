"""Generate fresh parent-invite links for students (manual testing).

The invite token is stored HASHED, so an existing link can't be read back — this
mints a new invite per student and prints the full link. Idempotent-ish: each run
creates a new valid invite (old ones for the same student still work until claimed).

Usage:
    python make_invite.py                 # all students in the tenant
    python make_invite.py DAVH-9A-7EB7    # just one, by student_code
"""
import asyncio
import os
import sys

import certifi
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.services import invite_service

TENANT = os.getenv("SEED_TENANT", "dav-hyderabad")
BASE_URL = os.getenv("SEED_BASE_URL", "http://localhost:5173")


async def main():
    code_filter = sys.argv[1].strip().upper() if len(sys.argv) > 1 else None
    c = AsyncIOMotorClient(settings.MONGODB_URI, tls=True, tlsCAFile=certifi.where())
    db = c[settings.MONGODB_DB]
    print(f"DB: {settings.MONGODB_DB}  tenant: {TENANT}\n")

    q = {"tenant": TENANT, "role": "student"}
    if code_filter:
        q["student_code"] = code_filter

    n = 0
    async for s in db.users.find(q):
        # Parent contact lives on the original invite, not the student doc.
        prev = await db.invites.find_one({"tenant": TENANT, "student_id": s["student_id"]})
        p_email = (prev or {}).get("parent_email") or s.get("parent_email")
        p_phone = (prev or {}).get("parent_phone") or s.get("parent_phone")
        if not p_email and not p_phone:
            print(f"{s.get('name'):18} {s.get('student_code'):16} → (skip: no parent contact on file)")
            continue
        inv = await invite_service.create_invite(
            db, tenant=TENANT, student_id=s["student_id"],
            parent_email=p_email, parent_phone=p_phone,
            parent_name=None, created_by="make_invite",
        )
        link = f"{BASE_URL.rstrip('/')}/auth/invite/{inv['token']}"
        print(f"{s.get('name'):18} {s.get('student_code'):16} → {link}")
        n += 1

    if not n:
        print("No students matched.")
    c.close()


if __name__ == "__main__":
    asyncio.run(main())
