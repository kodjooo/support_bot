# Техническое задание: Telegram-чатбот с OpenAI Assistant на Python
**Версия 2.1**

---

## 1. Общее описание системы

Система представляет собой Telegram-бота, который:
- Принимает сообщения от пользователей (текст, фото, документы-изображения)
- Накапливает сообщения в буфер, ожидая паузы в печати (3–5 секунд — дебаунс)
- После паузы отправляет накопленный контекст (текст + изображения) в OpenAI Assistants API
- Поддерживает непрерывный диалог через OpenAI Threads (история переписки сохраняется между сессиями)
- При необходимости переводит пользователя на оператора-человека через OpenAI Function Calling
- Очищает ответ от markdown-артефактов перед отправкой
- Показывает индикатор "бот печатает..." пока ждёт ответ от OpenAI

### Важно об архитектуре

Оригинальная система в Make состояла из трёх отдельных сценариев, соединённых HTTP-вебхуками — это было вынужденное ограничение платформы. В Python весь бот — **один процесс**. Никаких HTTP-вызовов между частями нет. Роль "вебхуков" выполняет `asyncio`: таймер дебаунса и вызов функции обработки — это просто `await asyncio.sleep(11)` внутри одной корутины.

### Схема потока данных

```
Telegram Update
    ↓
[Handler] Классифицировать сообщение
    │
    ├─ Фото достаточного размера → сохранить file_id в буфер
    ├─ Фото слишком маленькое   → ответ пользователю + уведомить оператора → СТОП
    ├─ Документ-изображение     → сохранить file_id в буфер
    ├─ Текст                    → сохранить текст в буфер
    └─ Прочее (видео, аудио…)   → ответ пользователю + уведомить оператора → СТОП
    ↓
Обновить last_update в БД
Сбросить старый таймер → asyncio.sleep(DEBOUNCE_DELAY)
    ↓ (через 11 секунд без новых сообщений)
[Processor] async with user_lock:
    Прочитать буфер из БД
    Получить URL картинок по file_id (на лету, не хранить)
    Если картинок > MAX_IMAGES → перевести на оператора → СТОП
    Собрать текст из буфера
    Показать "бот печатает..."
    Если thread_id есть → добавить в существующий тред OpenAI
    Если нет → создать новый тред, сохранить thread_id
    Получить ответ от OpenAI Assistant
    Если ответ = вызов transfer_to_operator() → перевести на оператора
    Иначе → очистить текст от артефактов → отправить пользователю
    Очистить буфер (texts + image_ids) в БД
```

---

## 2. Функциональные требования

### 2.1. Приём и классификация сообщений

Бот обрабатывает только **личные сообщения** (private chat). Группы и каналы игнорируются.

#### 2.1.1. Типы сообщений

| Тип | Условие | Действие |
|-----|---------|----------|
| **Фото (нормальное)** | `message.photo` не пустой И наибольшее фото (`photo[-1]`) шире 800px | Сохранить `file_id` наибольшего фото в `image_ids` буфера |
| **Фото (маленькое)** | `message.photo` не пустой НО `photo[-1].width < 800` | Ответить пользователю, уведомить оператора, не сохранять |
| **Документ-изображение** | `message.document` существует И `mime_type` начинается с `"image/"` | Сохранить `file_id` документа в `image_ids` буфера |
| **Текст** | `message.text` существует | Сохранить текст в `texts` буфера |
| **Прочее** | Всё остальное | Ответить пользователю, уведомить оператора, не сохранять |

> **Примечание про альбомы:** Когда пользователь отправляет несколько фото одновременно (альбом), Telegram присылает их как отдельные обновления с одинаковым `media_group_id`. Механизм дебаунса автоматически решает это: каждое фото альбома сохраняется отдельным `file_id` в буфер, а обрабатываются все вместе после 11-секундной паузы. Специальной обработки `media_group_id` не требуется.

#### 2.1.2. Сохранение в буфер

Запись в таблицу `users` (ключ = `user_id`):

```python
# texts и image_ids — дополняются (append), а не перезаписываются
db.upsert(
    user_id=user_id,
    first_name=first_name,
    last_name=last_name,
    texts=record.texts + [new_text],           # добавляем к существующим
    image_ids=record.image_ids + [new_file_id], # добавляем к существующим
    last_update=int(time.time())
)
```

