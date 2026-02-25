import asyncio
import json
import logging
import random
import socket
import time

import websockets

from .config import Settings
from .job_handler import handle_print_job
from .ota_updater import perform_ota_update, restart_service
from .printing import add_printer, discover_devices, get_printer_status

logger = logging.getLogger(__name__)

__version__ = "0.4.0"


def _get_local_ip() -> str:
    """Get the local LAN IP address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return ""


class GatewayClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._ws = None
        self._job_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._start_time = time.monotonic()
        self._ota_in_progress: bool = False

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

        elif msg_type == "discover_devices":
            request_id = msg.get("request_id", "")
            timeout = msg.get("timeout", 10)
            logger.info("Device discovery requested (request_id=%s)", request_id)
            asyncio.create_task(self._handle_discover_devices(request_id, timeout))

        elif msg_type == "cups_add_printer":
            asyncio.create_task(self._handle_cups_add_printer(msg))

        elif msg_type == "ota_update":
            url = msg.get("url", "")
            checksum = msg.get("checksum", "")
            version = msg.get("version", "?")
            logger.info("OTA update available: v%s", version)
            asyncio.create_task(self._handle_ota_update(url, checksum, version))

        else:
            logger.warning("Unknown message type: %s", msg_type)

    async def _handle_discover_devices(self, request_id: str, timeout: int):
        """Run device discovery and send results back to the server.

        Backend discovery can take 10-30s on a Raspberry Pi.  The server
        SSE loop times out after 25s of *silence*, so we send keepalive
        status messages every 10s while discovery is running.
        """
        subprocess_timeout = max(timeout * 5, 50)
        try:
            await self._send_discover_status(request_id, "Scanning for devices...")
            discovery = asyncio.get_event_loop().run_in_executor(
                None, discover_devices, subprocess_timeout,
            )
            # Send keepalives while backend discovery is working
            while True:
                try:
                    devices = await asyncio.wait_for(
                        asyncio.shield(discovery), timeout=10.0,
                    )
                    break
                except asyncio.TimeoutError:
                    await self._send_discover_status(
                        request_id, "Still scanning for devices...",
                    )

            await self._send_discover_status(
                request_id, f"Found {len(devices)} device(s), finishing up...",
            )
            await self._send({
                "type": "discover_devices_response",
                "request_id": request_id,
                "devices": devices,
                "error": None,
            })
        except Exception as e:
            logger.exception("Device discovery failed: %s", e)
            await self._send({
                "type": "discover_devices_response",
                "request_id": request_id,
                "devices": [],
                "error": str(e),
            })

    async def _send_discover_status(self, request_id: str, message: str):
        """Send device discovery status update to server."""
        await self._send({
            "type": "discover_devices_status",
            "request_id": request_id,
            "message": message,
        })

    async def _handle_cups_add_printer(self, msg: dict):
        """Add a printer to CUPS and send the result back."""
        request_id = msg.get("request_id", "")
        printer_name = msg.get("printer_name", "")
        device_uri = msg.get("device_uri", "")
        logger.info(
            "cups_add_printer request (request_id=%s, name=%s, uri=%s)",
            request_id, printer_name, device_uri,
        )
        try:
            await asyncio.to_thread(
                add_printer,
                printer_name=printer_name,
                device_uri=device_uri,
                ppd=msg.get("ppd", ""),
                description=msg.get("description", ""),
                location=msg.get("location", ""),
                options=msg.get("options") or None,
            )
            await self._send({
                "type": "cups_response",
                "request_id": request_id,
                "success": True,
                "data": None,
                "error": None,
            })
        except Exception as e:
            logger.exception("cups_add_printer failed: %s", e)
            await self._send({
                "type": "cups_response",
                "request_id": request_id,
                "success": False,
                "data": None,
                "error": str(e),
            })

    async def _handle_ota_update(self, url: str, checksum: str, version: str):
        """Download and install an OTA update, reporting status to the server."""
        if self._ota_in_progress:
            logger.warning("OTA update already in progress, ignoring")
            return

        self._ota_in_progress = True
        try:
            await self._send_ota_status(version, "downloading")
            await asyncio.to_thread(perform_ota_update, url, checksum, version)
            await self._send_ota_status(version, "completed")
            logger.info("OTA update to v%s completed, restarting service", version)
            await asyncio.to_thread(restart_service)
        except Exception as e:
            logger.exception("OTA update to v%s failed: %s", version, e)
            await self._send_ota_status(version, "failed", str(e))
        finally:
            self._ota_in_progress = False

    async def _send_ota_status(self, version: str, status: str, error: str | None = None):
        """Send OTA status update to server."""
        msg = {"type": "ota_status", "version": version, "status": status}
        if error:
            msg["error"] = error
        await self._send(msg)

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
                    "local_ip": _get_local_ip(),
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
