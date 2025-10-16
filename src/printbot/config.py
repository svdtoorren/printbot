import os
from dataclasses import dataclass

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
        missing = [k for k,v in self.__dict__.items() if isinstance(v,str) and not v]
        if missing:
            raise ValueError(f"Missing required settings: {', '.join(missing)}")
