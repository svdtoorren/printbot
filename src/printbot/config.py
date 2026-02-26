import os
from pathlib import Path
from dataclasses import dataclass

# Track which .env file was loaded
_loaded_env_path: Path | None = None

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
            _loaded_env_path = env_path.resolve()
            break
except ImportError:
    pass

# Map dataclass field names to .env variable names
_ENV_KEY_MAP = {
    "gateway_id": "GATEWAY_ID",
    "api_key": "API_KEY",
    "ws_url": "WS_URL",
    "printer_name": "PRINTER_NAME",
    "state_dir": "STATE_DIR",
    "heartbeat_interval": "HEARTBEAT_INTERVAL",
    "reconnect_delay": "RECONNECT_DELAY",
    "max_reconnect_delay": "MAX_RECONNECT_DELAY",
    "log_level": "LOG_LEVEL",
    "dry_run": "DRY_RUN",
}


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

    env_path: Path | None = _loaded_env_path

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

    def save_to_env(self, path: Path | None = None) -> None:
        """Persist current settings to the .env file.

        Reads the existing file, updates only keys that are already present
        (preserving comments and ordering), and writes it back.
        """
        target = path or self.env_path
        if target is None:
            raise RuntimeError("No .env path known; cannot save settings")

        target = Path(target)

        # Build a dict of current values keyed by env variable name
        values: dict[str, str] = {}
        for field_name, env_key in _ENV_KEY_MAP.items():
            val = getattr(self, field_name)
            if isinstance(val, bool):
                values[env_key] = "true" if val else "false"
            else:
                values[env_key] = str(val)

        # Read existing lines
        if target.exists():
            lines = target.read_text().splitlines(keepends=True)
        else:
            lines = []

        # Update lines in-place
        updated_keys: set[str] = set()
        new_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            # Skip blank/comment lines
            if not stripped or stripped.startswith("#"):
                new_lines.append(line)
                continue
            # Parse KEY=VALUE
            if "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in values:
                    # Preserve the original line ending
                    ending = "\n" if line.endswith("\n") else ""
                    new_lines.append(f"{key}={values[key]}{ending}")
                    updated_keys.add(key)
                    continue
            new_lines.append(line)

        # Append any keys that weren't already in the file
        for key, val in values.items():
            if key not in updated_keys:
                # Ensure file ends with newline before appending
                if new_lines and not new_lines[-1].endswith("\n"):
                    new_lines.append("\n")
                new_lines.append(f"{key}={val}\n")

        target.write_text("".join(new_lines))
