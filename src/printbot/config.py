import os
from pathlib import Path
from dataclasses import dataclass

# Load .env file if it exists (for local development and systemd EnvironmentFile)
try:
    from dotenv import load_dotenv
    env_paths = [
        Path(".env"),
        Path(__file__).parent.parent.parent / ".env",
        Path("/opt/printbot/.env"),
    ]
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            break
except ImportError:
    pass


@dataclass
class Settings:
    gateway_id: str = os.getenv("GATEWAY_ID", "")
    api_key: str = os.getenv("API_KEY", "")
    ws_url: str = os.getenv("WS_URL", "wss://printgateway.toorren.nl/ws/gateway")
    printer_name: str = os.getenv("PRINTER_NAME", "")
    state_dir: str = os.getenv("STATE_DIR", "/var/lib/printbot")
    heartbeat_interval: int = int(os.getenv("HEARTBEAT_INTERVAL", "30"))
    reconnect_delay: int = int(os.getenv("RECONNECT_DELAY", "5"))
    max_reconnect_delay: int = int(os.getenv("MAX_RECONNECT_DELAY", "300"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    dry_run: bool = os.getenv("DRY_RUN", "").lower() in ("true", "1", "yes")

    def validate(self):
        required = {
            "gateway_id": self.gateway_id,
            "api_key": self.api_key,
            "ws_url": self.ws_url,
            "printer_name": self.printer_name,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Missing required settings: {', '.join(missing)}")
