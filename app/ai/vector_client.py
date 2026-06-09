"""HTTP-клиент для поиска релевантных чанков в vector-base-for-bot."""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Таймаут запроса к сервису векторного поиска (секунды)
_REQUEST_TIMEOUT = 5.0


async def fetch_context(query: str) -> list[str]:
    """
    Возвращает релевантные чанки из векторной базы знаний.
    При недоступности сервиса или ошибке возвращает пустой список —
    бот продолжит работу без контекста.
    """
    if not settings.vector_base_url:
        return []

    url = f"{settings.vector_base_url.rstrip('/')}/search"

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            logger.info("[VECTOR] Запрос поиска: %s", query[:300])
            response = await client.post(url, json={"query": query, "top_k": 3})
            response.raise_for_status()
            data = response.json()
            chunks = data.get("chunks") or []
            logger.info("[VECTOR] Найдено чанков: %d", len(chunks))
            for i, chunk in enumerate(chunks):
                logger.info("[VECTOR] Чанк %d: %s", i + 1, chunk[:200])
            return chunks
    except httpx.TimeoutException:
        logger.warning("Таймаут запроса к векторной базе (%s).", url)
    except httpx.HTTPStatusError as exc:
        logger.warning("Ошибка HTTP от векторной базы: %s.", exc.response.status_code)
    except Exception:
        logger.warning("Не удалось получить контекст из векторной базы.", exc_info=True)

    return []
