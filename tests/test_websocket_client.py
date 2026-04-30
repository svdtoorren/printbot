"""Tests for the WebSocket client (GatewayClient)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from printbot.config import Settings
from printbot.websocket_client import GatewayClient, _build_printer_entry


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


class TestBuildPrinterEntry:
    """Per-printer heartbeat enrichment (PR2 wire-shape)."""

    @patch("printbot.websocket_client.list_printers")
    @patch("printbot.websocket_client.list_jobs")
    @patch("printbot.websocket_client.get_printer_detail")
    def test_full_entry_idle(self, mock_detail, mock_jobs, mock_printers):
        mock_detail.return_value = {
            "state": "idle",
            "state_reasons": [],
            "accepting_jobs": True,
            "state_message": "",
        }
        mock_jobs.return_value = []
        mock_printers.return_value = [
            {"name": "hp", "uri": "ipp://hp.local/", "state": "idle",
             "info": "HP Office", "is_default": True},
        ]

        entry = _build_printer_entry("hp")
        assert entry == {
            "name": "hp",
            "state": "idle",
            "state_reasons": [],
            "accepting_jobs": True,
            "cups_pending_jobs": 0,
            "oldest_job_age_seconds": None,
            "is_default": True,
            "uri": "ipp://hp.local/",
            "info": "HP Office",
        }

    @patch("printbot.websocket_client.list_printers")
    @patch("printbot.websocket_client.list_jobs")
    @patch("printbot.websocket_client.get_printer_detail")
    def test_stopped_with_reasons_and_pending_jobs(self, mock_detail, mock_jobs, mock_printers):
        mock_detail.return_value = {
            "state": "stopped",
            "state_reasons": ["marker-supply-empty"],
            "accepting_jobs": True,
            "state_message": "Drum end of life",
        }
        # Two pending jobs; oldest dictates age.
        import time as _time
        now = int(_time.time())
        mock_jobs.return_value = [
            {"job-id": 42, "time-at-creation": now - 600},
            {"job-id": 43, "time-at-creation": now - 120},
        ]
        mock_printers.return_value = [
            {"name": "hp", "uri": "", "state": "stopped", "info": "", "is_default": False},
        ]

        entry = _build_printer_entry("hp")
        assert entry["state"] == "stopped"
        assert entry["state_reasons"] == ["marker-supply-empty"]
        assert entry["cups_pending_jobs"] == 2
        # 600s ago, allow drift up to 5s for slow CI.
        assert 595 <= entry["oldest_job_age_seconds"] <= 605
        assert entry["is_default"] is False

    @patch("printbot.websocket_client.list_printers")
    @patch("printbot.websocket_client.list_jobs")
    @patch("printbot.websocket_client.get_printer_detail")
    def test_jobs_without_creation_time_skipped_for_age(self, mock_detail, mock_jobs, mock_printers):
        mock_detail.return_value = {
            "state": "idle", "state_reasons": [], "accepting_jobs": True, "state_message": "",
        }
        # Jobs with unparseable timestamps still count toward pending, but
        # cannot contribute to oldest_job_age_seconds.
        mock_jobs.return_value = [{"job-id": 1}, {"job-id": 2}]
        mock_printers.return_value = []

        entry = _build_printer_entry("hp")
        assert entry["cups_pending_jobs"] == 2
        assert entry["oldest_job_age_seconds"] is None

    @patch("printbot.websocket_client.list_printers")
    @patch("printbot.websocket_client.list_jobs")
    @patch("printbot.websocket_client.get_printer_detail")
    def test_uri_and_info_omitted_when_blank(self, mock_detail, mock_jobs, mock_printers):
        mock_detail.return_value = {
            "state": "idle", "state_reasons": [], "accepting_jobs": True, "state_message": "",
        }
        mock_jobs.return_value = []
        mock_printers.return_value = [
            {"name": "hp", "uri": "", "state": "idle", "info": "", "is_default": False},
        ]
        entry = _build_printer_entry("hp")
        assert "uri" not in entry
        assert "info" not in entry

    @patch("printbot.websocket_client.get_printer_detail", side_effect=RuntimeError("cupsd down"))
    def test_returns_none_on_cli_failure(self, _mock_detail):
        # Heartbeat keeps shipping (with an empty printers[] list) — never crashes.
        assert _build_printer_entry("hp") is None


class TestHeartbeatLoop:
    @patch("printbot.websocket_client._build_printer_entry")
    @patch("printbot.websocket_client.get_printer_status", return_value="idle")
    async def test_heartbeat_includes_printers_array(self, _mock_status, mock_build, client):
        mock_build.return_value = {
            "name": "test-printer",
            "state": "idle",
            "state_reasons": [],
            "accepting_jobs": True,
            "cups_pending_jobs": 0,
            "oldest_job_age_seconds": None,
            "is_default": True,
        }
        client._ws = AsyncMock()
        client._start_time = 0

        task = asyncio.create_task(client._heartbeat_loop())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["type"] == "heartbeat"
        # Back-compat scalar must still be present for v0.4.0 servers.
        assert sent["printer_status"] == "idle"
        # New per-printer array.
        assert sent["printers"] == [mock_build.return_value]
        # Server explicitly drops top-level aggregates — make sure we don't
        # accidentally start sending them.
        assert "printer_state_reasons" not in sent
        assert "accepting_jobs" not in sent
        assert "pending_jobs_count" not in sent
        assert "oldest_job_age_seconds" not in sent

    @patch("printbot.websocket_client._build_printer_entry", return_value=None)
    @patch("printbot.websocket_client.get_printer_status", return_value="unknown")
    async def test_heartbeat_empty_array_when_build_fails(self, _mock_status, _mock_build, client):
        client._ws = AsyncMock()
        client._start_time = 0

        task = asyncio.create_task(client._heartbeat_loop())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["printers"] == []
        # Heartbeat still went out — failures are tolerated.
        assert sent["type"] == "heartbeat"

    @patch("printbot.websocket_client._build_printer_entry")
    @patch("printbot.websocket_client.get_printer_status", return_value="idle")
    async def test_heartbeat_skips_build_when_no_printer_configured(
        self, _mock_status, mock_build, settings
    ):
        # printer_name="" → don't even call _build_printer_entry; just send empty array.
        settings.printer_name = ""
        client = GatewayClient(settings)
        client._ws = AsyncMock()
        client._start_time = 0

        task = asyncio.create_task(client._heartbeat_loop())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        mock_build.assert_not_called()
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["printers"] == []
