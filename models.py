"""
SQLAlchemy-модели проекта Vinder.

Все временные метки хранятся в UTC с явным timezone (aware),
чтобы не зависеть от deprecated datetime.utcnow().
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utcnow() -> datetime:
    """Текущее время в UTC (aware). Замена deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc)


class BotUser(Base):
    __tablename__ = "bot_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vk_id = Column(Integer, unique=True, nullable=False)
    city = Column(String, nullable=True)
    age_from = Column(Integer, default=18, nullable=False)
    age_to = Column(Integer, default=99, nullable=False)
    gender = Column(Integer, nullable=False, default=0)

    viewed = relationship("ViewedProfile", back_populates="user")
    blacklist = relationship("BlackList", back_populates="user")


class ViewedProfile(Base):
    __tablename__ = "viewed_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_user_id = Column(Integer, ForeignKey("bot_users.id"), nullable=False)
    candidate_vk_id = Column(Integer, nullable=False)
    is_favorited = Column(Boolean, default=False, nullable=False)
    viewed_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    user = relationship("BotUser", back_populates="viewed")

    __table_args__ = (
        UniqueConstraint("bot_user_id", "candidate_vk_id", name="_user_candidate_uc"),
    )


class BlackList(Base):
    __tablename__ = "blacklist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_user_id = Column(Integer, ForeignKey("bot_users.id"), nullable=False)
    blocked_candidate_vk_id = Column(Integer, nullable=False)
    added_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    user = relationship("BotUser", back_populates="blacklist")

    __table_args__ = (
        UniqueConstraint(
            "bot_user_id", "blocked_candidate_vk_id", name="_user_blocked_uc"
        ),
    )