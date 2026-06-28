"""Seed the auth/identity plane for the pilot (SPEC §10.3).

Idempotent. Creates a tenant + one of each role so every login path in P1 is
testable, and prints the generated secrets (dev only — these are throwaway).

    python -m app.scripts.seed_auth
    python -m app.scripts.seed_auth --tenant demo-school --school-code DEMO

What it creates (all under one tenant):
  - superadmin  (email + password)
  - school admin (email + password)
  - teacher      (email + password)
  - parent       (phone + OTP)         linked to ↓
  - student      (student_code + PIN)  + a soft child-PIN for family mode
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

from ..core.config import settings
from ..core.passwords import (
    generate_pin,
    generate_student_code,
    hash_password,
    hash_pin,
)
from ..db.mongo import get_db, init_indexes
from ..services.otp_service import normalize_phone


def _now():
    return datetime.now(timezone.utc)


async def _upsert_user(db, *, tenant, role, match, doc):
    """Upsert a user by a stable match key; never clobber an existing password/pin
    so re-running doesn't rotate secrets out from under a tester."""
    existing = await db.users.find_one({"tenant": tenant, "role": role, **match})
    if existing:
        return existing, False
    doc = {**doc, "tenant": tenant, "role": role, "status": "active",
           "failed_attempts": 0, "locked_until": None, "created_at": _now()}
    res = await db.users.insert_one(doc)
    doc["_id"] = res.inserted_id
    return doc, True


