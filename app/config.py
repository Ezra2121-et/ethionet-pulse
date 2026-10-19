from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "EthioNet Pulse"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/ethionet.db"

    # Monitoring
    CHECK_INTERVAL_SECONDS: int = 30
    INTERNET_TARGETS: str = "1.1.1.1,8.8.8.8,9.9.9.9"
    REQUEST_TIMEOUT_SECONDS: int = 5

    # Telegram (optional)
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    ENABLE_TELEGRAM_ALERTS: bool = False

    @property
    def targets_list(self) -> List[str]:
        """Convert the comma-separated targets into a clean list"""
        return [t.strip() for t in self.INTERNET_TARGETS.split(",") if t.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Create a single settings object that the whole app will use
settings = Settings()
