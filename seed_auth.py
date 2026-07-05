"""Seed a school tenant + a staff (admin) login for manual testing.

Targets whatever DB `MONGODB_DB` points at (see .env). Idempotent — re-running
just upserts. After this you can log in at /admin/roster and import a roster.

Usage:
    python seed_auth.py

Override defaults via env:
    SEED_SCHOOL_CODE=DAV-HYD SEED_TENANT=dav-hyderabad \
    SEED_ADMIN_EMAIL=admin@dav.edu SEED_ADMIN_PASSWORD=demo1234 python seed_auth.py
"""
import asyncio
import os
from datetime import datetime, timezone

import certifi
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.core.passwords import hash_secret

SCHOOL_CODE = os.getenv("SEED_SCHOOL_CODE", "DAV-HYD").strip().upper()
TENANT = os.getenv("SEED_TENANT", "dav-hyderabad").strip()
SCHOOL_NAME = os.getenv("SEED_SCHOOL_NAME", "DAV Hyderabad")
BOARD = os.getenv("SEED_BOARD", "CBSE")
ADMIN_EMAIL = os.getenv("SEED_ADMIN_EMAIL", "admin@dav.edu").strip().lower()
ADMIN_PASSWORD = os.getenv("SEED_ADMIN_PASSWORD", "demo1234")
ADMIN_NAME = os.getenv("SEED_ADMIN_NAME", "School Admin")


def now():
    return datetime.now(timezone.utc)


async def main():
    if not settings.MONGODB_URI:
        raise SystemExit("MONGODB_URI is not set — check .env")

    client = AsyncIOMotorClient(settings.MONGODB_URI, tls=True, tlsCAFile=certifi.where())
    db = client[settings.MONGODB_DB]
    print(f"→ Seeding auth into DB: {settings.MONGODB_DB!r}")

    # 1. School tenant (resolve_tenant_by_code matches on UPPER school_code)
    await db.tenants.update_one(
        {"tenant": TENANT},
        {"$set": {
            "tenant": TENANT, "school_code": SCHOOL_CODE, "name": SCHOOL_NAME,
            "board": BOARD, "type": "school", "status": "active",
        }, "$setOnInsert": {"created_at": now()}},
        upsert=True,
    )
    print(f"  ✓ tenant {TENANT!r}  (school_code {SCHOOL_CODE})")

    # 2. Admin login (email + password → /api/auth/login/password)
    await db.users.update_one(
        {"tenant": TENANT, "email": ADMIN_EMAIL},
        {"$set": {
            "tenant": TENANT, "email": ADMIN_EMAIL, "name": ADMIN_NAME,
            "role": "admin", "status": "active",
            "password_hash": hash_secret(ADMIN_PASSWORD),
        }, "$setOnInsert": {"created_at": now()}},
        upsert=True,
    )
    print(f"  ✓ admin  {ADMIN_EMAIL}  /  {ADMIN_PASSWORD}")

    client.close()
    print("\nDone. Log in at /auth/login → 'I'm a Teacher or Admin' with the above.")
    print(f"Then /admin/roster to import students under school code {SCHOOL_CODE}.")


if __name__ == "__main__":
    asyncio.run(main())