> **Важно:** В буфере хранятся только `file_id` — идентификаторы файлов Telegram, **не URL**. URL с токеном бота строится на лету непосредственно перед передачей в OpenAI и нигде не сохраняется (безопасность токена).

#### 2.1.3. Запуск дебаунса

После сохранения в буфер — запустить (или перезапустить) таймер дебаунса:

```python
async def debounce(user_id: str):
    """Сброс и перезапуск таймера при каждом новом сообщении."""
    if user_id in _timers:
        _timers[user_id].cancel()

    async def _run():
        await asyncio.sleep(DEBOUNCE_DELAY)  # 3–5 секунд, настраивается
        await process_and_reply(user_id)

    _timers[user_id] = asyncio.create_task(_run())
```

---

### 2.2. Обработка и ответ (запускается после дебаунса)

Вся обработка выполняется под `asyncio.Lock` на `user_id`, чтобы один пользователь не мог запустить два параллельных запроса к OpenAI.

#### 2.2.1. Проверка TTL буфера

Перед обработкой проверить актуальность буфера:

```python
MAX_BUFFER_AGE = 3600  # 1 час

record = db.get(user_id)
if not record or time.time() - record.last_update > MAX_BUFFER_AGE:
    db.clear_buffer(user_id)
    return  # сессия устарела, игнорируем
```

#### 2.2.2. Маршрутизация по изображениям

```python
images = record.image_ids

if len(images) > MAX_IMAGES:  # настраивается через конфиг, по умолчанию 10
    await transfer_to_operator(user_id, first_name, last_name)
    db.clear_buffer(user_id)
    return

# Строим URL на лету — токен не хранится в БД
image_urls = []
for file_id in images:
    file = await bot.get_file(file_id)
    image_urls.append(f"https://api.telegram.org/file/bot{TOKEN}/{file.file_path}")
```

#### 2.2.3. Индикатор "бот печатает..."

Пока OpenAI обрабатывает запрос (может занять 5–30 секунд), непрерывно отправлять `typing`:

```python
async def keep_typing(chat_id: str, stop_event: asyncio.Event):
    while not stop_event.is_set():
        await bot.send_chat_action(chat_id=chat_id, action="typing")
        await asyncio.sleep(4)  # typing-действие длится 5 сек, обновляем с запасом

stop = asyncio.Event()
typing_task = asyncio.create_task(keep_typing(user_id, stop))
try:
    response = await call_openai_assistant(...)
finally:
    stop.set()
    await typing_task
```

#### 2.2.4. Управление диалогом (OpenAI Threads)

**Первое обращение** (`thread_id` = NULL в БД):
```python
thread = await openai_client.beta.threads.create()
thread_id = thread.id
db.update(user_id, thread_id=thread_id)  # сохраняем для следующих обращений
```

**Повторное обращение** (`thread_id` есть в БД):
```python
thread_id = record.thread_id  # берём сохранённый
```

**Общая часть — добавить сообщение и запустить Run:**
```python
combined_text = "\n".join(record.texts)

# Формируем content с текстом и картинками
content = [{"type": "text", "text": combined_text}]
for url in image_urls:
    content.append({"type": "image_url", "image_url": {"url": url}})

await openai_client.beta.threads.messages.create(
    thread_id=thread_id,
    role="user",
    content=content
)

run = await openai_client.beta.threads.runs.create_and_poll(
    thread_id=thread_id,
    assistant_id=ASSISTANT_ID,
    tools=OPERATOR_TOOLS,  # см. раздел 2.2.5
    timeout=60
)
```

**Тайм-аут:** Если Run не завершился за 60 секунд — отменить Run и перевести на оператора.

#### 2.2.5. Детектирование необходимости оператора — Function Calling

Вместо текстового маркера используется OpenAI Function Calling. Ассистент сам вызывает функцию, когда считает нужным.

Определение инструмента (передаётся при создании Run):
```python
OPERATOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "transfer_to_operator",
            "description": (
                "Вызвать эту функцию, когда вопрос пользователя выходит за рамки "
                "компетенции ассистента и требует участия живого оператора."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    }
]
```

