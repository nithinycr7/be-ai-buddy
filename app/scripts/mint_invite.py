"""Mint a parent invitation link for testing/demo (stands in for roster import).

    python -m app.scripts.mint_invite --student-id STU-DEMO-2 --phone +919000000001
    python -m app.scripts.mint_invite --student-id STU-DEMO-2 --phone +919000000001 --web http://localhost:5173

Prints the claim URL the parent would receive by SMS.
"""
from __future__ import annotations

import argparse
import asyncio

from ..db.mongo import get_db, init_indexes
from ..services.invite_service import create_invite


async def run(tenant, student_id, phone, name, web):
    db = await get_db()
    await init_indexes()
    student = await db.users.find_one({"tenant": tenant, "role": "student", "student_id": student_id})
    if not student:
        raise SystemExit(f"No student {student_id} in tenant {tenant} (DB={db.name}). Seed first.")
    inv = await create_invite(db, tenant=tenant, student_id=student_id, parent_phone=phone,
                              relationship="guardian", parent_name=name)
    print(f"\nInvite created (DB={db.name}, tenant={tenant})")
    print(f"  child      : {student.get('name')} ({student_id})")
    print(f"  parent     : {inv['parent_phone']}")
    print(f"  token      : {inv['token']}")
    print(f"  CLAIM LINK : {web.rstrip('/')}/auth/invite/{inv['token']}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="demo-school")
    ap.add_argument("--student-id", required=True)
    ap.add_argument("--phone", required=True)
    ap.add_argument("--name", default=None)
    ap.add_argument("--web", default="http://localhost:5173")
    a = ap.parse_args()
    asyncio.run(run(a.tenant, a.student_id, a.phone, a.name, a.web))


if __name__ == "__main__":
    main()
