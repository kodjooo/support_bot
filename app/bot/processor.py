import asyncio

from aiogram import Bot

from app.storage import db
from app.config import settings

# asyncio.Lock на каждого пользователя
_user_locks: dict[str, asyncio.Lock] = {}


def get_lock(user_id: str) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


async def transfer_to_operator(bot: Bot, user_id: str, first_name: str, last_name: str) -> None:
    """Уведомляет пользователя и оператора о переключении на человека."""
    await bot.send_message(
        chat_id=user_id,
        text=f"Зову оператора {settings.operator_name}",
    )
    await bot.send_message(
        chat_id=settings.operator_chat_id,
        text=f"{first_name} {last_name} просит подключиться к его чату!",
    )


async def process_and_reply(bot: Bot, user_id: str) -> None:
    """Основная логика обработки после дебаунса."""
    async with get_lock(user_id):
        import time

        record = await db.get_user(user_id)
        if not record:
            return

        # TTL-проверка буфера
        if time.time() - record.last_update > settings.max_buffer_age:
            await db.clear_buffer(user_id)
            return

        # Импорт здесь — избегаем циклического импорта на старте
        from app.utils.telegram import get_image_url, keep_typing
        from app.ai.assistant import call_assistant
        from app.ai.cleaner import clean_response
        from app.ai.vector_client import fetch_context

        # Проверка количества изображений
        if len(record.image_ids) > settings.max_images:
            await transfer_to_operator(bot, user_id, record.first_name, record.last_name)
            await db.clear_buffer(user_id)
            return

        # URL изображений — строятся на лету, токен не хранится в БД
        image_urls = []
        for file_id in record.image_ids:
            url = await get_image_url(bot, file_id)
            image_urls.append(url)

        # Запрос релевантных чанков из векторной базы знаний
        user_query = "\n".join(record.texts)
        context_chunks = await fetch_context(user_query)
        if context_chunks:
            context_prefix = "Контекст из базы знаний:\n" + "\n\n".join(context_chunks)
            texts = [context_prefix] + record.texts
        else:
            texts = record.texts

        # Индикатор "бот печатает..."
        stop_event = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(bot, user_id, stop_event))

        try:
            response_text, needs_operator, new_response_id = await call_assistant(
                last_response_id=record.last_response_id,
                texts=texts,
                image_urls=image_urls,
            )
        except Exception:
            stop_event.set()
            await typing_task
            await transfer_to_operator(bot, user_id, record.first_name, record.last_name)
            await db.clear_buffer(user_id)
            return

        stop_event.set()
        await typing_task

        # Сохраняем ID последнего ответа для продолжения диалога
        if new_response_id and new_response_id != record.last_response_id:
            await db.save_last_response_id(user_id, new_response_id)

        if needs_operator:
            await transfer_to_operator(bot, user_id, record.first_name, record.last_name)
        else:
            cleaned = clean_response(response_text or "")
            await bot.send_message(chat_id=user_id, text=cleaned)

        await db.clear_buffer(user_id)
