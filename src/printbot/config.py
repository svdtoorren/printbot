import os
from pathlib import Path
from dataclasses import dataclass

# Load .env file if it exists (for local development and systemd EnvironmentFile)
try:
    from dotenv import load_dotenv
    # Try to load from common locations
    env_paths = [
        Path(".env"),  # Current directory
        Path(__file__).parent.parent.parent / ".env",  # Repository root
        Path("/opt/printbot/.env"),  # Production location
    ]
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            break
except ImportError:
    pass  # python-dotenv not installed, rely on environment variables

@dataclass
class Settings:
    tenant_id: str = os.getenv("TENANT_ID", "")
    client_id: str = os.getenv("CLIENT_ID", "")
    client_secret: str = os.getenv("CLIENT_SECRET", "")
    mailbox_upn: str = os.getenv("MAILBOX_UPN", "")
    mail_folder: str = os.getenv("MAIL_FOLDER", "PrintOrders")
    filter_sender: str = os.getenv("FILTER_SENDER", "")
    printer_name: str = os.getenv("PRINTER_NAME", "")
    poll_seconds: int = int(os.getenv("POLL_SECONDS", "60"))
    state_dir: str = os.getenv("STATE_DIR", "/var/lib/printbot")

    def validate(self):
        # List of optional fields that can be empty
        optional_fields = {'filter_sender'}

        # Check required string fields (exclude optional ones)
        missing = [k for k,v in self.__dict__.items()
                   if isinstance(v,str) and not v and k not in optional_fields]
        if missing:
            raise ValueError(f"Missing required settings: {', '.join(missing)}")
