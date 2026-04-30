"""Tests for message routing handlers in the WebSocket client."""

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
    c = GatewayClient(settings)
    c._ws = AsyncMock()
    return c


class TestCupsListPrinters:
    @patch("printbot.websocket_client.list_printers")
    async def test_success(self, mock_list, client):
        mock_list.return_value = [
            {"name": "HP-Printer", "uri": "ipp://...", "state": "idle", "is_default": True}
        ]
        await client._handle_cups_list_printers({"request_id": "req-1"})

        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["type"] == "cups_response"
        assert sent["request_id"] == "req-1"
        assert sent["success"] is True
        assert len(sent["data"]) == 1

    @patch("printbot.websocket_client.list_printers", side_effect=RuntimeError("lpstat failed"))
    async def test_failure(self, mock_list, client):
        await client._handle_cups_list_printers({"request_id": "req-2"})

        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is False
        assert "lpstat failed" in sent["error"]


class TestCupsAddPrinter:
    @patch("printbot.websocket_client.add_printer")
    async def test_success(self, mock_add, client):
        msg = {
            "request_id": "req-add",
            "printer_name": "new-printer",
            "device_uri": "ipp://192.168.1.50:631",
            "ppd": "",
            "description": "Office Printer",
            "location": "Floor 2",
        }
        await client._handle_cups_add_printer(msg)

        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is True
        mock_add.assert_called_once()

    @patch("printbot.websocket_client.add_printer", side_effect=RuntimeError("lpadmin error"))
    async def test_failure(self, mock_add, client):
        msg = {
            "request_id": "req-add-fail",
            "printer_name": "bad-printer",
            "device_uri": "ipp://bad",
        }
        await client._handle_cups_add_printer(msg)

        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is False
        assert "lpadmin error" in sent["error"]


class TestCupsRemovePrinter:
    @patch("printbot.websocket_client.remove_printer")
    async def test_success(self, mock_remove, client):
        await client._handle_cups_remove_printer({
            "request_id": "req-rm",
            "printer_name": "old-printer",
        })

        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is True
        mock_remove.assert_called_once_with("old-printer")


class TestCupsSetDefault:
    @patch("printbot.websocket_client.set_default_printer")
    async def test_success(self, mock_set, client):
        await client._handle_cups_set_default({
            "request_id": "req-default",
            "printer_name": "main-printer",
        })

        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is True
        mock_set.assert_called_once_with("main-printer")


class TestDiscoverDevices:
    @patch("printbot.websocket_client.discover_devices")
    async def test_success(self, mock_discover, client):
        mock_discover.return_value = [
            {"uri": "ipp://192.168.1.50", "make_model": "HP LaserJet", "info": "Office"}
        ]
        await client._handle_discover_devices("req-discover", timeout=5)

        calls = client._ws.send.call_args_list
        sent_msgs = [json.loads(c[0][0]) for c in calls]

        # Should have status messages and a final response
        response_msgs = [m for m in sent_msgs if m["type"] == "discover_devices_response"]
        assert len(response_msgs) == 1
        assert len(response_msgs[0]["devices"]) == 1

    @patch("printbot.websocket_client.discover_devices", side_effect=RuntimeError("backend failed"))
    async def test_failure(self, mock_discover, client):
        await client._handle_discover_devices("req-discover-fail", timeout=5)

        calls = client._ws.send.call_args_list
        sent_msgs = [json.loads(c[0][0]) for c in calls]
        response_msgs = [m for m in sent_msgs if m["type"] == "discover_devices_response"]
        assert len(response_msgs) == 1
        assert response_msgs[0]["error"] is not None


class TestCupsResumePrinter:
    """One-click recovery — cupsenable + cupsaccept on a stopped queue."""

    @patch("printbot.websocket_client.accept_jobs")
    @patch("printbot.websocket_client.enable_printer")
    async def test_success(self, mock_enable, mock_accept, client):
        await client._handle_cups_resume_printer({
            "request_id": "req-resume",
            "printer_name": "hp",
        })
        mock_enable.assert_called_once_with("hp")
        mock_accept.assert_called_once_with("hp")

        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["type"] == "cups_response"
        assert sent["request_id"] == "req-resume"
        assert sent["success"] is True
        assert sent["error"] is None

    @patch("printbot.websocket_client.accept_jobs")
    @patch("printbot.websocket_client.enable_printer", side_effect=RuntimeError("Not authorized"))
    async def test_enable_failure_short_circuits(self, mock_enable, mock_accept, client):
        await client._handle_cups_resume_printer({
            "request_id": "req-resume-fail",
            "printer_name": "hp",
        })
        # accept_jobs must not run if enable failed.
        mock_accept.assert_not_called()
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is False
        assert "Not authorized" in sent["error"]


