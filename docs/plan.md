# План реализации Telegram Support Bot

## Условия запуска
Проект запускается **только через Docker Desktop** (`docker compose up`). Локальное Python-окружение не используется.

---

## Этап 1. Структура проекта и конфигурация — выполнено

**Цель:** подготовить скелет приложения, настройки и Docker-инфраструктуру.

### Задачи:
- [ ] Создать структуру папок внутри `app/`:
  ```
  app/
  ├── __init__.py
  ├── main.py
  ├── config.py
  ├── bot/
  │   ├── __init__.py
  │   ├── handlers.py
  │   ├── debounce.py
  │   └── processor.py
  ├── storage/
  │   ├── __init__.py
  │   └── db.py
  ├── ai/
  │   ├── __init__.py
  │   ├── assistant.py
  │   └── cleaner.py
  └── utils/
      ├── __init__.py
      └── telegram.py
  ```
- [ ] Написать `app/config.py` — загрузка всех переменных из `.env` через `pydantic-settings`
- [ ] Обновить `.env.example` с комментариями (где получить каждый токен)
- [ ] Создать `.env` на базе `.env.example`
- [ ] Заполнить `requirements.txt`:
  - `aiogram>=3.7`
  - `openai>=1.30`
  - `aiosqlite>=0.20`
  - `pydantic-settings>=2.0`
- [ ] Создать `docker-compose.yml` с сервисом `bot` (volume для SQLite-файла)
- [ ] Проверить, что `docker compose build` проходит без ошибок

---

## Этап 2. Хранилище данных (SQLite) — выполнено

**Цель:** реализовать `storage/db.py` — единственную точку работы с БД.

### Задачи:
- [ ] Создать и инициализировать таблицу `users` при старте
- [ ] Реализовать функции:
  - `get_user(user_id)` — получить запись
  - `upsert_user(user_id, first_name, last_name, texts, image_ids, last_update)` — создать/обновить буфер
  - `save_thread_id(user_id, thread_id)` — сохранить OpenAI Thread ID
  - `clear_buffer(user_id)` — очистить `texts_json`, `image_ids_json`, `last_update` (thread_id сохранить)
- [ ] Покрыть функции тестами в `tests/test_db.py`

---

## Этап 3. Обработчики входящих сообщений Telegram — выполнено

**Цель:** реализовать `bot/handlers.py` — классификация и сохранение в буфер.

### Задачи:
- [ ] Подключить router aiogram, обрабатывать только `private` чаты
- [ ] Обработчик текстовых сообщений → `upsert` + дебаунс
- [ ] Обработчик фото:
  - нормальное (width ≥ `MIN_PHOTO_WIDTH`) → `upsert` + дебаунс
  - маленькое → ответ пользователю + уведомление оператора
- [ ] Обработчик документов-изображений (`mime_type` начинается с `image/`) → `upsert` + дебаунс
- [ ] Обработчик прочих типов (видео, аудио и т.д.) → ответ + уведомление оператора
- [ ] Тесты в `tests/test_handlers.py` (mock bot, mock db)

---

## Этап 4. Дебаунс — выполнено

**Цель:** реализовать `bot/debounce.py` — asyncio-таймеры с отменой.

### Задачи:
- [ ] Словарь `_timers: dict[str, asyncio.Task]`
- [ ] Функция `debounce(user_id, callback)` — отмена старого таймера, создание нового с `DEBOUNCE_DELAY`
- [ ] Тесты в `tests/test_debounce.py` — проверка, что повторный вызов сбрасывает таймер

---

## Этап 5. Вспомогательные утилиты Telegram — выполнено

**Цель:** реализовать `utils/telegram.py`.

### Задачи:
- [ ] `get_image_url(bot, file_id)` — получить `file_path` через `bot.get_file()` и вернуть URL (токен не сохраняется)
- [ ] `keep_typing(bot, chat_id, stop_event)` — корутина, шлёт `typing` каждые 4 сек до `stop_event`

---

## Этап 6. Интеграция OpenAI Assistants API — выполнено

**Цель:** реализовать `ai/assistant.py` — Threads, Function Calling, тайм-аут.

