"""ORM models (users, OAuth identities, per-user Dockerfiles)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    ai_prefill_preferences: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    oauth_identities: Mapped[list["UserOAuthIdentity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    dockerfiles: Mapped[list["Dockerfile"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class UserOAuthIdentity(Base):
    """Link a user to an external OAuth provider (currently GitHub).

    Stores the provider-issued access token encrypted at rest (Fernet); only the
    provider, subject id, and display fields are kept in plaintext so the API can
    show "Connected as @username" without ever leaking the token itself.
    """

    __tablename__ = "user_oauth_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_subject", name="uq_oauth_provider_subject"
        ),
        UniqueConstraint("provider", "user_id", name="uq_oauth_provider_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    scopes: Mapped[str | None] = mapped_column(String(512), nullable=True)
    access_token_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    user: Mapped[User] = relationship(back_populates="oauth_identities")


class Dockerfile(Base):
    __tablename__ = "dockerfiles"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_dockerfiles_owner_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contents: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    owner: Mapped[User] = relationship(back_populates="dockerfiles")


class DeploymentRecord(Base):
    __tablename__ = "deployment_records"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    container_id: Mapped[str] = mapped_column(String(128), nullable=False)
    container_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(2048), nullable=False)
    git_branch: Mapped[str | None] = mapped_column(String(256), nullable=True)
    image_tag: Mapped[str] = mapped_column(String(512), nullable=False)
    container_port: Mapped[int] = mapped_column(Integer, nullable=False)
    env_vars: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    command: Mapped[list | None] = mapped_column(JSON, nullable=True)
    dockerfile_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )

    user: Mapped[User] = relationship()


class EmailPreference(Base):
    __tablename__ = "email_preferences"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    alerts_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    alert_types: Mapped[list] = mapped_column(
        JSON, nullable=False, default=lambda: ["stop", "failure", "unhealthy"]
    )
    alert_frequency: Mapped[str] = mapped_column(
        String(32), nullable=False, default="immediate"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    user: Mapped[User] = relationship()


class AlertHistory(Base):
    __tablename__ = "alert_history"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    container_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    alert_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
    email_sent_to: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="sent")

    user: Mapped[User] = relationship()
