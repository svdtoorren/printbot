"""Tests for the WebSocket client (GatewayClient)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from printbot.config import Settings
from printbot.websocket_client import GatewayClient


@pytest.fixture
def settings():
    return Settings(
        gateway_id="test-gw-001",
        api_key="test-key",
        ws_url="ws://localhost:8000/ws/gateway",
        printer_name="test-printer",
        state_dir="/tmp/printbot-test",
        heartbeat_interval=5,
        reconnect_delay=1,
        max_reconnect_delay=10,
        dry_run=True,
    )


@pytest.fixture
def client(settings):
    return GatewayClient(settings)


class TestHandleMessage:
    async def test_print_message_queued(self, client):
        msg = {"type": "print", "job_id": "job-1", "payload": "base64data"}
        await client._handle_message(msg)
        assert client._job_queue.qsize() == 1
        queued = client._job_queue.get_nowait()
        assert queued["job_id"] == "job-1"

    async def test_ping_sends_pong(self, client):
        client._ws = AsyncMock()
        msg = {"type": "ping", "timestamp": "2025-01-01T00:00:00"}
        await client._handle_message(msg)
        client._ws.send.assert_called_once()
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["type"] == "pong"

    async def test_config_update_logged(self, client):
        # config_update is logged but no action — should not raise
        msg = {"type": "config_update", "printer_config": {"name": "new"}}
        await client._handle_message(msg)

    async def test_unknown_type_warning(self, client):
        msg = {"type": "unknown_type_xyz"}
        await client._handle_message(msg)  # should not raise

    @patch("printbot.websocket_client.discover_devices", return_value=[])
    async def test_discover_devices_creates_task(self, mock_discover, client):
        client._ws = AsyncMock()
        msg = {"type": "discover_devices", "request_id": "req-1", "timeout": 5}
        await client._handle_message(msg)
        # Give the created task a moment to run
        await asyncio.sleep(0.1)


class TestProcessJobs:
    @patch("printbot.websocket_client.handle_print_job")
    async def test_job_status_progression(self, mock_handle, client):
        """Jobs should send received → printing → completed."""
        mock_handle.return_value = {"status": "completed", "cups_job_id": 142}
        client._ws = AsyncMock()

        await client._job_queue.put({
            "type": "print",
            "job_id": "job-1",
            "payload": "data",
            "payload_type": "pdf",
            "metadata": {},
        })

        task = asyncio.create_task(client._process_jobs())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        calls = client._ws.send.call_args_list
        sent_msgs = [json.loads(c[0][0]) for c in calls]
        statuses = [m["status"] for m in sent_msgs if "status" in m]
        assert "received" in statuses
        assert "printing" in statuses
        assert "completed" in statuses

    @patch("printbot.websocket_client.handle_print_job")
    async def test_cups_job_id_propagates_from_printing_onward(self, mock_handle, client):
        """cups_job_id must appear from 'printing' through 'completed'.

        It is not present on 'received' (we haven't submitted yet — the id is
        only known after lp returns).
        """
        mock_handle.return_value = {"status": "completed", "cups_job_id": 273}
        client._ws = AsyncMock()

        await client._job_queue.put({
            "type": "print",
            "job_id": "job-273",
            "payload": "data",
            "payload_type": "pdf",
            "metadata": {},
        })

        task = asyncio.create_task(client._process_jobs())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        sent_msgs = [json.loads(c[0][0]) for c in client._ws.send.call_args_list]
        by_status = {m["status"]: m for m in sent_msgs if "status" in m}

        assert "cups_job_id" not in by_status["received"]
        assert by_status["printing"]["cups_job_id"] == 273
        assert by_status["completed"]["cups_job_id"] == 273

    @patch("printbot.websocket_client.handle_print_job")
    async def test_cups_job_id_omitted_when_unparseable(self, mock_handle, client):
        """If lp output couldn't be parsed, cups_job_id is omitted (not null)."""
        mock_handle.return_value = {"status": "completed", "cups_job_id": None}
        client._ws = AsyncMock()

        await client._job_queue.put({
            "type": "print",
            "job_id": "job-noid",
            "payload": "data",
            "payload_type": "pdf",
            "metadata": {},
        })

        task = asyncio.create_task(client._process_jobs())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        sent_msgs = [json.loads(c[0][0]) for c in client._ws.send.call_args_list]
        for m in sent_msgs:
            assert "cups_job_id" not in m

    @patch("printbot.websocket_client.handle_print_job")
    async def test_job_failure(self, mock_handle, client):
        mock_handle.return_value = {"status": "failed", "error": "CUPS error"}
        client._ws = AsyncMock()

        await client._job_queue.put({
            "type": "print",
            "job_id": "job-fail",
            "payload": "data",
            "payload_type": "pdf",
            "metadata": {},
        })

        task = asyncio.create_task(client._process_jobs())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        sent_msgs = [json.loads(c[0][0]) for c in client._ws.send.call_args_list]
        failed_msgs = [m for m in sent_msgs if m.get("status") == "failed"]
        assert len(failed_msgs) == 1
        assert failed_msgs[0]["error"] == "CUPS error"


class TestOtaGuard:
    async def test_ota_duplicate_blocked(self, client):
        """Second OTA request should be ignored while one is in progress."""
        client._ota_in_progress = True
        # This should return immediately without starting another OTA
        await client._handle_ota_update("http://example.com/ota.tar.gz", "sha256:abc", "0.5.0")
        # _ota_in_progress should still be True (not reset)
        assert client._ota_in_progress is True


class TestShutdown:
    async def test_shutdown_sets_running_false(self, client):
        client._running = True
        client._ws = AsyncMock()
        await client.shutdown()
        assert client._running is False
        client._ws.close.assert_called_once()

    async def test_shutdown_without_ws(self, client):
        client._running = True
        client._ws = None
        await client.shutdown()
        assert client._running is False
