"""
Telegram sender with retry logic and exponential backoff.
Handles both video and photo uploads to specific forum topics.
"""

import asyncio
import logging
from typing import Optional

import aiohttp

from config import Config, CAMERA_THREAD_MAP, LABEL_TRANSLATIONS
from video_processor import ProcessedEvent, VideoChunk

logger = logging.getLogger(__name__)


class TelegramSender:
    """Handles sending media to Telegram with retry logic."""

    def __init__(self, config: Config):
        self.config = config
        self.base_url = f"https://api.telegram.org/bot{config.telegram_token}"

    async def send_event(self, event: ProcessedEvent) -> bool:
        """
        Send all chunks of a processed event to Telegram.

        Args:
            event: ProcessedEvent with chunks to send

        Returns:
            True if all chunks were sent successfully
        """
        thread_id = CAMERA_THREAD_MAP.get(event.camera)
        if thread_id is None:
            logger.warning(f"No thread mapping for camera {event.camera}, skipping")
            return False

        success = True
        for chunk in event.chunks:
            caption = self._build_caption(event, chunk)
            chunk_success = await self._send_chunk(chunk, thread_id, caption)
            if not chunk_success:
                success = False
                logger.error(f"Failed to send chunk {chunk.part_number}/{chunk.total_parts} for {event.event_id}")

        return success

    def _build_caption(self, event: ProcessedEvent, chunk: VideoChunk) -> str:
        """Build caption with hashtags for the message."""
        parts = []

        # Part indicator if multiple chunks
        if chunk.total_parts > 1:
            parts.append(f"Часть {chunk.part_number}/{chunk.total_parts}")

        # Hashtags
        hashtags = []

        # Object type
        label_ru = LABEL_TRANSLATIONS.get(event.label, event.label)
        hashtags.append(f"#{label_ru}")

        # Camera name (replace dashes with underscores for valid hashtag)
        camera_tag = event.camera.replace("-", "_")
        hashtags.append(f"#{camera_tag}")

        # Event ID (short version)
        event_id_short = event.event_id.split("-")[0].split(".")[0]
        hashtags.append(f"#id_{event_id_short}")

        # Duration
        hashtags.append(f"#{event.duration}сек")

        # Thumbnail indicator
        if chunk.is_thumbnail:
            hashtags.append("#скриншот")

        parts.append(" ".join(hashtags))

        return "\n".join(parts)

    async def _send_chunk(
        self,
        chunk: VideoChunk,
        thread_id: int,
        caption: str,
    ) -> bool:
        """Send a single chunk with retry logic."""
        for attempt, delay in enumerate(self.config.retry_delays):
            try:
                if chunk.is_thumbnail:
                    success = await self._send_photo(chunk.file_path, thread_id, caption)
                else:
                    success = await self._send_video(chunk.file_path, thread_id, caption)

                if success:
                    return True

                logger.warning(f"Send attempt {attempt + 1} failed, retrying in {delay}s")
                await asyncio.sleep(delay)

            except Exception as e:
                logger.error(f"Send attempt {attempt + 1} error: {e}")
                if attempt < len(self.config.retry_delays) - 1:
                    await asyncio.sleep(delay)

        return False

    async def _send_video(self, file_path, thread_id: int, caption: str) -> bool:
        """Send video to Telegram."""
        try:
            timeout = aiohttp.ClientTimeout(total=self.config.upload_timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f"{self.base_url}/sendVideo"

                with open(file_path, "rb") as f:
                    data = aiohttp.FormData()
                    data.add_field("chat_id", str(self.config.telegram_chat_id))
                    data.add_field("message_thread_id", str(thread_id))
                    data.add_field("video", f, filename="video.mp4")
                    data.add_field("caption", caption)
                    data.add_field("supports_streaming", "true")

                    async with session.post(url, data=data) as response:
                        result = await response.json()

                        if result.get("ok"):
                            logger.info(f"Video sent to thread {thread_id}")
                            return True
                        else:
                            logger.error(f"Telegram error: {result.get('description')}")
                            return False

        except asyncio.TimeoutError:
            logger.error("Video upload timeout")
            return False
        except Exception as e:
            logger.error(f"Video upload error: {e}")
            return False

    async def _send_photo(self, file_path, thread_id: int, caption: str) -> bool:
        """Send photo to Telegram."""
        try:
            timeout = aiohttp.ClientTimeout(total=self.config.upload_timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f"{self.base_url}/sendPhoto"

                with open(file_path, "rb") as f:
                    data = aiohttp.FormData()
                    data.add_field("chat_id", str(self.config.telegram_chat_id))
                    data.add_field("message_thread_id", str(thread_id))
                    data.add_field("photo", f, filename="photo.jpg")
                    data.add_field("caption", caption)

                    async with session.post(url, data=data) as response:
                        result = await response.json()

                        if result.get("ok"):
                            logger.info(f"Photo sent to thread {thread_id}")
                            return True
                        else:
                            logger.error(f"Telegram error: {result.get('description')}")
                            return False

        except asyncio.TimeoutError:
            logger.error("Photo upload timeout")
            return False
        except Exception as e:
            logger.error(f"Photo upload error: {e}")
            return False

    async def send_message(self, thread_id: int, text: str) -> bool:
        """Send a text message to a specific thread."""
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f"{self.base_url}/sendMessage"
                payload = {
                    "chat_id": self.config.telegram_chat_id,
                    "message_thread_id": thread_id,
                    "text": text,
                }

                async with session.post(url, json=payload) as response:
                    result = await response.json()
                    return result.get("ok", False)

        except Exception as e:
            logger.error(f"Message send error: {e}")
            return False
