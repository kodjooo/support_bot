# Support Bot — Telegram-бот с OpenAI Assistant

Telegram-бот поддержки: принимает сообщения пользователей (текст, фото, документы-изображения), накапливает их через дебаунс и отправляет в OpenAI Assistants API. При необходимости переключает на оператора-человека.

## Требования

- Docker Desktop (единственный способ запуска)
- Telegram-бот (создать через [@BotFather](https://t.me/BotFather))
- OpenAI API ключ и ассистент (создать на [platform.openai.com/assistants](https://platform.openai.com/assistants))

## Быстрый старт

**1. Клонировать репозиторий:**
```bash
git clone https://github.com/kodjooo/support_bot.git
cd support_bot
```

**2. Создать файл `.env` из шаблона:**
```bash
cp .env.example .env
```

**3. Заполнить `.env`** — вставить токены и ID (комментарии в файле объясняют где что взять).

**4. Собрать и запустить:**
```bash
docker compose up --build
```

Бот запустится в режиме polling. Данные SQLite сохраняются в Docker volume `bot_data`.

## Остановка

```bash
docker compose down
```

## Структура проекта

```
app/
├── main.py          # Точка входа
├── config.py        # Настройки из .env
├── bot/
│   ├── handlers.py  # Классификация входящих сообщений
│   ├── debounce.py  # Таймер ожидания паузы
│   └── processor.py # Оркестрация обработки
├── storage/
│   └── db.py        # SQLite (таблица users)
├── ai/
│   ├── assistant.py # OpenAI Assistants API
│   └── cleaner.py   # Очистка ответа от артефактов
└── utils/
    └── telegram.py  # URL изображений, индикатор печати
```

## Деплой на удалённый сервер

**Требования на сервере:** Docker + Docker Compose (v2).

```bash
# 1. Установить Docker (Ubuntu/Debian)
curl -fsSL https://get.docker.com | sh

# 2. Клонировать репозиторий
git clone https://github.com/kodjooo/support_bot.git
cd support_bot

# 3. Создать и заполнить .env
cp .env.example .env
nano .env

# 4. Запустить в фоне
docker compose up -d --build

# 5. Просмотр логов
docker compose logs -f
```

Для автозапуска при перезагрузке сервера директива `restart: unless-stopped` в `docker-compose.yml` уже настроена.
