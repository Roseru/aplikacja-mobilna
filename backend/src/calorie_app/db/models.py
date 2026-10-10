from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from calorie_app.db.base import Base


class UserAccount(Base):
    __tablename__ = "user_accounts"
    __table_args__ = (
        UniqueConstraint("issuer", "subject"),
        CheckConstraint("generation >= 1", name="positive_generation"),
        CheckConstraint("state IN ('active', 'deleting')", name="account_state"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    issuer: Mapped[str] = mapped_column(String(2048))
    subject: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    generation: Mapped[int] = mapped_column(default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Compatibility imports for the E1 skeleton; table definitions live in catalog.
from calorie_app.modules.catalog.models import (  # noqa: E402, F401
    Product,
    ProductSource,
    ProductVersion,
)
