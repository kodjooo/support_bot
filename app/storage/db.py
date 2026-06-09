import json
import os
import time
from dataclasses import dataclass

import aiosqlite

from app.config import settings


@dataclass
class UserRecord:
    user_id: str
    first_name: str
    last_name: str
    last_response_id: str | None  # ID последнего ответа Responses API (для цепочки диалога)
    texts: list[str]
    image_ids: list[str]
    last_update: int


_db_path: str = settings.database_path


async def init() -> None:
    """Создаёт файл БД и таблицу users при первом запуске."""
    os.makedirs(os.path.dirname(_db_path) or ".", exist_ok=True)
    async with aiosqlite.connect(_db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id             TEXT PRIMARY KEY,
                first_name          TEXT,
                last_name           TEXT,
                last_response_id    TEXT,
                texts_json          TEXT,
                image_ids_json      TEXT,
                last_update         INTEGER
            )
        """)
        await db.commit()


async def get_user(user_id: str) -> UserRecord | None:
    """Возвращает запись пользователя или None."""
    async with aiosqlite.connect(_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()

    if row is None:
        return None

    return UserRecord(
        user_id=row["user_id"],
        first_name=row["first_name"] or "",
        last_name=row["last_name"] or "",
        last_response_id=row["last_response_id"],
        texts=json.loads(row["texts_json"] or "[]"),
        image_ids=json.loads(row["image_ids_json"] or "[]"),
        last_update=row["last_update"] or 0,
    )


async def upsert_user(
    user_id: str,
    first_name: str,
    last_name: str,
    texts: list[str],
    image_ids: list[str],
    last_update: int,
) -> None:
    """Создаёт или обновляет запись. last_response_id не трогает."""
    async with aiosqlite.connect(_db_path) as db:
        await db.execute(
            """
            INSERT INTO users (user_id, first_name, last_name, texts_json, image_ids_json, last_update)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                first_name      = excluded.first_name,
                last_name       = excluded.last_name,
                texts_json      = excluded.texts_json,
                image_ids_json  = excluded.image_ids_json,
                last_update     = excluded.last_update
            """,
            (
                user_id,
                first_name,
                last_name,
                json.dumps(texts, ensure_ascii=False),
                json.dumps(image_ids, ensure_ascii=False),
                last_update,
            ),
        )
        await db.commit()


async def save_last_response_id(user_id: str, last_response_id: str) -> None:
    """Сохраняет ID последнего ответа Responses API для продолжения диалога."""
    async with aiosqlite.connect(_db_path) as db:
        await db.execute(
            "UPDATE users SET last_response_id = ? WHERE user_id = ?",
            (last_response_id, user_id),
        )
        await db.commit()


async def clear_buffer(user_id: str) -> None:
    """Очищает буфер текстов и изображений. last_response_id сохраняет."""
    async with aiosqlite.connect(_db_path) as db:
        await db.execute(
            """
            UPDATE users
            SET texts_json = '[]', image_ids_json = '[]', last_update = 0
            WHERE user_id = ?
            """,
            (user_id,),
        )
        await db.commit()