async def seed(tenant: str, school_code: str):
    db = await get_db()
    await init_indexes()

    created: dict[str, str] = {}

    # --- tenant ---------------------------------------------------------------
    await db.tenants.update_one(
        {"tenant": tenant},
        {"$set": {
            "tenant": tenant, "school_code": school_code.upper(),
            "name": "Demo Public School", "board": "CBSE", "status": "active",
            "type": "school",  # two-axis: content source = school (teacher transcript)
            "sso": {"provider": None, "domain": None},
            "settings": {"student_login": ["family", "pin"], "consent_required": True},
            "group_id": None,
        }, "$setOnInsert": {"created_at": _now()}},
        upsert=True,
    )

    # --- superadmin -----------------------------------------------------------
    super_pw = "Super@123"
    await _upsert_user(
        db, tenant=tenant, role="superadmin",
        match={"email": "super@mymedha.app"},
        doc={"email": "super@mymedha.app", "name": "Platform Super Admin",
             "password_hash": hash_password(super_pw)},
    )
    created["superadmin"] = "super@mymedha.app / " + super_pw

    # --- school admin ---------------------------------------------------------
    admin_pw = "Admin@123"
    await _upsert_user(
        db, tenant=tenant, role="admin",
        match={"email": "admin@demo.app"},
        doc={"email": "admin@demo.app", "name": "Demo School Admin",
             "password_hash": hash_password(admin_pw)},
    )
    created["admin"] = "admin@demo.app / " + admin_pw

    # --- teacher --------------------------------------------------------------
    teacher_pw = "Teacher@123"
    await _upsert_user(
        db, tenant=tenant, role="teacher",
        match={"email": "teacher@demo.app"},
        doc={"email": "teacher@demo.app", "name": "Demo Teacher",
             "password_hash": hash_password(teacher_pw)},
    )
    created["teacher"] = "teacher@demo.app / " + teacher_pw

    # --- student (school-device path) ----------------------------------------
    student_id = "STU-DEMO-1"
    student_code = generate_student_code(school_code=school_code, class_no=9, section="A")
    student_pin = generate_pin(settings.STUDENT_PIN_LENGTH)
    child_pin = generate_pin(settings.CHILD_PIN_LENGTH)
    student, fresh = await _upsert_user(
        db, tenant=tenant, role="student",
        match={"student_id": student_id},
        doc={"student_id": student_id, "name": "Aarav Demo", "class_no": 9, "section": "A",
             "roll_no": "7", "student_code": student_code, "mascot": "fox",
             # two-axis identity: content source = school (transcript-driven)
             "enrollment": {"type": "school", "class_no": 9, "section": "A", "board": "CBSE"},
             "pin_hash": hash_pin(child_pin)},  # child soft-PIN for family mode
    )
    if fresh:
        # also store the school-device login PIN (separate from the soft child PIN
        # is overkill for the demo; we reuse one PIN for both paths here)
        await db.users.update_one(
            {"_id": student["_id"]},
            {"$set": {"pin_hash": hash_pin(student_pin)}},
        )
        created["student"] = f"code={student_code}  pin={student_pin}  (student_id={student_id})"
    else:
        created["student"] = f"(exists) student_id={student_id} code={student.get('student_code')}"

    # --- parent (phone OTP) + link -------------------------------------------
    parent_phone = normalize_phone("+919000000001")
    parent, _ = await _upsert_user(
        db, tenant=tenant, role="parent",
        match={"phone": parent_phone},
        doc={"phone": parent_phone, "name": "Demo Parent"},
    )
    await db.parent_links.update_one(
        {"tenant": tenant, "parent_id": str(parent["_id"]), "student_id": student_id},
        {"$set": {
            "tenant": tenant, "parent_id": str(parent["_id"]), "student_id": student_id,
            "relationship": "father", "status": "active",
            "consent": {"granted": True, "granted_at": _now(), "method": "seed",
                        "scope": ["learning", "progress"]},
        }, "$setOnInsert": {"created_at": _now()}},
        upsert=True,
    )
    created["parent"] = f"phone={parent_phone}  (OTP echoed in dev) → linked to {student_id}"

    # --- second child (Diya) — UNLINKED, with a pending invite ---------------
    # Lets us exercise the claim flow: same parent phone, a new invitation that
    # should *add* Diya to the existing parent (idempotent), not duplicate.
    student2_id = "STU-DEMO-2"
    code2 = generate_student_code(school_code=school_code, class_no=2, section="B")
    await _upsert_user(
        db, tenant=tenant, role="student",
        match={"student_id": student2_id},
        doc={"student_id": student2_id, "name": "Diya Demo", "class_no": 2, "section": "B",
             "roll_no": "12", "student_code": code2, "mascot": "owl",
             "enrollment": {"type": "school", "class_no": 2, "section": "B", "board": "CBSE"},
             "pin_hash": hash_pin(generate_pin(settings.CHILD_PIN_LENGTH))},
    )
    from ..services.invite_service import create_invite
    existing_inv = await db.invites.find_one({"tenant": tenant, "student_id": student2_id, "status": "pending"})
    if not existing_inv:
        inv = await create_invite(db, tenant=tenant, student_id=student2_id,
                                  parent_phone=parent_phone, relationship="father",
                                  parent_name="Demo Parent")
        created["invite (Diya)"] = f"token={inv['token']}  → claim adds {student2_id} to {parent_phone}"
    else:
        created["invite (Diya)"] = f"(exists) pending invite for {student2_id}"

    print("\n=== Seeded auth for tenant:", tenant, f"(school_code={school_code.upper()}) ===")
    for role, cred in created.items():
        print(f"  {role:11s}: {cred}")
    print("\nLogin smoke tests:")
    print("  POST /api/auth/login/password  {identifier, password}")
    print("  POST /api/auth/login/student   {tenant, student_code, pin}")
    print("  POST /api/auth/login/otp/request {phone}  → returns dev_otp")
    print("  POST /api/auth/login/otp/verify  {phone, code}")
    print("  POST /api/auth/family/switch   {student_id}  (parent token)\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="demo-school")
    ap.add_argument("--school-code", default="DEMO")
    args = ap.parse_args()
    asyncio.run(seed(args.tenant, args.school_code))


if __name__ == "__main__":
    main()
