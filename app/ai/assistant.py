from openai import AsyncOpenAI

from app.config import settings

_client = AsyncOpenAI(api_key=settings.openai_api_key)

# Инструмент Function Calling для перевода на оператора
OPERATOR_TOOLS = [
    {
        "type": "function",
        "name": "transfer_to_operator",
        "description": (
            "Вызвать эту функцию, когда вопрос пользователя выходит за рамки "
            "компетенции ассистента и требует участия живого оператора."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    }
]


async def call_assistant(
    last_response_id: str | None,
    texts: list[str],
    image_urls: list[str],
) -> tuple[str | None, bool, str | None]:
    """
    Отправляет сообщение через OpenAI Responses API и возвращает:
      (response_text, needs_operator, new_last_response_id)

    Если needs_operator=True — response_text будет None.
    Бросает исключение при любой сетевой или API ошибке.
    """
    combined_text = "\n".join(texts) if texts else ""

    # Формируем content: текст + изображения
    content: list[dict] = [{"type": "input_text", "text": combined_text}]
    for url in image_urls:
        content.append({"type": "input_image", "image_url": url})

    # Параметры запроса
    params: dict = {
        "model": settings.openai_model,
        "input": content,
        "tools": OPERATOR_TOOLS,
    }

    # Системный промпт — только при первом обращении (нет previous_response_id)
    if last_response_id is None:
        instructions = settings.get_instructions()
        if instructions:
            params["instructions"] = instructions

    # Продолжение существующего диалога
    if last_response_id is not None:
        params["previous_response_id"] = last_response_id

    # Температура — для gpt-серии (0.0–2.0); модели o-серии её не поддерживают
    if settings.openai_temperature is not None:
        params["temperature"] = settings.openai_temperature

    # Уровень рассуждения — только для моделей o-серии (o3, o4-mini и др.)
    if settings.openai_reasoning_effort is not None:
        params["reasoning"] = {"effort": settings.openai_reasoning_effort}

    response = await _client.responses.create(**params)

    new_last_response_id = response.id

    # Проверяем, вызвал ли ассистент transfer_to_operator
    for item in response.output:
        if getattr(item, "type", None) == "function_tool_call":
            if getattr(item, "name", None) == "transfer_to_operator":
                return None, True, new_last_response_id

    # Получаем текстовый ответ
    if response.status == "completed":
        return response.output_text, False, new_last_response_id

    # Все остальные статусы (failed, incomplete и т.д.)
    return None, True, new_last_response_id
