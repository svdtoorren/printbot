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
