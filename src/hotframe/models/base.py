"""
SQLAlchemy declarative base and abstract model classes.

Provides Base, HubBaseModel, TimeStampedModel, and ActiveModel.
All use SQLAlchemy 2.0 mapped_column style with UUID primary keys.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Root declarative base for all models."""
    pass


class HubBaseModel(Base):
    """
    Abstract base for hub-scoped models.

    Includes: UUID PK, hub_id FK, timestamps, audit fields, soft delete.
    Most module models should inherit from this.
    """

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4,
    )
    hub_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, index=True,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True,
    )

    # Soft delete
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", index=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )


class TimeStampedModel(Base):
    """Abstract base with only timestamps (created_at, updated_at)."""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ActiveModel(Base):
    """Abstract base with timestamps + is_active flag."""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true",
    )