### Задачи:
- [ ] Определить `OPERATOR_TOOLS` (function calling: `transfer_to_operator`)
- [ ] Функция `call_assistant(thread_id, texts, image_urls)`:
  - создать Thread если `thread_id` = None
  - добавить message с текстом + image_url
  - запустить `runs.create_and_poll` с `timeout=OPENAI_RUN_TIMEOUT`
  - обработать статусы: `completed`, `requires_action`, прочие → бросить исключение
- [ ] Вернуть `(response_text | None, needs_operator: bool, new_thread_id)`
- [ ] Тесты в `tests/test_assistant.py` (mock openai client)

---

## Этап 7. Очистка ответа от артефактов — выполнено

**Цель:** реализовать `ai/cleaner.py`.

### Задачи:
- [ ] Функция `clean_response(text)` — убрать Markdown-форматирование и citation-ссылки OpenAI
- [ ] Тесты в `tests/test_cleaner.py` — проверить все паттерны (`**bold**`, `【1:2†source】` и т.д.)

---

## Этап 8. Основная логика обработки (processor) — выполнено

**Цель:** реализовать `bot/processor.py` — оркестрация всех компонентов после дебаунса.

### Задачи:
- [ ] Словарь `_user_locks: dict[str, asyncio.Lock]` + `get_lock(user_id)`
- [ ] Функция `process_and_reply(bot, user_id)`:
  1. Получить запись из БД, проверить TTL (`MAX_BUFFER_AGE`)
  2. Проверить кол-во изображений (`MAX_IMAGES`)
  3. Получить URL изображений на лету
  4. Запустить `keep_typing` в фоне
  5. Вызвать `call_assistant(...)`, сохранить `thread_id` если новый
  6. Остановить `keep_typing`
  7. Если нужен оператор → `transfer_to_operator`
  8. Иначе → `clean_response` → `bot.send_message`
  9. Очистить буфер
- [ ] Функция `transfer_to_operator(bot, user_id, first_name, last_name)`
- [ ] Тесты в `tests/test_processor.py`

---

## Этап 9. Точка входа — выполнено

**Цель:** реализовать `app/main.py` — запуск бота.

### Задачи:
- [ ] Инициализировать БД (`await db.init()`)
- [ ] Создать `Bot` и `Dispatcher` aiogram
- [ ] Подключить router из `handlers.py`
- [ ] Запустить polling (`dp.start_polling(bot)`)

---

## Этап 10. Docker Compose и финальная проверка — выполнено

**Цель:** убедиться, что всё работает в Docker Desktop.

### Задачи:
- [ ] Финализировать `docker-compose.yml`:
  - сервис `bot`
  - volume `bot_data` примонтирован в `/app/data` для SQLite
  - `env_file: .env`
  - `restart: unless-stopped`
- [ ] Убедиться, что `DATABASE_PATH` в `.env` указывает на `/app/data/chatbot.db`
- [ ] Проверить `docker compose up --build` — бот стартует без ошибок
- [ ] Проверить `.dockerignore` — `.env` не попадает в образ
- [ ] Обновить `docs/architecture.md`

---

## Этап 11. Интеграционное тестирование — выполнено

**Цель:** проверить все сценарии работы бота вручную.

### Сценарии:
- [ ] Обычный текстовый вопрос → ответ от ассистента
- [ ] Несколько сообщений подряд → дебаунс срабатывает один раз
- [ ] Фото нормального размера → обрабатывается
- [ ] Фото маленького размера → сообщение пользователю + уведомление оператора
- [ ] Альбом из нескольких фото → все обрабатываются вместе
- [ ] Документ-изображение → обрабатывается
- [ ] Видео → уведомление оператора
- [ ] Вопрос, требующий оператора (ассистент вызывает `transfer_to_operator`) → уведомление
- [ ] Тайм-аут OpenAI (>60 сек) → уведомление оператора
- [ ] Буфер старше 1 часа → игнорируется

---

## Этап 12. Публикация в GitHub

**Цель:** запушить финальную версию в репозиторий.

### Задачи:
- [ ] Проверить `.gitignore` — `.env` исключён
- [ ] Обновить `README.md` — инструкция по запуску через Docker Desktop
- [ ] `git push` в ветку `main` репозитория `https://github.com/kodjooo/support_bot.git`