class TestCupsEnablePrinter:
    @patch("printbot.websocket_client.enable_printer")
    async def test_success(self, mock_enable, client):
        await client._handle_cups_enable_printer({
            "request_id": "req-en", "printer_name": "hp",
        })
        mock_enable.assert_called_once_with("hp")
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is True

    @patch("printbot.websocket_client.enable_printer", side_effect=RuntimeError("cupsd down"))
    async def test_failure(self, mock_enable, client):
        await client._handle_cups_enable_printer({
            "request_id": "req-en-fail", "printer_name": "hp",
        })
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is False
        assert "cupsd down" in sent["error"]


class TestCupsDisablePrinter:
    @patch("printbot.websocket_client.disable_printer")
    async def test_success_with_reason(self, mock_disable, client):
        await client._handle_cups_disable_printer({
            "request_id": "req-dis",
            "printer_name": "hp",
            "reason": "maintenance",
        })
        mock_disable.assert_called_once_with("hp", "maintenance")
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is True

    @patch("printbot.websocket_client.disable_printer")
    async def test_success_no_reason(self, mock_disable, client):
        await client._handle_cups_disable_printer({
            "request_id": "req-dis-nor", "printer_name": "hp",
        })
        # Empty reason still passes through; printing.disable_printer skips -r when empty.
        mock_disable.assert_called_once_with("hp", "")

    @patch("printbot.websocket_client.disable_printer", side_effect=RuntimeError("not allowed"))
    async def test_failure(self, mock_disable, client):
        await client._handle_cups_disable_printer({
            "request_id": "req-dis-fail", "printer_name": "hp",
        })
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is False


class TestCupsAcceptJobs:
    @patch("printbot.websocket_client.accept_jobs")
    async def test_success(self, mock_accept, client):
        await client._handle_cups_accept_jobs({
            "request_id": "req-acc", "printer_name": "hp",
        })
        mock_accept.assert_called_once_with("hp")
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is True


class TestCupsRejectJobs:
    @patch("printbot.websocket_client.reject_jobs")
    async def test_success_with_reason(self, mock_reject, client):
        await client._handle_cups_reject_jobs({
            "request_id": "req-rej",
            "printer_name": "hp",
            "reason": "paper out",
        })
        mock_reject.assert_called_once_with("hp", "paper out")
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is True


class TestCupsListJobs:
    @patch("printbot.websocket_client.list_jobs")
    async def test_returns_jobs_under_jobs_key(self, mock_list, client):
        # Server contract: data shape is {"jobs": [...]}.
        mock_list.return_value = [
            {
                "job-id": 42,
                "job-originating-user-name": "alice",
                "job-k-octets": 24,
                "time-at-creation": 1745683200,
                "job-state": "pending",
            }
        ]
        await client._handle_cups_list_jobs({
            "request_id": "req-lj", "printer_name": "hp",
        })
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is True
        assert sent["data"] == {"jobs": [
            {
                "job-id": 42,
                "job-originating-user-name": "alice",
                "job-k-octets": 24,
                "time-at-creation": 1745683200,
                "job-state": "pending",
            }
        ]}

    @patch("printbot.websocket_client.list_jobs")
    async def test_empty_queue_returns_empty_list(self, mock_list, client):
        mock_list.return_value = []
        await client._handle_cups_list_jobs({
            "request_id": "req-lj-empty", "printer_name": "hp",
        })
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is True
        assert sent["data"] == {"jobs": []}

    @patch("printbot.websocket_client.list_jobs", side_effect=RuntimeError("no such printer"))
    async def test_failure(self, mock_list, client):
        await client._handle_cups_list_jobs({
            "request_id": "req-lj-fail", "printer_name": "ghost",
        })
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is False
        assert "no such printer" in sent["error"]


