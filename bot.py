"""
VK-бот Vinder: точка входа.

Работает через VkBotLongPoll (сообщество ВКонтакте).

Функционал:
  /start           → регистрация + первый кандидат
  /settings        → настройка города / возраста / пола
  ❤️ Нравится       → избранное + следующий
  ➡️ Следующий      → следующий кандидат
  🚫 В ЧС          → добавить в чёрный список + следующий
  /favorites       → избранные
  /blacklist       → текущий ЧС

Особенности:
  - Нет FSM: состояние диалога хранится в user_states (dict) + в БД.
  - Клавиатура VK вместо inline.
  - Callback-кнопки приходят как событие MESSAGE_EVENT.
  - Фото отправляются как attachment "photo{owner_id}_{id}_{access_key}".
"""
import json
import logging
import time

import vk_api
from vk_api.bot_longpoll import VkBotEventType, VkBotLongPoll
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.utils import get_random_id

from config import settings
from database import (
    SessionLocal,
    add_to_blacklist,
    add_user,
    add_viewed_profile,
    count_viewed_profiles,
    get_blacklisted_ids,
    get_favorite_candidate_ids,
    get_user,
)
from vk_client import VKClient


# --------------------------------------------------------------------------- #
#                              ИНИЦИАЛИЗАЦИЯ                                  #
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("vinder-vk-bot")

vk_session = vk_api.VkApi(token=settings.VK_GROUP_TOKEN)
vk = vk_session.get_api()
longpoll = VkBotLongPoll(vk_session, group_id=settings.VK_GROUP_ID)
client = VKClient(token=settings.VK_USER_TOKEN)

SEARCH_BATCH = settings.SEARCH_BATCH

# Состояния пользователей (in-memory). Ключ — vk_user_id.
#   {"step": "waiting_city" | "waiting_age_from" | "waiting_age_to" | "waiting_gender",
#    "data": {...}}
user_states: dict[int, dict] = {}


# --------------------------------------------------------------------------- #
#                          ОТПРАВКА СООБЩЕНИЙ                                 #
# --------------------------------------------------------------------------- #
def send_message(
        user_id: int,
        text: str,
        keyboard: VkKeyboard | None = None,
        attachments: list[str] | None = None,
) -> None:
    """Универсальная отправка сообщения пользователю."""
    params = {
        "user_id": user_id,
        "random_id": get_random_id(),
        "message": text,
    }
    if keyboard is not None:
        params["keyboard"] = keyboard.get_keyboard()
    if attachments:
        params["attachment"] = ",".join(attachments)

    try:
        vk.messages.send(**params)
    except vk_api.exceptions.ApiError as e:
        # 901 — пользователь запретил сообщения от сообщества.
        log.warning("Не удалось отправить сообщение %s: %s", user_id, e)


def answer_event(
        event_id: str, user_id: int, peer_id: int, text: str | None = None
) -> None:
    """Ответить на callback (убирает «часики» и может показать снекбар)."""
    params = {
        "event_id": event_id,
        "user_id": user_id,
        "peer_id": peer_id,
    }
    if text:
        params["event_data"] = json.dumps({"type": "show_snackbar", "text": text})
    try:
        vk.messages.sendMessageEventAnswer(**params)
    except vk_api.exceptions.ApiError as e:
        log.debug("sendMessageEventAnswer failed: %s", e)


# --------------------------------------------------------------------------- #
#                              КЛАВИАТУРЫ                                     #
# --------------------------------------------------------------------------- #
def candidate_keyboard(candidate_vk_id: int) -> VkKeyboard:
    kb = VkKeyboard(one_time=False)
    kb.add_callback_button(
        label="❤️ Нравится",
        color=VkKeyboardColor.POSITIVE,
        payload={"cmd": "like", "candidate_id": candidate_vk_id},
    )
    kb.add_callback_button(
        label="➡️ Следующий",
        color=VkKeyboardColor.PRIMARY,
        payload={"cmd": "next"},
    )
    kb.add_line()
    kb.add_callback_button(
        label="🚫 В чёрный список",
        color=VkKeyboardColor.NEGATIVE,
        payload={"cmd": "block", "candidate_id": candidate_vk_id},
    )
    return kb


