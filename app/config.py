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
    DNS_TEST_HOSTS: str = "example.com,cloudflare.com"
    SERVICE_URLS: str = ""
    SERVICE_REQUEST_TIMEOUT_SECONDS: int = 10
    SERVICE_FAILURE_THRESHOLD: int = 2
    SERVICE_RECOVERY_THRESHOLD: int = 2

    # Packet-loss and latency quality monitoring (in addition to single-packet checks).
    PING_SAMPLES_PER_CHECK: int = 5
    QUALITY_PING_TIMEOUT_SECONDS: int = 1
    PACKET_LOSS_WARNING_PERCENT: float = 20.0
    HIGH_LATENCY_WARNING_MS: float = 400.0
    DEGRADATION_CONSECUTIVE_ROUNDS: int = 3
    QUALITY_RECOVERY_CONSECUTIVE_ROUNDS: int = 3

    # An outage is confirmed after this many consecutive failed check rounds.
    OUTAGE_FAILURE_THRESHOLD: int = 2
    OUTAGE_RECOVERY_THRESHOLD: int = 2

    # Web authentication
    SESSION_SECRET_KEY: str = ""
    SESSION_COOKIE_SECURE: bool = False
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    CONTACT_EMAIL: str = ""

    # Telegram (optional)
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    ENABLE_TELEGRAM_ALERTS: bool = False

    @property
    def targets_list(self) -> List[str]:
        """Convert the comma-separated targets into a clean list."""
        return [t.strip() for t in self.INTERNET_TARGETS.split(",") if t.strip()]

    @property
    def dns_test_hosts_list(self) -> List[str]:
        """Return DNS names that should resolve during a diagnosis."""
        return [host.strip() for host in self.DNS_TEST_HOSTS.split(",") if host.strip()]

    @property
    def service_urls_list(self) -> List[str]:
        """Return optional HTTP(S) services to check during diagnosis."""
        return [url.strip() for url in self.SERVICE_URLS.split(",") if url.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Create a single settings object that the whole app will use
settings = Settings()
