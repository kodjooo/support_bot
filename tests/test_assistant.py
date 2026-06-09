import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("OPENAI_ASSISTANT_ID", "asst_test")
os.environ.setdefault("OPERATOR_CHAT_ID", "0")
os.environ.setdefault("OPERATOR_NAME", "test")
os.environ.setdefault("DATABASE_PATH", "/tmp/test.db")

from app.ai.assistant import call_assistant


def _make_run(status: str, tool_name: str | None = None):
    run = MagicMock()
    run.status = status
    if tool_name:
        tc = MagicMock()
        tc.function.name = tool_name
        run.required_action.submit_tool_outputs.tool_calls = [tc]
    return run


def _make_messages(text: str):
    msg = MagicMock()
    msg.data[0].content[0].text.value = text
    return msg


@pytest.mark.asyncio
async def test_completed_returns_text():
    run = _make_run("completed")
    with patch("app.ai.assistant._client") as mock_client:
        mock_client.beta.threads.create = AsyncMock(return_value=MagicMock(id="thread_new"))
        mock_client.beta.threads.messages.create = AsyncMock()
        mock_client.beta.threads.runs.create_and_poll = AsyncMock(return_value=run)
        mock_client.beta.threads.messages.list = AsyncMock(return_value=_make_messages("Привет!"))

        text, needs_op, tid = await call_assistant(None, ["вопрос"], [])

    assert text == "Привет!"
    assert needs_op is False
    assert tid == "thread_new"


@pytest.mark.asyncio
async def test_requires_action_transfer():
    run = _make_run("requires_action", tool_name="transfer_to_operator")
    with patch("app.ai.assistant._client") as mock_client:
        mock_client.beta.threads.create = AsyncMock(return_value=MagicMock(id="thread_x"))
        mock_client.beta.threads.messages.create = AsyncMock()
        mock_client.beta.threads.runs.create_and_poll = AsyncMock(return_value=run)

        text, needs_op, tid = await call_assistant(None, ["вопрос"], [])

    assert needs_op is True
    assert text is None


@pytest.mark.asyncio
async def test_failed_status_transfers():
    run = _make_run("failed")
    with patch("app.ai.assistant._client") as mock_client:
        mock_client.beta.threads.create = AsyncMock(return_value=MagicMock(id="thread_y"))
        mock_client.beta.threads.messages.create = AsyncMock()
        mock_client.beta.threads.runs.create_and_poll = AsyncMock(return_value=run)

        text, needs_op, tid = await call_assistant(None, [], [])

    assert needs_op is True


@pytest.mark.asyncio
async def test_existing_thread_reused():
    run = _make_run("completed")
    with patch("app.ai.assistant._client") as mock_client:
        mock_client.beta.threads.create = AsyncMock()
        mock_client.beta.threads.messages.create = AsyncMock()
        mock_client.beta.threads.runs.create_and_poll = AsyncMock(return_value=run)
        mock_client.beta.threads.messages.list = AsyncMock(return_value=_make_messages("ок"))

        _, _, tid = await call_assistant("existing_thread", ["текст"], [])

    # create не должен вызываться — тред уже есть
    mock_client.beta.threads.create.assert_not_called()
    assert tid == "existing_thread"
