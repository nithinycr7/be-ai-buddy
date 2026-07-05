"""School roster provisioning (SPEC §3.1, §8).

School admin imports a roster → we bulk-create student auth records (opaque
student_code + random PIN, mirroring seed_auth), and create a parent invite per
row (email-first). The PLAINTEXT code+PIN are returned ONCE so the admin can print
login slips — they are bcrypt-hashed at rest and never recoverable afterwards.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from ..core.config import settings
from ..core.passwords import generate_pin, generate_student_code, hash_pin
from . import invite_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def import_roster(
    db: AsyncIOMotorDatabase,
    *,
    tenant: str,
    rows: List[dict],
    created_by: Optional[str] = None,
    base_url: str = "",
) -> dict:
    """Create students + parent invites for each roster row. Returns the generated
    credentials (code + plaintext PIN) for printable slips, plus skipped rows."""
    school = await db.tenants.find_one({"tenant": tenant})
    school_code = (school or {}).get("school_code") or tenant

    credentials: List[dict] = []
    skipped: List[dict] = []

    for row in rows:
        name = (row.get("name") or "").strip()
        class_no = row.get("class_no")
        section = (row.get("section") or "").strip().upper()
        roll_no = str(row.get("roll_no") or "").strip()
        parent_email = (row.get("parent_email") or "").strip() or None
        parent_phone = (row.get("parent_phone") or "").strip() or None

        if not name or class_no in (None, "") or not section:
            skipped.append({"row": row, "reason": "missing name/class/section"})
            continue

        try:
            class_no = int(class_no)
        except (TypeError, ValueError):
            skipped.append({"row": row, "reason": "class_no not a number"})
            continue

        # Natural key within a school — don't duplicate on re-import.
        if roll_no and await db.users.find_one({
            "tenant": tenant, "role": "student",
            "class_no": class_no, "section": section, "roll_no": roll_no,
        }):
            skipped.append({"row": row, "reason": "already exists (class/section/roll)"})
            continue

        student_id = f"STU-{uuid.uuid4().hex[:10].upper()}"
        student_code = generate_student_code(school_code=school_code, class_no=class_no, section=section)
        pin = generate_pin(settings.STUDENT_PIN_LENGTH)

        await db.users.insert_one({
            "tenant": tenant, "role": "student", "status": "active",
            "student_id": student_id, "name": name,
            "class_no": class_no, "section": section, "roll_no": roll_no,
            "student_code": student_code, "pin_hash": hash_pin(pin),
            "enrollment": {"type": "school", "class_no": class_no, "section": section, "board": "CBSE"},
            "failed_attempts": 0, "locked_until": None, "created_at": _now(),
        })

        invited = None
        if parent_email or parent_phone:
            inv = await invite_service.create_invite(
                db, tenant=tenant, student_id=student_id,
                parent_email=parent_email, parent_phone=parent_phone,
                parent_name=None, created_by=created_by,
            )
            if base_url:
                try:
                    await invite_service.send_invite(
                        db, token=inv["token"], tenant=tenant,
                        parent_email=parent_email, parent_phone=parent_phone, base_url=base_url,
                    )
                    invited = "sent"
                except Exception:  # best-effort; slip is still valid
                    invited = "created"
            else:
                invited = "created"

        credentials.append({
            "name": name, "class_no": class_no, "section": section, "roll_no": roll_no,
            "student_code": student_code, "pin": pin,
            "parent_email": parent_email, "parent_phone": parent_phone,
            "invite": invited,
        })

    return {"count": len(credentials), "skipped": len(skipped),
            "credentials": credentials, "skipped_rows": skipped}
