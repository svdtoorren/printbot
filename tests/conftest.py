"""Shared fixtures for printbot tests."""

import pytest

from printbot.config import Settings


@pytest.fixture
def mock_settings():
    """Settings instance configured for testing (DRY_RUN=true, test values)."""
    return Settings(
        gateway_id="test-gateway-001",
        api_key="test-api-key-abc123",
        ws_url="ws://localhost:8000/ws/gateway",
        printer_name="test-printer",
        printer_queues=[],
        state_dir="/tmp/printbot-test",
        heartbeat_interval=5,
        reconnect_delay=1,
        max_reconnect_delay=10,
        log_level="DEBUG",
        dry_run=True,
    )
