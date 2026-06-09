# Архитектура проекта Support Bot

## Общее описание

Telegram-бот на Python с интеграцией OpenAI Assistants API. Единый асинхронный процесс на `aiogram` v3. Запускается **только через Docker Desktop** (`docker compose up`).

---

## Структура проекта

```
support-bot/
├── app/
│   ├── main.py              # Точка входа: инициализация и запуск polling
│   ├── config.py            # Настройки через pydantic-settings + .env
│   ├── bot/
│   │   ├── handlers.py      # Обработчики входящих сообщений Telegram
│   │   ├── debounce.py      # asyncio-дебаунс с отменой таймеров
│   │   └── processor.py     # Оркестрация обработки после дебаунса
│   ├── storage/
│   │   └── db.py            # CRUD для таблицы users (aiosqlite)
│   ├── ai/
│   │   ├── assistant.py     # OpenAI Assistants API: Threads, Function Calling
│   │   └── cleaner.py       # Очистка ответа от Markdown-артефактов
│   └── utils/
│       └── telegram.py      # get_image_url(), keep_typing()
├── tests/                   # pytest-тесты (не попадают в Docker-образ)
├── docs/
│   ├── requirements.md
│   ├── arch-rules.md
│   ├── architecture.md      # этот файл
│   └── plan.md
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env                     # локальные секреты (не в git)
└── .env.example             # шаблон переменных окружения
```

---

## Компоненты

### config.py
Загружает все переменные из `.env` через `pydantic-settings`. Единый объект `settings` импортируется везде.

**Переменные:**
- `TELEGRAM_BOT_TOKEN` — токен бота
- `OPENAI_API_KEY`, `OPENAI_ASSISTANT_ID` — OpenAI
- `OPERATOR_CHAT_ID`, `OPERATOR_NAME` — оператор
- `DATABASE_PATH` — путь к SQLite (внутри контейнера: `./data/chatbot.db`)
- `DEBOUNCE_DELAY`, `MAX_BUFFER_AGE`, `MAX_IMAGES`, `MIN_PHOTO_WIDTH`, `OPENAI_RUN_TIMEOUT` — поведенческие параметры

### storage/db.py *(этап 2)*
SQLite через `aiosqlite`. Одна таблица `users`.

### bot/handlers.py *(этап 3)*
Router aiogram. Классифицирует входящие сообщения, сохраняет в буфер, запускает дебаунс.

### bot/debounce.py *(этап 4)*
Словарь asyncio-задач. При каждом новом сообщении сбрасывает таймер пользователя.

### utils/telegram.py *(этап 5)*
`get_image_url()` — строит URL на лету (токен не хранится в БД).  
`keep_typing()` — корутина-индикатор "бот печатает...".

### ai/assistant.py *(этап 6)*
Работа с OpenAI Assistants API: создание/переиспользование Threads, отправка сообщений, обработка Function Calling (`transfer_to_operator`), тайм-аут Run.

### ai/cleaner.py *(этап 7)*
`clean_response()` — убирает `**bold**`, `__italic__`, `~~strike~~`, citation-ссылки `【N:M†source】`.

### bot/processor.py *(этап 8)*
Оркестрация: asyncio.Lock на user_id → TTL-проверка → URL изображений → keep_typing → OpenAI → очистка → ответ или оператор.

### app/main.py *(этап 9)*
Инициализация БД, создание Bot и Dispatcher, подключение router, запуск `dp.start_polling(bot)`.

---

## Поток данных

```
Telegram Update
    ↓
handlers.py — классификация сообщения
    ↓
storage/db.py — upsert буфера (texts + image_ids)
    ↓
debounce.py — сброс/перезапуск asyncio-таймера
    ↓ (через DEBOUNCE_DELAY секунд без новых сообщений)
processor.py — asyncio.Lock(user_id)
    ├─ TTL-проверка буфера
    ├─ проверка MAX_IMAGES
    ├─ utils/telegram.py → get_image_url() на лету
    ├─ utils/telegram.py → keep_typing() в фоне
    ├─ ai/assistant.py → OpenAI Assistants API
    │   ├─ requires_action → transfer_to_operator
    │   ├─ completed → ai/cleaner.py → bot.send_message
    │   └─ прочие статусы → transfer_to_operator
    └─ storage/db.py → clear_buffer()
```

---

## Docker

- **Dockerfile** — образ `python:3.12-slim`, копирует только `app/` и `requirements.txt`
- **docker-compose.yml** — сервис `bot`, volume `bot_data` → `/app/data` (SQLite), `env_file: .env`
- **`.dockerignore`** — исключает `.env`, `.git`, `tests/`, `__pycache__`

---

## Статус реализации

| Этап | Компонент | Статус |
|------|-----------|--------|
| 1 | Структура, config.py, docker-compose.yml | ✅ выполнено |
| 2 | storage/db.py | ✅ выполнено |
| 3 | bot/handlers.py | ✅ выполнено |
| 4 | bot/debounce.py | ✅ выполнено |
| 5 | utils/telegram.py | ✅ выполнено |
| 6 | ai/assistant.py | ✅ выполнено |
| 7 | ai/cleaner.py | ✅ выполнено |
| 8 | bot/processor.py | ✅ выполнено |
| 9 | app/main.py | ✅ выполнено |
| 10 | Docker финализация | ✅ выполнено |
| 11 | Интеграционное тестирование | ✅ выполнено |
| 12 | GitHub | ✅ выполнено |
