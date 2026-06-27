# Import every entity module here so SQLAlchemy registers it on Base.metadata
# before Alembic's autogenerate (or app startup) inspects it.
#
# Example, once you add an entity:
#   from app.modules.user.entity import User  # noqa: F401
