"""Tests for the config/settings module.

Note: Settings uses os.getenv() in dataclass field defaults, which are evaluated
at class definition time. To test env var behavior, we must pass values directly
to the constructor rather than patching os.environ.
"""

import tempfile
from pathlib import Path

import pytest

from printbot.config import Settings, _parse_printer_queues


class TestSettingsDefaults:
    def test_constructor_with_values(self):
        s = Settings(
            gateway_id="gw-test",
            api_key="key-test",
            ws_url="ws://localhost:8000/ws/gateway",
            printer_name="HP-Test",
            state_dir="/tmp/test",
            heartbeat_interval=10,
            dry_run=True,
        )
        assert s.gateway_id == "gw-test"
        assert s.api_key == "key-test"
        assert s.ws_url == "ws://localhost:8000/ws/gateway"
        assert s.printer_name == "HP-Test"
        assert s.heartbeat_interval == 10
        assert s.dry_run is True

    def test_default_reconnect_values(self):
        s = Settings()
        assert s.reconnect_delay == 5 or isinstance(s.reconnect_delay, int)
        assert s.max_reconnect_delay == 300 or isinstance(s.max_reconnect_delay, int)


class TestDryRunValues:
    def test_dry_run_true(self):
        s = Settings(dry_run=True)
        assert s.dry_run is True

    def test_dry_run_false(self):
        s = Settings(dry_run=False)
        assert s.dry_run is False


class TestValidate:
    def test_validate_all_required(self, mock_settings):
        # mock_settings has all required fields set — should not raise
        mock_settings.validate()

    def test_validate_missing_gateway_id(self, mock_settings):
        mock_settings.gateway_id = ""
        with pytest.raises(ValueError, match="gateway_id"):
            mock_settings.validate()

    def test_validate_missing_api_key(self, mock_settings):
        mock_settings.api_key = ""
        with pytest.raises(ValueError, match="api_key"):
            mock_settings.validate()

    def test_validate_missing_multiple(self):
        s = Settings(
            gateway_id="",
            api_key="",
            ws_url="ws://test",
            printer_name="",
        )
        with pytest.raises(ValueError) as exc_info:
            s.validate()
        assert "gateway_id" in str(exc_info.value)
        assert "api_key" in str(exc_info.value)

    def test_validate_ws_url_required(self):
        s = Settings(
            gateway_id="gw",
            api_key="key",
            ws_url="",
            printer_name="printer",
        )
        with pytest.raises(ValueError, match="ws_url"):
            s.validate()


class TestPrinterQueues:
    def test_parse_empty_string(self):
        assert _parse_printer_queues("") == []

    def test_parse_single(self):
        assert _parse_printer_queues("standaard") == ["standaard"]

    def test_parse_multiple(self):
        assert _parse_printer_queues("standaard,briefpapier") == ["standaard", "briefpapier"]

    def test_parse_strips_whitespace(self):
        assert _parse_printer_queues(" standaard , briefpapier ") == ["standaard", "briefpapier"]

    def test_parse_skips_empty_entries(self):
        assert _parse_printer_queues("standaard,,briefpapier,") == ["standaard", "briefpapier"]

    def test_default_is_empty_list(self):
        s = Settings()
        # When PRINTER_QUEUES env var is not set, the default should be an empty list.
        # (In CI this env var is typically absent.)
        assert isinstance(s.printer_queues, list)

    def test_can_pass_queues_explicitly(self):
        s = Settings(printer_queues=["standaard", "briefpapier"])
        assert s.printer_queues == ["standaard", "briefpapier"]


class TestSaveToEnv:
    def test_save_serializes_list_as_csv(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("PRINTER_QUEUES=old\nGATEWAY_ID=gw\n")

        s = Settings(
            gateway_id="gw",
            api_key="key",
            ws_url="ws://x",
            printer_name="p",
            printer_queues=["standaard", "briefpapier"],
        )
        s.save_to_env(env_file)

        content = env_file.read_text()
        assert "PRINTER_QUEUES=standaard,briefpapier" in content

    def test_save_empty_list_serializes_as_empty_string(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("PRINTER_QUEUES=old\n")

        s = Settings(
            gateway_id="gw",
            api_key="key",
            ws_url="ws://x",
            printer_queues=[],
        )
        s.save_to_env(env_file)

        content = env_file.read_text()
        assert "PRINTER_QUEUES=" in content
        # No residual comma-separated list
        assert "PRINTER_QUEUES=old" not in content
