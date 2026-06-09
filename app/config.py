from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Telegram
    telegram_bot_token: str

    # OpenAI
    openai_api_key: str
    openai_assistant_id: str

    # Оператор
    operator_chat_id: str
    operator_name: str

    # База данных
    database_path: str = "./data/chatbot.db"

    # Параметры дебаунса и буфера
    debounce_delay: int = 4
    max_buffer_age: int = 3600
    max_images: int = 10
    min_photo_width: int = 800
    openai_run_timeout: int = 60


settings = Settings()