Обработка ответа:
```python
if run.status == "requires_action":
    # Ассистент вызвал transfer_to_operator()
    tool_calls = run.required_action.submit_tool_outputs.tool_calls
    if any(tc.function.name == "transfer_to_operator" for tc in tool_calls):
        await transfer_to_operator(user_id, first_name, last_name)
        db.clear_buffer(user_id)
        return

elif run.status == "completed":
    messages = await openai_client.beta.threads.messages.list(thread_id=thread_id)
    raw_text = messages.data[0].content[0].text.value
    cleaned = clean_response(raw_text)
    await bot.send_message(chat_id=user_id, text=cleaned)
    db.clear_buffer(user_id)

else:
    # completed_with_error, expired, cancelled, failed
    await transfer_to_operator(user_id, first_name, last_name)
    db.clear_buffer(user_id)
```

#### 2.2.6. Перевод на оператора

```python
async def transfer_to_operator(user_id: str, first_name: str, last_name: str):
    await bot.send_message(
        chat_id=user_id,
        text=f"Зову оператора {OPERATOR_NAME}"
    )
    await bot.send_message(
        chat_id=OPERATOR_CHAT_ID,
        text=f"{first_name} {last_name} просит подключиться к его чату!"
    )
```

#### 2.2.7. Очистка ответа от артефактов

```python
import re

def clean_response(text: str) -> str:
    """
    Убирает Markdown-форматирование и citation-ссылки OpenAI Assistants.
    Использует is not None вместо or, чтобы корректно обрабатывать пустые группы.
    """
    pattern = (
        r'\*\*(.*?)\*\*'         # **жирный**
        r'|__(.*?)__'             # __курсив__
        r'|~~(.*?)~~'            # ~~зачёркнутый~~
        r'|\[.*?†source\]'       # [text†source]
        r'|【\d+:\d+†source】'  # 【1:2†source】
        r'|【\d+†source】'       # 【1†source】
    )

    def replacer(m: re.Match) -> str:
        for i in range(1, 4):
            if m.group(i) is not None:
                return m.group(i)
        return ""

    return re.sub(pattern, replacer, text)
```

---

## 3. Хранилище данных

Одна таблица SQLite вместо двух DataStore из Make. Redis — опция для многосерверного деплоя.

### 3.1. Таблица `users`

```sql
CREATE TABLE IF NOT EXISTS users (
    user_id         TEXT PRIMARY KEY,
    first_name      TEXT,
    last_name       TEXT,
    thread_id       TEXT,        -- OpenAI Thread ID; NULL = новый диалог
    texts_json      TEXT,        -- JSON-массив строк (буфер текстов)
    image_ids_json  TEXT,        -- JSON-массив file_id (НЕ URL!)
    last_update     INTEGER      -- Unix timestamp; используется для TTL
);
```

> Поля `locked_at` и `processing` из оригинала — **убраны**. Защита от параллельных запросов реализована через `asyncio.Lock` в памяти процесса.

### 3.2. Блокировки (в памяти)

```python
_user_locks: dict[str, asyncio.Lock] = {}

def get_lock(user_id: str) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]

# Использование:
async with get_lock(user_id):
    await process_and_reply(user_id)
```

### 3.3. TTL и восстановление при рестарте

- Записи старше `MAX_BUFFER_AGE = 3600` секунд считаются устаревшими и удаляются при попытке обработки.
- `thread_id` при этом **не удаляется** — история диалога с ассистентом сохраняется. Очищается только буфер (`texts_json`, `image_ids_json`, `last_update`).
- При рестарте бота таймеры дебаунса (хранятся только в памяти) теряются. Для данного бота это приемлемо: пользователь просто повторит сообщение. Если неприемлемо — добавить восстановление: при старте читать все записи с `last_update < 60` секунд назад и перезапускать для них таймеры.

---

## 4. Сообщения бота

| Ситуация | Текст пользователю |
|---------|-------------------|
| Фото слишком маленькое | "Пожалуйста, загрузите фотографию большего размера — в текущем виде сложно оценить информацию. После этого повторите, пожалуйста, свой вопрос." |
| Неизвестный формат вложения | `"Человек с большей вероятностью вам поможет. Зову оператора."` |
| Перевод на оператора (ИИ решил) | `"Зову оператора {OPERATOR_NAME}"` |

**Уведомление оператору** (chat_id из `OPERATOR_CHAT_ID`):
`"{first_name} {last_name} просит подключиться к его чату!"`

---

## 5. Стек технологий

