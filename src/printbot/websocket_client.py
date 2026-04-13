import asyncio
import json
import logging
import random
import socket
import time

import websockets

from . import __version__
from .config import Settings
from .job_handler import handle_print_job
from .ota_updater import perform_ota_update, request_restart
from .printing import (
    add_printer,
    discover_devices,
    get_printer_options,
    get_printer_status,
    list_printers,
    remove_printer,
    set_default_printer,
    set_printer_options,
)

logger = logging.getLogger(__name__)


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
            asyncio.create_task(self._handle_config_update(msg))

        elif msg_type == "discover_devices":
            request_id = msg.get("request_id", "")
            timeout = msg.get("timeout", 10)
            logger.info("Device discovery requested (request_id=%s)", request_id)
            asyncio.create_task(self._handle_discover_devices(request_id, timeout))

        elif msg_type == "cups_add_printer":
            asyncio.create_task(self._handle_cups_add_printer(msg))

        elif msg_type == "cups_list_printers":
            asyncio.create_task(self._handle_cups_list_printers(msg))

        elif msg_type == "cups_remove_printer":
            asyncio.create_task(self._handle_cups_remove_printer(msg))

        elif msg_type == "cups_set_default":
            asyncio.create_task(self._handle_cups_set_default(msg))

        elif msg_type == "cups_get_printer_options":
            asyncio.create_task(self._handle_cups_get_printer_options(msg))

        elif msg_type == "cups_set_printer_options":
            asyncio.create_task(self._handle_cups_set_printer_options(msg))

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

    async def _handle_cups_list_printers(self, msg: dict):
        """List CUPS printers and send the result back."""
        request_id = msg.get("request_id", "")
        logger.info("cups_list_printers request (request_id=%s)", request_id)
        try:
            printers = await asyncio.to_thread(list_printers)
            await self._send({
                "type": "cups_response",
                "request_id": request_id,
                "success": True,
                "data": printers,
                "error": None,
            })
        except Exception as e:
            logger.exception("cups_list_printers failed: %s", e)
            await self._send({
                "type": "cups_response",
                "request_id": request_id,
                "success": False,
                "data": None,
                "error": str(e),
            })

    async def _handle_cups_remove_printer(self, msg: dict):
        """Remove a CUPS printer and send the result back."""
        request_id = msg.get("request_id", "")
        printer_name = msg.get("printer_name", "")
        logger.info(
            "cups_remove_printer request (request_id=%s, name=%s)",
            request_id, printer_name,
        )
        try:
            await asyncio.to_thread(remove_printer, printer_name)
            await self._send({
                "type": "cups_response",
                "request_id": request_id,
                "success": True,
                "data": None,
                "error": None,
            })
        except Exception as e:
            logger.exception("cups_remove_printer failed: %s", e)
            await self._send({
                "type": "cups_response",
                "request_id": request_id,
                "success": False,
                "data": None,
                "error": str(e),
            })

    async def _handle_cups_set_default(self, msg: dict):
        """Set the default CUPS printer and send the result back."""
        request_id = msg.get("request_id", "")
        printer_name = msg.get("printer_name", "")
        logger.info(
            "cups_set_default request (request_id=%s, name=%s)",
            request_id, printer_name,
        )
        try:
            await asyncio.to_thread(set_default_printer, printer_name)
            await self._send({
                "type": "cups_response",
                "request_id": request_id,
                "success": True,
                "data": None,
                "error": None,
            })
        except Exception as e:
            logger.exception("cups_set_default failed: %s", e)
            await self._send({
                "type": "cups_response",
                "request_id": request_id,
                "success": False,
                "data": None,
                "error": str(e),
            })

    async def _handle_cups_get_printer_options(self, msg: dict):
        """Get CUPS printer options and send the result back."""
        request_id = msg.get("request_id", "")
        printer_name = msg.get("printer_name", "")
        logger.info(
            "cups_get_printer_options request (request_id=%s, name=%s)",
            request_id, printer_name,
        )
        try:
            options = await asyncio.to_thread(get_printer_options, printer_name)
            await self._send({
                "type": "cups_response",
                "request_id": request_id,
                "success": True,
                "data": options,
                "error": None,
            })
        except Exception as e:
            logger.exception("cups_get_printer_options failed: %s", e)
            await self._send({
                "type": "cups_response",
                "request_id": request_id,
                "success": False,
                "data": None,
                "error": str(e),
            })

    async def _handle_cups_set_printer_options(self, msg: dict):
        """Set CUPS printer options and send the result back."""
        request_id = msg.get("request_id", "")
        printer_name = msg.get("printer_name", "")
        options = msg.get("options", {})
        logger.info(
            "cups_set_printer_options request (request_id=%s, name=%s, options=%s)",
            request_id, printer_name, options,
        )
        try:
            await asyncio.to_thread(set_printer_options, printer_name, options)
            await self._send({
                "type": "cups_response",
                "request_id": request_id,
                "success": True,
                "data": None,
                "error": None,
            })
        except Exception as e:
            logger.exception("cups_set_printer_options failed: %s", e)
            await self._send({
                "type": "cups_response",
                "request_id": request_id,
                "success": False,
                "data": None,
                "error": str(e),
            })

    async def _handle_config_update(self, msg: dict):
        """Apply remote config changes, persist to .env, and send response."""
        applied = {}
        errors = []

        # printer_name
        if "printer_name" in msg and msg["printer_name"] is not None:
            self.settings.printer_name = str(msg["printer_name"])
            applied["printer_name"] = self.settings.printer_name

        # dry_run
        if "dry_run" in msg and msg["dry_run"] is not None:
            self.settings.dry_run = bool(msg["dry_run"])
            applied["dry_run"] = self.settings.dry_run

        # log_level
        if "log_level" in msg and msg["log_level"] is not None:
            level_str = str(msg["log_level"]).upper()
            if level_str in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
                self.settings.log_level = level_str
                logging.getLogger().setLevel(level_str)
                applied["log_level"] = level_str
            else:
                errors.append(f"Invalid log_level: {msg['log_level']}")

        # heartbeat_interval
        if "heartbeat_interval" in msg and msg["heartbeat_interval"] is not None:
            try:
                interval = int(msg["heartbeat_interval"])
                if 10 <= interval <= 300:
                    self.settings.heartbeat_interval = interval
                    applied["heartbeat_interval"] = interval
                else:
                    errors.append(f"heartbeat_interval must be 10-300, got {interval}")
            except (ValueError, TypeError):
                errors.append(f"Invalid heartbeat_interval: {msg['heartbeat_interval']}")

        # Persist to .env
        if applied:
            try:
                self.settings.save_to_env()
            except Exception as e:
                logger.error("Failed to save config to .env: %s", e)
                errors.append(f"Failed to persist: {e}")

        success = len(errors) == 0
        error_msg = "; ".join(errors) if errors else None
        logger.info("Config update applied: %s%s", applied, f" (errors: {error_msg})" if error_msg else "")

        await self._send({
            "type": "config_response",
            "success": success,
            "applied": applied,
            "error": error_msg,
        })

    async def _handle_ota_update(self, url: str, checksum: str, version: str):
        """Download and install an OTA update, reporting status to the server."""
        if self._ota_in_progress:
            logger.warning("OTA update already in progress, ignoring")
            return

        self._ota_in_progress = True
        try:
            await self._send_ota_status(version, "downloading")
            await asyncio.to_thread(perform_ota_update, url, checksum, version, self.settings.api_key)
            await self._send_ota_status(version, "completed")
            logger.info("OTA update to v%s completed, restarting service", version)
            request_restart()
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
        """Send periodic heartbeats.

        Sends both the legacy scalar ``printer_status`` (status of the default
        queue, for backward compatibility) and a ``printer_statuses`` dict with
        per-queue status when ``PRINTER_QUEUES`` is configured. Status values
        are CUPS-native: ``idle | printing | disabled | unknown``.
        """
        while True:
            try:
                # Scalar status = status of the default (legacy) printer
                printer_status = get_printer_status(self.settings.printer_name)

                # Per-queue statuses (new). Empty dict when no queues configured.
                printer_statuses: dict[str, str] = {}
                for queue_name in self.settings.printer_queues:
                    printer_statuses[queue_name] = get_printer_status(queue_name)

                uptime = int(time.monotonic() - self._start_time)

                await self._send({
                    "type": "heartbeat",
                    "gateway_id": self.settings.gateway_id,
                    "version": __version__,
                    "printer_status": printer_status,
                    "printer_statuses": printer_statuses,
                    "uptime": uptime,
                    "local_ip": _get_local_ip(),
                    "config": {
                        "printer_name": self.settings.printer_name,
                        "printer_queues": self.settings.printer_queues,
                        "dry_run": self.settings.dry_run,
                        "log_level": self.settings.log_level,
                        "heartbeat_interval": self.settings.heartbeat_interval,
                    },
                })
                logger.debug(
                    "Heartbeat sent (printer=%s, queues=%d, uptime=%ds)",
                    printer_status, len(printer_statuses), uptime,
                )
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
