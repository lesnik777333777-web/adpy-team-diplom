"""
CRUD-функции над моделями из models.py.

Строка подключения к БД берётся из config.settings.DATABASE_URL.
Сессия открывается через SessionLocal() внутри каждой функции или через
контекстный менеджер `with SessionLocal() as db:` в bot.py.
"""
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from config import settings
from models import Base, BlackList, BotUser, ViewedProfile, utcnow


# --------------------------------------------------------------------------- #
#                          ДВИЖОК И СЕССИИ                                    #
# --------------------------------------------------------------------------- #
engine = create_engine(settings.DATABASE_URL, echo=False, future=True)


# Для SQLite включаем FK-ограничения (иначе они игнорируются).
if settings.DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


Base.metadata.create_all(engine)

SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
)


# --------------------------------------------------------------------------- #
#                                  USERS                                      #
# --------------------------------------------------------------------------- #
def add_user(
        db: Session,
        vk_id: int,
        city: str | None = None,
        age_from: int = 18,
        age_to: int = 99,
        gender: int = 0,
) -> BotUser:
    """Создать или обновить BotUser по vk_id."""
    user = db.scalar(select(BotUser).where(BotUser.vk_id == vk_id))

    if user is None:
        user = BotUser(
            vk_id=vk_id, city=city, age_from=age_from, age_to=age_to, gender=gender
        )
        db.add(user)
    else:
        user.city = city
        user.age_from = age_from
        user.age_to = age_to
        user.gender = gender

    db.commit()
    db.refresh(user)
    return user


def get_user(db: Session, vk_id: int) -> BotUser | None:
    """Найти BotUser по его vk_id."""
    return db.scalar(select(BotUser).where(BotUser.vk_id == vk_id))


# --------------------------------------------------------------------------- #
#                             VIEWED PROFILES                                 #
# --------------------------------------------------------------------------- #
def add_viewed_profile(
        db: Session,
        bot_user_vk_id: int,
        candidate_vk_id: int,
        is_favorited: bool | None = None,
) -> ViewedProfile:
    """
    Сохранить факт просмотра профиля.

    :param is_favorited: None — не трогать флаг (по умолчанию при создании False);
                         True/False — явно выставить.
    """
    user = db.scalar(select(BotUser).where(BotUser.vk_id == bot_user_vk_id))
    if user is None:
        raise ValueError(f"BotUser с vk_id={bot_user_vk_id} не найден")

    viewed = db.scalar(
        select(ViewedProfile).where(
            ViewedProfile.bot_user_id == user.id,
            ViewedProfile.candidate_vk_id == candidate_vk_id,
            )
    )

    if viewed is None:
        viewed = ViewedProfile(
            bot_user_id=user.id,
            candidate_vk_id=candidate_vk_id,
            is_favorited=bool(is_favorited),
            viewed_at=utcnow(),
        )
        db.add(viewed)
    else:
        if is_favorited is not None:
            viewed.is_favorited = is_favorited
        viewed.viewed_at = utcnow()

    db.commit()
    db.refresh(viewed)
    return viewed


def set_favorited(db: Session, bot_user_vk_id: int, candidate_vk_id: int) -> None:
    """Пометить профиль как избранный (флаг не сбрасывается)."""
    add_viewed_profile(
        db=db,
        bot_user_vk_id=bot_user_vk_id,
        candidate_vk_id=candidate_vk_id,
        is_favorited=True,
    )


def count_viewed_profiles(db: Session, bot_user_vk_id: int) -> int:
    """Сколько профилей пользователь уже посмотрел (offset для VK API)."""
    user = db.scalar(select(BotUser).where(BotUser.vk_id == bot_user_vk_id))
    if user is None:
        return 0
    return db.scalar(
        select(func.count())
        .select_from(ViewedProfile)
        .where(ViewedProfile.bot_user_id == user.id)
    ) or 0


def get_viewed_candidate_ids(db: Session, bot_user_vk_id: int) -> set[int]:
    """Множество vk_id всех просмотренных кандидатов."""
    user = db.scalar(select(BotUser).where(BotUser.vk_id == bot_user_vk_id))
    if user is None:
        return set()
    stmt = select(ViewedProfile.candidate_vk_id).where(
        ViewedProfile.bot_user_id == user.id
    )
    return set(db.scalars(stmt).all())


def get_favorite_candidate_ids(db: Session, bot_user_vk_id: int) -> list[int]:
    """vk_id избранных кандидатов (свежие — сверху)."""
    user = db.scalar(select(BotUser).where(BotUser.vk_id == bot_user_vk_id))
    if user is None:
        return []

    stmt = (
        select(ViewedProfile.candidate_vk_id)
        .where(
            ViewedProfile.bot_user_id == user.id,
            ViewedProfile.is_favorited.is_(True),
            )
        .order_by(ViewedProfile.viewed_at.desc())
    )
    return list(db.scalars(stmt).all())


# --------------------------------------------------------------------------- #
#                                BLACKLIST                                    #
# --------------------------------------------------------------------------- #
def add_to_blacklist(
        db: Session,
        bot_user_vk_id: int,
        candidate_vk_id: int,
) -> BlackList:
    """
    Добавить кандидата в чёрный список. Идемпотентно:
    повторный вызов не создаёт дубликат (UNIQUE(bot_user_id, blocked_candidate_vk_id)).
    """
    user = db.scalar(select(BotUser).where(BotUser.vk_id == bot_user_vk_id))
    if user is None:
        raise ValueError(f"BotUser с vk_id={bot_user_vk_id} не найден")

    existing = db.scalar(
        select(BlackList).where(
            BlackList.bot_user_id == user.id,
            BlackList.blocked_candidate_vk_id == candidate_vk_id,
            )
    )
    if existing is not None:
        return existing

    entry = BlackList(
        bot_user_id=user.id,
        blocked_candidate_vk_id=candidate_vk_id,
        added_at=utcnow(),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def get_blacklisted_ids(db: Session, bot_user_vk_id: int) -> list[int]:
    """Список vk_id, заблокированных пользователем (свежие — сверху)."""
    user = db.scalar(select(BotUser).where(BotUser.vk_id == bot_user_vk_id))
    if user is None:
        return []

    stmt = (
        select(BlackList.blocked_candidate_vk_id)
        .where(BlackList.bot_user_id == user.id)
        .order_by(BlackList.added_at.desc())
    )
    return list(db.scalars(stmt).all())


def remove_from_blacklist(
        db: Session, bot_user_vk_id: int, candidate_vk_id: int
) -> bool:
    """Убрать кандидата из ЧС. Возвращает True, если запись была удалена."""
    user = db.scalar(select(BotUser).where(BotUser.vk_id == bot_user_vk_id))
    if user is None:
        return False

    entry = db.scalar(
        select(BlackList).where(
            BlackList.bot_user_id == user.id,
            BlackList.blocked_candidate_vk_id == candidate_vk_id,
            )
    )
    if entry is None:
        return False

    db.delete(entry)
    db.commit()
    return True