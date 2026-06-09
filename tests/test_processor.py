import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("OPENAI_ASSISTANT_ID", "asst_test")
os.environ.setdefault("OPERATOR_CHAT_ID", "9999")
os.environ.setdefault("OPERATOR_NAME", "Оператор")
os.environ.setdefault("DATABASE_PATH", "/tmp/test_processor.db")

import app.storage.db as db
from app.bot.processor import process_and_reply

db._db_path = "/tmp/test_processor.db"


@pytest.fixture(autouse=True)
async def clean_db():
    if os.path.exists("/tmp/test_processor.db"):
        os.remove("/tmp/test_processor.db")
    await db.init()
    yield


async def _seed(user_id: str, texts: list[str], image_ids: list[str], age: int = 0):
    """Создаёт запись в БД с заданным возрастом буфера."""
    last_update = int(time.time()) - age
    await db.upsert_user(user_id, "Иван", "Петров", texts, image_ids, last_update)


@pytest.mark.asyncio
async def test_sends_reply_on_completed():
    await _seed("1", ["вопрос"], [])
    bot = MagicMock()
    bot.get_file = AsyncMock()
    bot.send_chat_action = AsyncMock()
    bot.send_message = AsyncMock()

    with patch("app.ai.assistant.call_assistant", new_callable=AsyncMock) as mock_ai:
        mock_ai.return_value = ("Ответ ассистента", False, "thread_1")
        await process_and_reply(bot, "1")

    bot.send_message.assert_called_once()
    call_args = bot.send_message.call_args
    assert call_args.kwargs["text"] == "Ответ ассистента"

    record = await db.get_user("1")
    assert record.texts == []


@pytest.mark.asyncio
async def test_transfers_when_needs_operator():
    await _seed("2", ["вопрос"], [])
    bot = MagicMock()
    bot.get_file = AsyncMock()
    bot.send_chat_action = AsyncMock()
    bot.send_message = AsyncMock()

    with patch("app.ai.assistant.call_assistant", new_callable=AsyncMock) as mock_ai:
        mock_ai.return_value = (None, True, "thread_2")
        await process_and_reply(bot, "2")

    # send_message вызван дважды: пользователю и оператору
    assert bot.send_message.call_count == 2


@pytest.mark.asyncio
async def test_skips_stale_buffer():
    await _seed("3", ["старый вопрос"], [], age=7200)  # 2 часа назад
    bot = MagicMock()
    bot.send_message = AsyncMock()

    with patch("app.ai.assistant.call_assistant", new_callable=AsyncMock) as mock_ai:
        await process_and_reply(bot, "3")
        mock_ai.assert_not_called()

    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_transfers_on_too_many_images():
    image_ids = [f"img_{i}" for i in range(15)]
    await _seed("4", [], image_ids)
    bot = MagicMock()
    bot.send_message = AsyncMock()

    with patch("app.ai.assistant.call_assistant", new_callable=AsyncMock) as mock_ai:
        await process_and_reply(bot, "4")
        mock_ai.assert_not_called()

    # Уведомление пользователю + оператору
    assert bot.send_message.call_count == 2


@pytest.mark.asyncio
async def test_saves_new_thread_id():
    await _seed("5", ["текст"], [])
    bot = MagicMock()
    bot.get_file = AsyncMock()
    bot.send_chat_action = AsyncMock()
    bot.send_message = AsyncMock()

    with patch("app.ai.assistant.call_assistant", new_callable=AsyncMock) as mock_ai:
        mock_ai.return_value = ("ответ", False, "new_thread_id")
        await process_and_reply(bot, "5")

    record = await db.get_user("5")
    assert record.thread_id == "new_thread_id"
