"""Captures the content snapshot of every course version that doesn't have one
yet - in practice the "1.0 baseline" versions the content-governance migration
created for courses published before governance existed.

Without a snapshot a version can't be diffed against or rolled back to. The
first working copy of a course captures its baseline lazily anyway; run this
once after deploying the migration so every course has history from day one.

Idempotent: versions that already have a snapshot are skipped.

Usage:
    python -m app.scripts.backfill_course_snapshots
"""

import asyncio

from sqlalchemy import select

import app.models  # noqa: F401 - registers every entity on Base.metadata before use
from app.core.database import AsyncSessionLocal
from app.modules.course.entity import Course
from app.modules.governance.draft_scope import include_drafts
from app.modules.governance.entity import CourseVersion
from app.modules.governance.tree import build_normalized_tree, tree_hash


async def main() -> None:
    filled = failed = 0
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(CourseVersion, Course)
                .join(Course, Course.id == CourseVersion.course_id)
                .where(CourseVersion.snapshot.is_(None), CourseVersion.is_current.is_(True))
            )
        ).all()
        for version, course in rows:
            try:
                with include_drafts(session):
                    snapshot = await build_normalized_tree(session, course)
                version.snapshot = snapshot
                version.snapshot_hash = tree_hash(snapshot)
                await session.commit()
                filled += 1
                print(f"  captured {course.title} v{version.label}")
            except Exception as exc:  # keep going; report at the end
                await session.rollback()
                failed += 1
                print(f"  FAILED {course.title} v{version.label}: {exc}")
    print(f"Done: {filled} snapshot(s) captured, {failed} failure(s).")
    # Only the current version can be captured: older versions' content is gone.


if __name__ == "__main__":
    asyncio.run(main())