def gender_keyboard() -> VkKeyboard:
    kb = VkKeyboard(one_time=True)
    kb.add_callback_button(
        label="👩 Женский",
        color=VkKeyboardColor.PRIMARY,
        payload={"cmd": "gender", "value": 1},
    )
    kb.add_callback_button(
        label="👨 Мужской",
        color=VkKeyboardColor.PRIMARY,
        payload={"cmd": "gender", "value": 2},
    )
    kb.add_line()
    kb.add_callback_button(
        label="🤷 Любой",
        color=VkKeyboardColor.SECONDARY,
        payload={"cmd": "gender", "value": 0},
    )
    return kb


def main_keyboard() -> VkKeyboard:
    kb = VkKeyboard(one_time=False)
    kb.add_button(label="➡️ Дальше", color=VkKeyboardColor.PRIMARY)
    kb.add_button(label="⚙️ Настройки", color=VkKeyboardColor.SECONDARY)
    kb.add_line()
    kb.add_button(label="❤️ Избранные", color=VkKeyboardColor.POSITIVE)
    kb.add_button(label="🚫 ЧС", color=VkKeyboardColor.NEGATIVE)
    return kb


# --------------------------------------------------------------------------- #
#                          ВСПОМОГАТЕЛЬНЫЕ                                     #
# --------------------------------------------------------------------------- #
def profile_url(candidate: dict) -> str:
    domain = candidate.get("domain") or f"id{candidate['id']}"
    return f"https://vk.com/{domain}"


def ensure_user(db, vk_id: int):
    """Гарантировать наличие BotUser; иначе создать с дефолтами."""
    user = get_user(db, vk_id)
    if user is None:
        user = add_user(
            db=db,
            vk_id=vk_id,
            city=str(settings.DEFAULT_CITY_ID),
            age_from=settings.DEFAULT_AGE_FROM,
            age_to=settings.DEFAULT_AGE_TO,
            gender=settings.DEFAULT_GENDER,
        )
    return user


# --------------------------------------------------------------------------- #
#                          ОТПРАВКА СЛЕДУЮЩЕГО                                #
# --------------------------------------------------------------------------- #
def send_next_candidate(user_id: int) -> None:
    """
    Найти, показать и сохранить следующего кандидата.

    Параметры поиска берутся из BotUser (могут быть изменены через /settings).
    Кандидаты из ЧС пропускаются.
    """
    with SessionLocal() as db:
        user = ensure_user(db, user_id)
        city_id = int(user.city) if user.city else settings.DEFAULT_CITY_ID
        age_from = user.age_from
        age_to = user.age_to
        gender = user.gender

        offset = count_viewed_profiles(db, user_id)
        blacklisted = set(get_blacklisted_ids(db, user_id))

        candidate = None
        max_attempts = 5

        for _ in range(max_attempts):
            try:
                candidates = client.get_candidates(
                    city_id=city_id,
                    age_from=age_from,
                    age_to=age_to,
                    gender=gender,
                    offset=offset,
                    count=SEARCH_BATCH,
                )
            except RuntimeError as e:
                log.exception("VK API error while fetching candidates")
                send_message(user_id, f"⚠️ Ошибка VK API: {e}")
                return

            if not candidates:
                break

            for c in candidates:
                if c["id"] not in blacklisted:
                    candidate = c
                    break
            if candidate is not None:
                break

            offset += len(candidates)

        if candidate is None:
            send_message(
                user_id,
                "Кандидаты закончились 😔 Попробуй позже.",
                keyboard=main_keyboard(),
            )
            return

        candidate_vk_id = candidate["id"]
        first_name = candidate.get("first_name", "")
        last_name = candidate.get("last_name", "")
        url = profile_url(candidate)

        # Топ-3 фото.
        try:
            photos = client.get_top_photos(candidate_vk_id, count=3)
        except RuntimeError as e:
            log.warning("Не удалось получить фото для %s: %s", candidate_vk_id, e)
            photos = []

        # Формируем attachments вида photo{owner_id}_{id}_{access_key}.
        attachments = []
        for p in photos:
            if not p.get("id") or not p.get("owner_id"):
                continue
            att = f"photo{p['owner_id']}_{p['id']}"
            if p.get("access_key"):
                att += f"_{p['access_key']}"
            attachments.append(att)

        text = f"👤 {first_name} {last_name}\n🔗 {url}"
        send_message(
            user_id,
            text,
            keyboard=candidate_keyboard(candidate_vk_id),
            attachments=attachments,
        )

        add_viewed_profile(
            db=db,
            bot_user_vk_id=user_id,
            candidate_vk_id=candidate_vk_id,
            is_favorited=None,
        )


