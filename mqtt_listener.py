"""
MQTT listener for Frigate events with filtering and reconnection logic.
Listens to frigate/events and filters based on event type, labels, and duration.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Optional

import aiomqtt

from config import Config, ALLOWED_LABELS, CAMERA_THREAD_MAP

logger = logging.getLogger(__name__)


@dataclass
class FrigateEvent:
    """Parsed Frigate event ready for processing."""
    event_id: str
    camera: str
    label: str
    start_time: float
    end_time: float
    duration: float
    stationary: bool


class MQTTListener:
    """
    Listens to Frigate MQTT events and filters them.
    Automatically reconnects on disconnection.
    """

    def __init__(self, config: Config, queue: asyncio.Queue):
        self.config = config
        self.queue = queue
        self.running = False
        self.connected = False
        self.reconnect_delay = 5  # seconds

    async def start(self):
        """Start listening to MQTT with auto-reconnect."""
        self.running = True
        while self.running:
            try:
                await self._connect_and_listen()
            except aiomqtt.MqttError as e:
                self.connected = False
                logger.error(f"MQTT connection error: {e}")
                if self.running:
                    logger.info(f"Reconnecting in {self.reconnect_delay}s...")
                    await asyncio.sleep(self.reconnect_delay)
            except Exception as e:
                self.connected = False
                logger.error(f"Unexpected error in MQTT listener: {e}")
                if self.running:
                    await asyncio.sleep(self.reconnect_delay)

    async def _connect_and_listen(self):
        """Connect to MQTT and listen for messages."""
        logger.info(f"Connecting to MQTT {self.config.mqtt_broker}:{self.config.mqtt_port}")

        async with aiomqtt.Client(
            hostname=self.config.mqtt_broker,
            port=self.config.mqtt_port,
            username=self.config.mqtt_user or None,
            password=self.config.mqtt_password or None,
            identifier="frigate-telegram",
        ) as client:
            self.connected = True
            logger.info("Connected to MQTT broker")

            await client.subscribe(self.config.mqtt_topic)
            logger.info(f"Subscribed to {self.config.mqtt_topic}")

            async for message in client.messages:
                try:
                    await self._handle_message(message)
                except Exception as e:
                    logger.error(f"Error handling message: {e}")

    async def _handle_message(self, message):
        """Parse and filter incoming MQTT message."""
        try:
            payload = json.loads(message.payload.decode())
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in MQTT message")
            return

        # Only process "end" events (event completed, clip ready)
        event_type = payload.get("type")
        if event_type != "end":
            return

        # Get the "after" state (final state of the event)
        after = payload.get("after", {})

        event_id = after.get("id")
        camera = after.get("camera")
        label = after.get("label")
        start_time = after.get("start_time")
        end_time = after.get("end_time")
        stationary = after.get("stationary", False)
        has_clip = after.get("has_clip", False)

        # Validate required fields
        if not all([event_id, camera, label, start_time, end_time]):
            logger.debug("Skipping event with missing fields")
            return

        # Filter: only allowed labels
        if label not in ALLOWED_LABELS:
            logger.debug(f"Skipping label: {label}")
            return

        # Filter: only cameras we have thread mappings for
        if camera not in CAMERA_THREAD_MAP:
            logger.debug(f"Skipping unmapped camera: {camera}")
            return

        # Filter: skip stationary objects (parked cars)
        if stationary:
            logger.debug(f"Skipping stationary object: {event_id}")
            return

        # Filter: must have clip
        if not has_clip:
            logger.debug(f"Skipping event without clip: {event_id}")
            return

        # Calculate duration
        duration = end_time - start_time

        # Filter: skip events longer than max duration (30 min)
        if duration > self.config.max_event_duration:
            logger.info(f"Skipping event > 30min: {event_id} ({duration:.0f}s)")
            return

        event = FrigateEvent(
            event_id=event_id,
            camera=camera,
            label=label,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            stationary=stationary,
        )

        logger.info(f"New event: {camera} {label} ({duration:.0f}s) - {event_id}")

        # Check queue size
        if self.queue.qsize() >= self.config.max_queue_size:
            logger.warning("Queue full, dropping oldest event")
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

        await self.queue.put(event)

    def stop(self):
        """Stop the listener."""
        self.running = False
        logger.info("MQTT listener stopping...")