| Компонент | Решение | Библиотека |
|-----------|---------|------------|
| Telegram Bot | polling или webhook | `aiogram` v3 (рекомендуется) или `python-telegram-bot` v20+ |
| БД (основная) | SQLite | `aiosqlite` |
| БД (multi-server) | Redis | `redis-py` с `asyncio` |
| OpenAI | Assistants API v2 | `openai` >= 1.30 |
| Конфигурация | `.env` | `pydantic-settings` |
| Запуск (webhook) | ASGI-сервер | `uvicorn` + `FastAPI` |

---

## 6. Структура проекта

```
chatbot/
├── main.py                 # Точка входа: запуск бота (polling или webhook)
├── config.py               # Настройки через pydantic-settings + .env
├── bot/
│   ├── handlers.py         # Обработчики входящих сообщений Telegram
│   ├── debounce.py         # asyncio-дебаунс и таймеры
│   └── processor.py        # Основная логика обработки после дебаунса
├── storage/
│   └── db.py               # Единая точка работы с БД (users table)
├── ai/
│   ├── assistant.py        # Работа с OpenAI Assistants API + Function Calling
│   └── cleaner.py          # clean_response() — очистка от артефактов
├── utils/
│   └── telegram.py         # get_image_url(), keep_typing()
├── requirements.txt
└── .env.example
```

---

## 7. Конфигурация (.env)

```env
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
OPENAI_API_KEY=sk-...
OPENAI_ASSISTANT_ID=your-assistant-id

OPERATOR_CHAT_ID=your-operator-chat-id
OPERATOR_NAME=Имя оператора

DATABASE_PATH=./chatbot.db      # путь к SQLite-файлу
# REDIS_URL=redis://localhost:6379/0  # раскомментировать для Redis

DEBOUNCE_DELAY=4                # секунд ожидания паузы (рекомендуется 3–5)
MAX_BUFFER_AGE=3600             # секунд до устаревания буфера
MAX_IMAGES=10                   # максимум картинок за одну сессию
MIN_PHOTO_WIDTH=800             # минимальная ширина фото в пикселях
OPENAI_RUN_TIMEOUT=60           # секунд ожидания ответа от OpenAI

# Для webhook-режима (опционально):
WEBHOOK_HOST=https://your-server.com
WEBHOOK_PORT=8443
WEBHOOK_SECRET=your-secret-token
```

---

## 8. Граничные случаи и требования к надёжности

| Ситуация | Поведение |
|---------|-----------|
| Пользователь шлёт несколько сообщений подряд | Таймер сбрасывается каждый раз; обработка — только после 11-секундной паузы |
| Пользователь шлёт альбом фото | Каждое фото альбома накапливается в буфер; обрабатываются все вместе после паузы |
| Больше `MAX_IMAGES` картинок в буфере | Перевод на оператора, очистка буфера |
| OpenAI не ответил за 60 сек | Отменить Run, перевести на оператора |
| OpenAI вернул ошибку / статус failed | Перевести на оператора |
| Запись в буфере старше 1 часа | Считать устаревшей, очистить буфер (thread_id сохранить) |
| Бот перезапущен во время дебаунса | Таймеры теряются; пользователь повторяет сообщение (приемлемо) |
| Параллельные запросы от одного пользователя | `asyncio.Lock` гарантирует последовательную обработку |

---

## 9. Этапы реализации

1. Настройка проекта: структура папок, `config.py`, `.env`
2. Инициализация SQLite (`storage/db.py`): создание таблицы `users`, CRUD-функции
3. Обработчики Telegram (`bot/handlers.py`): классификация, сохранение в буфер
4. Дебаунс (`bot/debounce.py`): asyncio-таймеры с отменой
5. Получение URL картинок на лету (`utils/telegram.py`)
6. Интеграция OpenAI Assistant (`ai/assistant.py`): Threads, Function Calling, тайм-аут
7. Очистка ответа (`ai/cleaner.py`)
8. Индикатор "бот печатает..." (`utils/telegram.py`)
9. Логика перевода на оператора (`bot/processor.py`)
10. Тестирование: текст, фото, альбом, несколько сообщений подряд, тайм-аут OpenAI, перевод на оператора
11. Деплой на сервер (systemd или Docker)

---

*Версия 2.1 — финальная. Полностью независима от платформы Make.com: единый Python-процесс, одна таблица БД, asyncio.Lock, Function Calling, безопасное хранение file_id вместо URL с токеном, все параметры вынесены в конфиг.*