class TestCupsCancelJob:
    @patch("printbot.websocket_client.cancel_job")
    async def test_success_int_id(self, mock_cancel, client):
        await client._handle_cups_cancel_job({
            "request_id": "req-cnc", "job_id": 42,
        })
        mock_cancel.assert_called_once_with(42, False)
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is True

    @patch("printbot.websocket_client.cancel_job")
    async def test_success_namespaced_id_with_purge(self, mock_cancel, client):
        await client._handle_cups_cancel_job({
            "request_id": "req-cnc-purge",
            "job_id": "hp-42",
            "purge": True,
        })
        mock_cancel.assert_called_once_with("hp-42", True)

    @patch("printbot.websocket_client.cancel_job")
    async def test_missing_job_id_fails(self, mock_cancel, client):
        # Idempotency rule: surfaces a clear error rather than silently no-op.
        await client._handle_cups_cancel_job({"request_id": "req-cnc-noid"})
        mock_cancel.assert_not_called()
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is False
        assert "job_id is required" in sent["error"]

    @patch("printbot.websocket_client.cancel_job", side_effect=RuntimeError("job not found"))
    async def test_already_cancelled_returns_failure(self, mock_cancel, client):
        # Server-spec idempotency: cancel on already-canceled/completed job
        # surfaces "job not found" via success=False.
        await client._handle_cups_cancel_job({
            "request_id": "req-cnc-gone", "job_id": 999,
        })
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is False
        assert "job not found" in sent["error"]


class TestCupsClearQueue:
    @patch("printbot.websocket_client.clear_queue")
    async def test_success(self, mock_clear, client):
        await client._handle_cups_clear_queue({
            "request_id": "req-clr", "printer_name": "hp",
        })
        mock_clear.assert_called_once_with("hp", False)
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["success"] is True

    @patch("printbot.websocket_client.clear_queue")
    async def test_purge(self, mock_clear, client):
        await client._handle_cups_clear_queue({
            "request_id": "req-clr-p", "printer_name": "hp", "purge": True,
        })
        mock_clear.assert_called_once_with("hp", True)


class TestCupsControlDispatchInHandleMessage:
    """Smoke-test that _handle_message routes the new types to their handlers."""

    @patch("printbot.websocket_client.GatewayClient._handle_cups_resume_printer", new_callable=AsyncMock)
    async def test_resume_routed(self, mock_handler, client):
        msg = {"type": "cups_resume_printer", "request_id": "r", "printer_name": "hp"}
        await client._handle_message(msg)
        await asyncio.sleep(0)  # let create_task fire
        mock_handler.assert_called_once()

    @patch("printbot.websocket_client.GatewayClient._handle_cups_list_jobs", new_callable=AsyncMock)
    async def test_list_jobs_routed(self, mock_handler, client):
        msg = {"type": "cups_list_jobs", "request_id": "r", "printer_name": "hp"}
        await client._handle_message(msg)
        await asyncio.sleep(0)
        mock_handler.assert_called_once()

    @patch("printbot.websocket_client.GatewayClient._handle_cups_cancel_job", new_callable=AsyncMock)
    async def test_cancel_job_routed(self, mock_handler, client):
        msg = {"type": "cups_cancel_job", "request_id": "r", "job_id": 42}
        await client._handle_message(msg)
        await asyncio.sleep(0)
        mock_handler.assert_called_once()


class TestOtaStatusProgression:
    @patch("printbot.websocket_client.request_restart")
    @patch("printbot.websocket_client.perform_ota_update")
    async def test_success_flow(self, mock_perform, mock_restart, client):
        await client._handle_ota_update("http://example.com/ota.tar.gz", "sha256:abc", "0.5.0")

        calls = client._ws.send.call_args_list
        sent_msgs = [json.loads(c[0][0]) for c in calls]
        statuses = [m["status"] for m in sent_msgs if m["type"] == "ota_status"]
        assert "downloading" in statuses
        assert "completed" in statuses
        mock_restart.assert_called_once()

    @patch("printbot.websocket_client.perform_ota_update", side_effect=ValueError("Checksum mismatch"))
    async def test_failure_flow(self, mock_perform, client):
        await client._handle_ota_update("http://example.com/ota.tar.gz", "sha256:bad", "0.5.0")

        calls = client._ws.send.call_args_list
        sent_msgs = [json.loads(c[0][0]) for c in calls]
        failed_msgs = [m for m in sent_msgs if m.get("status") == "failed"]
        assert len(failed_msgs) == 1
        assert "Checksum mismatch" in failed_msgs[0]["error"]