# --------------------------------------------------------------------------- #
#                              КОМАНДЫ                                         #
# --------------------------------------------------------------------------- #
def cmd_start(user_id: int) -> None:
    with SessionLocal() as db:
        user = ensure_user(db, user_id)
        send_message(
            user_id,
            f"Привет! 👋\n\n"
            f"Твои параметры поиска:\n"
            f"• Город ID: {user.city}\n"
            f"• Возраст: {user.age_from}–{user.age_to}\n"
            f"• Пол ищущего: {user.gender}\n\n"
            f"Настроить — /settings. Погнали 🚀",
        )
    send_next_candidate(user_id)


def cmd_settings(user_id: int) -> None:
    user_states[user_id] = {"step": "waiting_city", "data": {}}
    send_message(
        user_id,
        "Введи ID города ВКонтакте (число).\n"
        "Например: 1 — Москва, 2 — Санкт-Петербург.\n\n"
        "Отмена — /cancel.",
    )


def cmd_cancel(user_id: int) -> None:
    user_states.pop(user_id, None)
    send_message(user_id, "Настройка отменена.", keyboard=main_keyboard())


def cmd_favorites(user_id: int) -> None:
    with SessionLocal() as db:
        fav_ids = get_favorite_candidate_ids(db, user_id)
    if not fav_ids:
        send_message(user_id, "У тебя пока нет избранных 💔")
        return

    try:
        infos = client.get_users_info(fav_ids)
    except RuntimeError as e:
        log.exception("VK API error while fetching favorites")
        send_message(user_id, f"⚠️ Не удалось получить данные из VK: {e}")
        return

    lines = ["Твои избранные:"]
    for info in infos:
        domain = info.get("domain") or f"id{info['id']}"
        url = f"https://vk.com/{domain}"
        name = f"{info.get('first_name', '')} {info.get('last_name', '')}".strip()
        lines.append(f"• {name or info['id']} — {url}")
    send_message(user_id, "\n".join(lines))


def cmd_blacklist(user_id: int) -> None:
    with SessionLocal() as db:
        blocked_ids = get_blacklisted_ids(db, user_id)
    if not blocked_ids:
        send_message(user_id, "Чёрный список пуст.")
        return
    lines = ["В чёрном списке:"] + [f"• {vid}" for vid in blocked_ids]
    send_message(user_id, "\n".join(lines))


# --------------------------------------------------------------------------- #
#                          ОБРАБОТКА ТЕКСТА                                    #
# --------------------------------------------------------------------------- #
def handle_text(user_id: int, text: str) -> None:
    text_lower = text.strip().lower()
    state = user_states.get(user_id)

    # --- Если пользователь в диалоге настройки ---
    if state:
        step = state["step"]

        if step == "waiting_city":
            if not text.strip().isdigit():
                send_message(user_id, "Нужно целое число. Попробуй ещё раз:")
                return
            state["data"]["city"] = text.strip()
            state["step"] = "waiting_age_from"
            send_message(user_id, "Минимальный возраст (число):")
            return

        if step == "waiting_age_from":
            t = text.strip()
            if not t.isdigit() or not (14 <= int(t) <= 99):
                send_message(user_id, "Введи число от 14 до 99:")
                return
            state["data"]["age_from"] = int(t)
            state["step"] = "waiting_age_to"
            send_message(user_id, "Максимальный возраст (число):")
            return

        if step == "waiting_age_to":
            t = text.strip()
            if not t.isdigit():
                send_message(user_id, "Введи число:")
                return
            age_to = int(t)
            if age_to < state["data"]["age_from"]:
                send_message(
                    user_id,
                    f"Максимум должен быть ≥ {state['data']['age_from']}. "
                    f"Попробуй ещё раз:",
                )
                return
            state["data"]["age_to"] = age_to
            state["step"] = "waiting_gender"
            send_message(user_id, "Кого ищем?", keyboard=gender_keyboard())
            return

        # waiting_gender — ждём нажатия кнопки, текст игнорируем.

    # --- Команды ---
    if text_lower in ("начать", "start", "/start", "привет"):
        cmd_start(user_id)
        return
    if text_lower in ("/settings", "настройки", "⚙️ настройки"):
        cmd_settings(user_id)
        return
    if text_lower in ("/cancel", "отмена"):
        cmd_cancel(user_id)
        return
    if text_lower in ("/favorites", "избранные", "❤️ избранные"):
        cmd_favorites(user_id)
        return
    if text_lower in ("/blacklist", "чс", "🚫 чс"):
        cmd_blacklist(user_id)
        return
    if text_lower in ("дальше", "следующий", "/next", "➡️ дальше"):
        send_next_candidate(user_id)
        return

    # --- По умолчанию ---
    send_message(
        user_id,
        "Не понял команду. Доступно:\n"
        "/start, /settings, /favorites, /blacklist.\n"
        "Или жми кнопки ниже.",
        keyboard=main_keyboard(),
    )


