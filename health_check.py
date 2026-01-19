"""
Health check HTTP endpoint for monitoring and container orchestration.
Provides /health endpoint with status information.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Callable

from aiohttp import web

logger = logging.getLogger(__name__)


class HealthCheck:
    """
    Simple HTTP server for health checks.
    Exposes /health endpoint with component status.
    """

    def __init__(self, port: int, stats_callback: Callable[[], dict]):
        self.port = port
        self.stats_callback = stats_callback
        self.start_time = datetime.now()
        self.app = web.Application()
        self.runner = None

        # Setup routes
        self.app.router.add_get("/health", self._health_handler)
        self.app.router.add_get("/", self._health_handler)

    async def start(self):
        """Start the health check server."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        site = web.TCPSite(self.runner, "0.0.0.0", self.port)
        await site.start()

        logger.info(f"Health check server started on port {self.port}")

    async def stop(self):
        """Stop the health check server."""
        if self.runner:
            await self.runner.cleanup()
            logger.info("Health check server stopped")

    async def _health_handler(self, request: web.Request) -> web.Response:
        """Handle health check requests."""
        try:
            stats = self.stats_callback()
            uptime = (datetime.now() - self.start_time).total_seconds()

            response = {
                "status": "healthy",
                "uptime_seconds": int(uptime),
                "timestamp": datetime.now().isoformat(),
                **stats,
            }

            return web.Response(
                text=json.dumps(response, indent=2),
                content_type="application/json",
                status=200,
            )

        except Exception as e:
            logger.error(f"Health check error: {e}")
            return web.Response(
                text=json.dumps({"status": "unhealthy", "error": str(e)}),
                content_type="application/json",
                status=500,
            )
