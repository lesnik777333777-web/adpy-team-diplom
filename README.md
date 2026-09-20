# 🎯 Vinder Bot — бот ВКонтакте для поиска людей

Бот ВКонтакте, который находит новых людей по заданным фильтрам
(город, возраст, пол), показывает их лучшие фотографии и позволяет лайкать
или добавлять в чёрный список. Работает от имени **сообщества ВК** через
`VkBotLongPoll`, хранит состояние в **PostgreSQL/SQLite** через
**SQLAlchemy 2.0**, а для обхода лимита VK в 1000 результатов использует
`vk.execute` + VKScript.
## Демонстрация работы
img_1.png
img_2.png
img_3.png

## 🛠 Стек

| Компонент      | Инструмент                       |
|----------------|----------------------------------|
| Python         | 3.10+                            |
| VK API         | `vk_api` (LongPoll + VKScript)   |
| ORM            | SQLAlchemy 2.0                   |
| Конфигурация   | `python-dotenv` + `dataclass`    |
| БД             | SQLite (по умолчанию) / Postgres |
| Логирование    | `logging`                        |

## 📁 Структура

```
vinder-vk-bot/
├── .env.example
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── config.py             # Settings: VK_TOKEN, VK_GROUP_ID, DATABASE_URL
├── models.py             # BotUser, ViewedProfile, BlackList
├── database.py           # engine, SessionLocal, CRUD
├── vk_client.py          # VKClient: users.search, photos.getAll, vk.execute
├── bot.py                # VkBotLongPoll + хэндлеры
├── tests/
└── README.md
```

## 🗄 Схема БД

```mermaid
erDiagram
    BOT_USERS ||--o{ VIEWED_PROFILES : "смотрит"
    BOT_USERS ||--o{ BLACKLIST       : "блокирует"

    BOT_USERS {
        int     id          PK
        int     vk_id       UK
        string  city
        int     age_from
        int     age_to
        int     gender
    }
    VIEWED_PROFILES {
        int      id              PK
        int      bot_user_id     FK
        int      candidate_vk_id
        bool     is_favorited
        datetime viewed_at
    }
    BLACKLIST {
        int      id                     PK
        int      bot_user_id            FK
        int      blocked_candidate_vk_id
        datetime added_at
    }
```

## 🚀 Установка и запуск

### 1. Подготовить сообщество ВК

1. Создай группу ВК (или используй существующую).
2. Управление группой → **Сообщения** → включить «Сообщения сообщества».
3. Управление группой → **Работа с API** → **Long Poll API** → включить.
4. Там же, **Типы событий** → отметить:
    - **Входящие сообщения** (`message_new`);
    - **Действия с сообщениями** (`message_event`) — нужны для callback-кнопок.
5. Управление группой → **Настройки** → **Возможности ботов** → включить.
6. Управление группой → **Работа с API** → **Создать ключ** → получить `VK_TOKEN`.
7. ID сообщества берётся из адресной строки (`vk.com/club123456789` → `123456789`).

### 2. Клонировать и настроить окружение

```bash
git clone https://github.com/your-username/vinder-vk-bot.git
cd vinder-vk-bot
python -m venv .venv
source .venv/bin/activate       # Linux/macOS
# .venv\Scripts\activate        # Windows

pip install -r requirements.txt
cp .env.example .env
```

Заполни `.env`:

```dotenv
VK_TOKEN=vk1.a.your-community-token
VK_GROUP_ID=123456789
DATABASE_URL=postgresql+psycopg2://vinder_user:strong_password@localhost:5432/vinder
```

Если используешь PostgreSQL, не забудь `pip install psycopg2-binary`.

### 3. Запустить

```bash
python bot.py
```

В логе появится:
```
INFO | vinder-vk-bot | VK bot started (group_id=123456789)
```

Напиши сообществу в ЛС «начать» — бот ответит приветствием и покажет первого кандидата.

## 🤖 Функционал

| Команда / кнопка        | Что делает                                          |
|-------------------------|-----------------------------------------------------|
| `/start`                | Регистрация + первый кандидат                       |
| `/settings`             | Диалог настройки города / возраста / пола           |
| ➡️ **Следующий**         | Следующий кандидат (offset из БД)                   |
| ❤️ **Нравится**          | В избранное + следующий                             |
| 🚫 **В чёрный список**   | В ЧС + следующий                                    |
| `/favorites`            | Список избранных                                    |
| `/blacklist`            | Текущий ЧС                                          |
| `/cancel`               | Отменить диалог настройки                           |

## ⚡ Как решён лимит VK в 1000

`users.search` отдаёт максимум 1000 записей на одну комбинацию фильтров.
Мы обходим это через `vk.execute`: разбиваем возрастной диапазон на
поддиапазоны шириной в 1 год и делаем отдельный `users.search` для каждого.
Так как фильтры уникальны, у каждого свой счётчик в 1000. На диапазоне
`18–30` доступно до **13 000** кандидатов вместо 1000.

## ✅ Тесты

```bash
pip install -r requirements-dev.txt
pytest
```

Покрыто:
- `test_config.py` — Settings читает env, падает с понятной ошибкой.
- `test_database.py` — CRUD, идемпотентность, изоляция ЧС между юзерами.
- `test_vk_client.py` — логика полов, разбиение возраста, лучший URL фото,
  обычный поиск, обход лимита через `execute`, обработка `ApiError`.

## 📝 Лицензия

MIT.