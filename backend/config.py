"""Settings for backend services, read from the repo's .env."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

STREAM_IN = "lms:in"  # Redis stream: validated device messages
STREAM_GROUP = "processor"
CHANNEL_LIVE = "lms:live"  # Redis pub/sub: live updates for dashboards
CHANNEL_ALERTS = "lms:alerts"  # Redis pub/sub: new alerts for the notifier


@dataclass(frozen=True)
class Settings:
    mqtt_host: str = os.environ.get("MQTT_HOST", "127.0.0.1")
    mqtt_port: int = int(os.environ.get("MQTT_PORT", "1883"))
    mqtt_user: str = os.environ.get("MQTT_USER", "")
    mqtt_password: str = os.environ.get("MQTT_PASSWORD", "")
    redis_url: str = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    database_url: str = os.environ.get("DATABASE_URL", "")
    admin_user: str = os.environ.get("API_ADMIN_USER", "admin")
    admin_password: str = os.environ.get("API_ADMIN_PASSWORD", "")
    jwt_secret: str = os.environ.get("API_JWT_SECRET", "")
    rover_url: str = os.environ.get("ROVER_URL", "")
    rover_token: str = os.environ.get("ROVER_TOKEN", "")
    telegram_token: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.environ.get("TELEGRAM_CHAT_ID", "")


settings = Settings()
