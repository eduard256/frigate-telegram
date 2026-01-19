"""
Worker pool for processing Frigate events asynchronously.
Each worker takes events from the queue, processes them, and sends to Telegram.
"""

import asyncio
import logging
from typing import List

from config import Config
from mqtt_listener import FrigateEvent
from video_processor import VideoProcessor
from telegram_sender import TelegramSender

logger = logging.getLogger(__name__)


class WorkerPool:
    """
    Pool of async workers that process events from queue.
    Each worker independently downloads, processes, and sends events.
    """

    def __init__(
        self,
        config: Config,
        queue: asyncio.Queue,
        video_processor: VideoProcessor,
        telegram_sender: TelegramSender,
    ):
        self.config = config
        self.queue = queue
        self.video_processor = video_processor
        self.telegram_sender = telegram_sender
        self.workers: List[asyncio.Task] = []
        self.running = False

        # Stats
        self.processed_count = 0
        self.error_count = 0

    async def start(self):
        """Start all workers."""
        self.running = True
        logger.info(f"Starting {self.config.max_workers} workers")

        for i in range(self.config.max_workers):
            worker = asyncio.create_task(self._worker(i))
            self.workers.append(worker)

    async def _worker(self, worker_id: int):
        """
        Worker coroutine that processes events from queue.

        Args:
            worker_id: Unique identifier for this worker
        """
        logger.debug(f"Worker {worker_id} started")

        while self.running:
            try:
                # Wait for event with timeout to allow clean shutdown
                try:
                    event = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                logger.info(f"Worker {worker_id} processing {event.event_id}")

                # Process the event
                processed = await self.video_processor.process_event(
                    event_id=event.event_id,
                    camera=event.camera,
                    label=event.label,
                    duration=event.duration,
                )

                if processed is None:
                    logger.error(f"Worker {worker_id} failed to process {event.event_id}")
                    self.error_count += 1
                    self.queue.task_done()
                    continue

                # Send to Telegram
                success = await self.telegram_sender.send_event(processed)

                if success:
                    self.processed_count += 1
                    logger.info(f"Worker {worker_id} completed {event.event_id}")
                else:
                    self.error_count += 1
                    logger.error(f"Worker {worker_id} failed to send {event.event_id}")

                # Cleanup temp files
                await self.video_processor.cleanup_processed_event(processed)

                self.queue.task_done()

            except asyncio.CancelledError:
                logger.debug(f"Worker {worker_id} cancelled")
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
                self.error_count += 1
                # Don't break - continue processing other events

        logger.debug(f"Worker {worker_id} stopped")

    async def stop(self):
        """Stop all workers gracefully."""
        logger.info("Stopping worker pool...")
        self.running = False

        # Wait for queue to be processed (with timeout)
        try:
            await asyncio.wait_for(self.queue.join(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for queue to drain")

        # Cancel all workers
        for worker in self.workers:
            worker.cancel()

        # Wait for workers to finish
        if self.workers:
            await asyncio.gather(*self.workers, return_exceptions=True)

        self.workers.clear()
        logger.info("Worker pool stopped")

    def get_stats(self) -> dict:
        """Get worker pool statistics."""
        return {
            "workers": len(self.workers),
            "queue_size": self.queue.qsize(),
            "processed": self.processed_count,
            "errors": self.error_count,
        }
