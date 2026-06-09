from openai import AsyncOpenAI

from app.config import settings

_client = AsyncOpenAI(api_key=settings.openai_api_key)

# Инструмент Function Calling для перевода на оператора
OPERATOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "transfer_to_operator",
            "description": (
                "Вызвать эту функцию, когда вопрос пользователя выходит за рамки "
                "компетенции ассистента и требует участия живого оператора."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
]


async def call_assistant(
    thread_id: str | None,
    texts: list[str],
    image_urls: list[str],
) -> tuple[str | None, bool, str]:
    """
    Отправляет сообщение в OpenAI Assistant и возвращает:
      (response_text, needs_operator, thread_id)

    Если needs_operator=True — response_text будет None.
    Бросает исключение при любой сетевой или API ошибке.
    """
    # Создаём или переиспользуем Thread
    if thread_id is None:
        thread = await _client.beta.threads.create()
        thread_id = thread.id

    # Формируем content: текст + изображения
    combined_text = "\n".join(texts) if texts else ""
    content: list[dict] = [{"type": "text", "text": combined_text}]
    for url in image_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})

    await _client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=content,
    )

    run = await _client.beta.threads.runs.create_and_poll(
        thread_id=thread_id,
        assistant_id=settings.openai_assistant_id,
        tools=OPERATOR_TOOLS,
        timeout=settings.openai_run_timeout,
    )

    # Ассистент вызвал transfer_to_operator
    if run.status == "requires_action":
        tool_calls = run.required_action.submit_tool_outputs.tool_calls
        if any(tc.function.name == "transfer_to_operator" for tc in tool_calls):
            return None, True, thread_id

    # Успешный ответ
    if run.status == "completed":
        messages = await _client.beta.threads.messages.list(thread_id=thread_id)
        raw_text = messages.data[0].content[0].text.value
        return raw_text, False, thread_id

    # Все остальные статусы (failed, expired, cancelled, тайм-аут)
    return None, True, thread_id
