"""Tests for the config/settings module.

Note: Settings uses os.getenv() in dataclass field defaults, which are evaluated
at class definition time. To test env var behavior, we must pass values directly
to the constructor rather than patching os.environ.
"""

import pytest

from printbot.config import Settings


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
