# Import every entity module here so SQLAlchemy registers it on Base.metadata
# before Alembic's autogenerate (or app startup) inspects it.

from app.modules.auth.entity import PasswordResetToken, RefreshToken  # noqa: F401
from app.modules.user.entity import User  # noqa: F401
