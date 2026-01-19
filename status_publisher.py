"""
MQTT status publisher for automation monitoring.
Periodically publishes status to MQTT for monitoring dashboards.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Callable

import aiomqtt

from config import Config

logger = logging.getLogger(__name__)


class StatusPublisher:
    """
    Publishes automation status to MQTT periodically.
    Used for monitoring and debugging.
    """

    def __init__(self, config: Config, stats_callback: Callable[[], dict]):
        self.config = config
        self.stats_callback = stats_callback
        self.start_time = datetime.now()
        self.running = False
        self.status_topic = "automation/frigate-telegram/status"

    async def start(self):
        """Start periodic status publishing."""
        self.running = True
        logger.info("Status publisher started")

        while self.running:
            try:
                await self._publish_status()
            except Exception as e:
                logger.error(f"Status publish error: {e}")

            # Wait for next interval
            await asyncio.sleep(self.config.status_interval)

    async def _publish_status(self):
        """Publish current status to MQTT."""
        try:
            stats = self.stats_callback()
            uptime = (datetime.now() - self.start_time).total_seconds()

            status = {
                "name": "frigate-telegram",
                "status": "running",
                "uptime": int(uptime),
                "timestamp": datetime.now().isoformat(),
                **stats,
            }

            async with aiomqtt.Client(
                hostname=self.config.mqtt_broker,
                port=self.config.mqtt_port,
                username=self.config.mqtt_user or None,
                password=self.config.mqtt_password or None,
                identifier="frigate-telegram-status",
            ) as client:
                await client.publish(
                    self.status_topic,
                    payload=json.dumps(status),
                    retain=True,
                )
                logger.debug("Status published to MQTT")

        except Exception as e:
            logger.error(f"Failed to publish status: {e}")

    def stop(self):
        """Stop the status publisher."""
        self.running = False
        logger.info("Status publisher stopping...")