# --------------------------------------------------------------------------- #
#                          ОБРАБОТКА CALLBACK                                  #
# --------------------------------------------------------------------------- #
def handle_callback(event) -> None:
    """Обработка нажатия на callback-кнопку."""
    # Payload приходит как JSON-строка, её нужно распарсить
    payload_raw = event.object.payload
    payload = json.loads(payload_raw) if isinstance(payload_raw, str) else (payload_raw or {})

    user_id = event.object.user_id
    peer_id = event.object.peer_id
    event_id = event.object.event_id

    cmd = payload.get("cmd")

    # --- Настройка: выбор пола ---
    if cmd == "gender":
        gender = int(payload.get("value", 0))
        state = user_states.get(user_id)
        if not state or state.get("step") != "waiting_gender":
            answer_event(event_id, user_id, peer_id, "Настройка уже завершена")
            return

        data = state["data"]
        with SessionLocal() as db:
            add_user(
                db=db,
                vk_id=user_id,
                city=data["city"],
                age_from=data["age_from"],
                age_to=data["age_to"],
                gender=gender,
            )
        user_states.pop(user_id, None)
        answer_event(event_id, user_id, peer_id, "Сохранено ✅")
        send_message(user_id, "Настройки обновлены. Ищу новых кандидатов…")
        send_next_candidate(user_id)
        return

    # --- Лайк ---
    if cmd == "like":
        candidate_vk_id = int(payload.get("candidate_id", 0))
        if not candidate_vk_id:
            answer_event(event_id, user_id, peer_id, "Ошибка")
            return
        with SessionLocal() as db:
            add_viewed_profile(
                db=db,
                bot_user_vk_id=user_id,
                candidate_vk_id=candidate_vk_id,
                is_favorited=True,
            )
        answer_event(event_id, user_id, peer_id, "Добавлено в избранное ❤️")
        send_next_candidate(user_id)
        return

    # --- Следующий ---
    if cmd == "next":
        answer_event(event_id, user_id, peer_id)
        send_next_candidate(user_id)
        return

    # --- В чёрный список ---
    if cmd == "block":
        candidate_vk_id = int(payload.get("candidate_id", 0))
        if not candidate_vk_id:
            answer_event(event_id, user_id, peer_id, "Ошибка")
            return
        with SessionLocal() as db:
            add_to_blacklist(
                db=db,
                bot_user_vk_id=user_id,
                candidate_vk_id=candidate_vk_id,
            )
        answer_event(event_id, user_id, peer_id, "Добавлено в ЧС 🚫")
        send_next_candidate(user_id)
        return

    answer_event(event_id, user_id, peer_id, "Неизвестная команда")


# --------------------------------------------------------------------------- #
#                              ГЛАВНЫЙ ЦИКЛ                                    #
# --------------------------------------------------------------------------- #
def main() -> None:
    log.info("VK bot started (group_id=%s)", settings.VK_GROUP_ID)

    for event in longpoll.listen():
        try:
            if event.type == VkBotEventType.MESSAGE_NEW:
                msg = event.obj.message
                # Игнорируем сообщения от самого сообщества.
                if msg.get("out"):
                    continue
                user_id = msg["from_id"]
                text = msg.get("text", "")
                handle_text(user_id, text)

            elif event.type == VkBotEventType.MESSAGE_EVENT:
                handle_callback(event)

        except Exception:
            log.exception("Ошибка при обработке события")
            # Не роняем бота из-за одного события.
            time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        log.info("VK bot stopped")