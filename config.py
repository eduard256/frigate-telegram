"""
Configuration and mappings for Frigate-Telegram integration.
All settings are loaded from environment variables.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, Set


def _parse_camera_thread_map() -> Dict[str, int]:
    """
    Parse CAMERA_THREAD_MAP from environment variable.
    Expected format: JSON object {"camera-name": thread_id, ...}
    Example: {"cam-doorbell": 2, "cam-entrance": 3}
    """
    raw = os.getenv("CAMERA_THREAD_MAP", "{}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _parse_thumbnail_only_cameras() -> Set[str]:
    """
    Parse THUMBNAIL_ONLY_CAMERAS from environment variable.
    Expected format: comma-separated list of camera names
    Example: cam-entrance,cam-kitchen
    """
    raw = os.getenv("THUMBNAIL_ONLY_CAMERAS", "")
    if not raw.strip():
        return set()
    return {cam.strip() for cam in raw.split(",") if cam.strip()}


@dataclass
class Config:
    """Main configuration class with all settings."""

    # MQTT settings
    mqtt_broker: str = os.getenv("MQTT_BROKER", "localhost")
    mqtt_port: int = int(os.getenv("MQTT_PORT", "1883"))
    mqtt_user: str = os.getenv("MQTT_USER", "")
    mqtt_password: str = os.getenv("MQTT_PASSWORD", "")
    mqtt_topic: str = os.getenv("MQTT_TOPIC", "frigate/events")

    # Frigate settings
    frigate_url: str = os.getenv("FRIGATE_URL", "http://localhost:5000")

    # Telegram settings
    telegram_token: str = os.getenv("TELEGRAM_TOKEN", "")
    telegram_chat_id: int = int(os.getenv("TELEGRAM_CHAT_ID", "0"))

    # Worker settings
    max_workers: int = int(os.getenv("MAX_WORKERS", "10"))
    max_queue_size: int = int(os.getenv("MAX_QUEUE_SIZE", "1000"))

    # Video processing settings
    max_event_duration: int = int(os.getenv("MAX_EVENT_DURATION", str(30 * 60)))  # 30 minutes
    video_chunk_duration: int = int(os.getenv("VIDEO_CHUNK_DURATION", str(10 * 60)))  # 10 minutes
    video_scale: str = os.getenv("VIDEO_SCALE", "1280:-2")  # Width 1280, height auto
    video_crf: int = int(os.getenv("VIDEO_CRF", "23"))  # Quality (lower = better, 18-28 typical)
    audio_bitrate: str = os.getenv("AUDIO_BITRATE", "128k")

    # Retry settings
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    retry_delays: tuple = (5, 15, 30)  # Exponential backoff delays in seconds

    # HTTP timeouts
    download_timeout: int = int(os.getenv("DOWNLOAD_TIMEOUT", "60"))
    upload_timeout: int = int(os.getenv("UPLOAD_TIMEOUT", "120"))

    # Health check
    health_port: int = int(os.getenv("HEALTH_PORT", "8085"))

    # Status publishing interval (seconds)
    status_interval: int = int(os.getenv("STATUS_INTERVAL", "60"))

    # Camera mappings (loaded from env)
    camera_thread_map: Dict[str, int] = field(default_factory=_parse_camera_thread_map)
    thumbnail_only_cameras: Set[str] = field(default_factory=_parse_thumbnail_only_cameras)


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
