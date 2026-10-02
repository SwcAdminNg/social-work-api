from contextlib import contextmanager

from sqlalchemy.ext.asyncio import AsyncSession


@contextmanager
def include_drafts(session: AsyncSession):
    """Lets ORM queries inside the block see draft-layer rows (sections/items of
    a revision's working copy), which are otherwise filtered out of every SELECT
    by the listener in app/modules/course/entity.py. Restores the previous state
    on exit, so nesting is safe."""
    sync_session = session.sync_session
    previous = sync_session.info.get("include_drafts", False)
    sync_session.info["include_drafts"] = True
    try:
        yield
    finally:
        sync_session.info["include_drafts"] = previous
