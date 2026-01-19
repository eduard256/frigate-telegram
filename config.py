"""
Configuration and mappings for Frigate-Telegram integration.
All settings are loaded from environment variables with sensible defaults.
"""

import os
from dataclasses import dataclass
from typing import Dict, Set


@dataclass
class Config:
    """Main configuration class with all settings."""

    # MQTT settings
    mqtt_broker: str = os.getenv("MQTT_BROKER", "10.0.20.20")
    mqtt_port: int = int(os.getenv("MQTT_PORT", "1883"))
    mqtt_user: str = os.getenv("MQTT_USER", "")
    mqtt_password: str = os.getenv("MQTT_PASSWORD", "")
    mqtt_topic: str = "frigate/events"

    # Frigate settings
    frigate_url: str = os.getenv("FRIGATE_URL", "http://10.0.10.3:5000")

    # Telegram settings
    telegram_token: str = os.getenv("TELEGRAM_TOKEN", "")
    telegram_chat_id: int = int(os.getenv("TELEGRAM_CHAT_ID", "-1002981790452"))

    # Worker settings
    max_workers: int = int(os.getenv("MAX_WORKERS", "10"))
    max_queue_size: int = int(os.getenv("MAX_QUEUE_SIZE", "1000"))

    # Video processing settings
    max_event_duration: int = 30 * 60  # 30 minutes in seconds
    video_chunk_duration: int = 10 * 60  # 10 minutes in seconds
    video_scale: str = "1280:-2"  # Width 1280, height auto (divisible by 2)
    video_crf: int = 23  # Quality (lower = better, 18-28 typical)
    audio_bitrate: str = "128k"

    # Retry settings
    max_retries: int = 3
    retry_delays: tuple = (5, 15, 30)  # Exponential backoff delays in seconds

    # HTTP timeouts
    download_timeout: int = 60  # Seconds
    upload_timeout: int = 120  # Seconds

    # Health check
    health_port: int = int(os.getenv("HEALTH_PORT", "8085"))

    # Status publishing interval (seconds)
    status_interval: int = 60


# Camera to Telegram thread_id mapping
CAMERA_THREAD_MAP: Dict[str, int] = {
    "cam-doorbell": 2,
    "cam-entrance-hall": 3,
    "cam-house-entrance": 5,
    "cam-main-gate": 6,
    "cam-main-terrace": 7,
    "cam-dog-pen-gate": 8,
    "cam-parking-secondary": 11,
    "cam-professional-kitchen": 12,
    "cam-staff-house-entrance": 13,
    "cam-street-left": 14,
    "cam-street-right": 15,
}

# Cameras with broken video codec (only thumbnail available)
THUMBNAIL_ONLY_CAMERAS: Set[str] = {
    "cam-house-entrance",
    "cam-professional-kitchen",
}

# Object labels we care about and their Russian translations
LABEL_TRANSLATIONS: Dict[str, str] = {
    "person": "человек",
    "dog": "собака",
    "cat": "кошка",
    "car": "машина",
}

# Labels to process (ignore motion, etc.)
ALLOWED_LABELS: Set[str] = set(LABEL_TRANSLATIONS.keys())


def get_config() -> Config:
    """Get configuration instance."""
    return Config()
