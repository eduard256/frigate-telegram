#!/usr/bin/env python3
"""
Frigate to Telegram automation.
Monitors Frigate events via MQTT and sends video clips/thumbnails to Telegram forum topics.

Architecture:
- MQTTListener: Subscribes to frigate/events, filters and queues events
- WorkerPool: 10 async workers process events in parallel
- VideoProcessor: Downloads, compresses, splits videos
- TelegramSender: Sends to Telegram with retry logic
- HealthCheck: HTTP /health endpoint
- StatusPublisher: Publishes status to MQTT
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime

from config import get_config
from mqtt_listener import MQTTListener
from worker_pool import WorkerPool
from video_processor import VideoProcessor
from telegram_sender import TelegramSender
from health_check import HealthCheck
from status_publisher import StatusPublisher

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("frigate-telegram")


class FrigateTelegramBot:
    """Main application class that orchestrates all components."""

    def __init__(self):
        self.config = get_config()
        self.queue: asyncio.Queue = asyncio.Queue()
        self.running = False

        # Components
        self.mqtt_listener: MQTTListener = None
        self.worker_pool: WorkerPool = None
        self.video_processor: VideoProcessor = None
        self.telegram_sender: TelegramSender = None
        self.health_check: HealthCheck = None
        self.status_publisher: StatusPublisher = None

        # Tasks
        self.tasks = []

    def _get_stats(self) -> dict:
        """Get combined stats from all components."""
        stats = {
            "mqtt_connected": False,
            "queue_size": self.queue.qsize(),
            "workers": 0,
            "processed": 0,
            "errors": 0,
        }

        if self.mqtt_listener:
            stats["mqtt_connected"] = self.mqtt_listener.connected

        if self.worker_pool:
            worker_stats = self.worker_pool.get_stats()
            stats.update(worker_stats)

        return stats

    async def start(self):
        """Initialize and start all components."""
        logger.info("=" * 60)
        logger.info("Frigate-Telegram Bot starting...")
        logger.info("=" * 60)

        self.running = True

        # Validate config
        if not self.config.telegram_token:
            logger.error("TELEGRAM_TOKEN not set!")
            return

        # Initialize components
        self.video_processor = VideoProcessor(self.config)
        self.telegram_sender = TelegramSender(self.config)
        self.mqtt_listener = MQTTListener(self.config, self.queue)
        self.worker_pool = WorkerPool(
            self.config,
            self.queue,
            self.video_processor,
            self.telegram_sender,
        )
        self.health_check = HealthCheck(self.config.health_port, self._get_stats)
        self.status_publisher = StatusPublisher(self.config, self._get_stats)

        # Start health check first
        await self.health_check.start()

        # Start worker pool
        await self.worker_pool.start()

        # Start MQTT listener and status publisher as tasks
        mqtt_task = asyncio.create_task(self.mqtt_listener.start())
        status_task = asyncio.create_task(self.status_publisher.start())
        self.tasks = [mqtt_task, status_task]

        logger.info("All components started successfully")
        logger.info(f"Health check: http://0.0.0.0:{self.config.health_port}/health")
        logger.info(f"Workers: {self.config.max_workers}")
        logger.info(f"Max queue size: {self.config.max_queue_size}")
        logger.info("=" * 60)

        # Wait for shutdown signal
        await self._wait_for_shutdown()

    async def _wait_for_shutdown(self):
        """Wait for tasks to complete or shutdown signal."""
        try:
            await asyncio.gather(*self.tasks)
        except asyncio.CancelledError:
            logger.info("Tasks cancelled")

    async def stop(self):
        """Gracefully stop all components."""
        logger.info("Shutting down...")
        self.running = False

        # Stop components in order
        if self.mqtt_listener:
            self.mqtt_listener.stop()

        if self.status_publisher:
            self.status_publisher.stop()

        if self.worker_pool:
            await self.worker_pool.stop()

        if self.health_check:
            await self.health_check.stop()

        # Cancel remaining tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()

        logger.info("Shutdown complete")


async def main():
    """Main entry point."""
    bot = FrigateTelegramBot()

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()

    def signal_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(bot.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
