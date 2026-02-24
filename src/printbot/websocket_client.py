import asyncio
import json
import logging
import random
import time

import websockets

from .config import Settings
from .job_handler import handle_print_job
from .printing import get_printer_status

logger = logging.getLogger(__name__)

__version__ = "0.2.0"


class GatewayClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._ws = None
        self._job_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._start_time = time.monotonic()

    async def run(self):
        """Main run loop with auto-reconnect."""
        self._running = True
        delay = self.settings.reconnect_delay

        while self._running:
            try:
                await self._connect_and_listen()
                # Connection closed normally, reset delay
                delay = self.settings.reconnect_delay
            except (websockets.ConnectionClosed, ConnectionError, OSError) as e:
                logger.warning("Connection lost: %s", e)
            except Exception as e:
                logger.exception("Unexpected error: %s", e)

            if not self._running:
                break

            # Exponential backoff with jitter
            jitter = random.uniform(0, delay * 0.3)
            wait = delay + jitter
            logger.info("Reconnecting in %.1f seconds...", wait)
            await asyncio.sleep(wait)
            delay = min(delay * 2, self.settings.max_reconnect_delay)

    async def _connect_and_listen(self):
        """Connect to server and process messages."""
        extra_headers = {"Authorization": f"Bearer {self.settings.api_key}"}

        logger.info("Connecting to %s", self.settings.ws_url)
        async with websockets.connect(
            self.settings.ws_url,
            additional_headers=extra_headers,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=10,
        ) as ws:
            self._ws = ws
            logger.info("Connected to server")

            # Start heartbeat and job processor tasks
            heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            processor_task = asyncio.create_task(self._process_jobs())

            try:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON received")
                        continue

                    await self._handle_message(msg)
            finally:
                heartbeat_task.cancel()
                processor_task.cancel()
                self._ws = None

    async def _handle_message(self, msg: dict):
        """Route incoming messages by type."""
        msg_type = msg.get("type")

        if msg_type == "print":
            await self._job_queue.put(msg)
            logger.info("Print job queued: %s", msg.get("job_id", "?"))

        elif msg_type == "ping":
            await self._send({"type": "pong", "timestamp": msg.get("timestamp", "")})

        elif msg_type == "config_update":
            logger.info("Config update received: %s", msg.get("printer_config", {}))

        elif msg_type == "ota_update":
            logger.info("OTA update available: v%s", msg.get("version", "?"))
            # TODO: implement OTA update handler

        else:
            logger.warning("Unknown message type: %s", msg_type)

    async def _heartbeat_loop(self):
        """Send periodic heartbeats."""
        while True:
            try:
                printer_status = get_printer_status(self.settings.printer_name)
                uptime = int(time.monotonic() - self._start_time)

                await self._send({
                    "type": "heartbeat",
                    "gateway_id": self.settings.gateway_id,
                    "version": __version__,
                    "printer_status": printer_status,
                    "uptime": uptime,
                })
                logger.debug("Heartbeat sent (printer=%s, uptime=%ds)", printer_status, uptime)
            except Exception as e:
                logger.error("Heartbeat error: %s", e)

            await asyncio.sleep(self.settings.heartbeat_interval)

    async def _process_jobs(self):
        """Process print jobs from queue sequentially."""
        while True:
            msg = await self._job_queue.get()
            job_id = msg.get("job_id", "unknown")

            try:
                # Acknowledge receipt
                await self._send_job_status(job_id, "received")

                # Process the job
                await self._send_job_status(job_id, "printing")
                result = await asyncio.to_thread(
                    handle_print_job,
                    msg,
                    self.settings.printer_name,
                    self.settings.state_dir,
                    self.settings.dry_run,
                )

                await self._send_job_status(job_id, result["status"], result.get("error"))

            except Exception as e:
                logger.exception("Job %s failed: %s", job_id, e)
                await self._send_job_status(job_id, "failed", str(e))

            self._job_queue.task_done()

    async def _send_job_status(self, job_id: str, status: str, error: str | None = None):
        """Send job status update to server."""
        msg = {"type": "job_status", "job_id": job_id, "status": status}
        if error:
            msg["error"] = error
        await self._send(msg)

    async def _send(self, msg: dict):
        """Send JSON message via WebSocket."""
        if self._ws:
            await self._ws.send(json.dumps(msg))

    async def shutdown(self):
        """Graceful shutdown: wait for current job, close connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
