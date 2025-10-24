import os, sqlite3
from typing import Dict, Any
from .printing import print_text, html_to_text

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS printed (
  id TEXT PRIMARY KEY,
  printed_utc TEXT NOT NULL
);
"""

class Processor:
    def __init__(self, state_dir: str, printer_name: str):
        self.state_dir = state_dir
        self.printer_name = printer_name
        os.makedirs(state_dir, exist_ok=True)
        self.db_path = os.path.join(state_dir, 'state.db')
        self._init_db()

    def _init_db(self):
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(DB_SCHEMA)
            con.commit()
        finally:
            con.close()

    def already_printed(self, internet_message_id: str) -> bool:
        con = sqlite3.connect(self.db_path)
        try:
            cur = con.execute("SELECT 1 FROM printed WHERE id = ?", (internet_message_id,))
            return cur.fetchone() is not None
        finally:
            con.close()

    def mark_printed(self, internet_message_id: str):
        import datetime as dt
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("INSERT OR IGNORE INTO printed (id, printed_utc) VALUES (?, ?)",
                        (internet_message_id, dt.datetime.utcnow().isoformat()+"Z"))
            con.commit()
        finally:
            con.close()

    def handle_message(self, msg: Dict[str,Any]) -> str:
        """
        Process a message and send to printer.
        Returns the internet message ID if successful, None otherwise.
        Does NOT mark as printed - caller must do that after moving the message.
        """
        imid = msg.get('internetMessageId') or msg.get('id')
        if not imid:
            print("[Processor] Skipping message without ID")
            return None
        if self.already_printed(imid):
            print(f"[Processor] Message already printed: {msg.get('subject', 'no subject')}")
            return None
        subject = msg.get('subject') or 'Order'
        print(f"[Processor] Processing message: {subject}")
        body = msg.get('body') or {}
        ctype = body.get('contentType','text')
        content = body.get('content','') or (msg.get('bodyPreview') or '')
        if ctype.lower() == 'html':
            content = html_to_text(content)
        content = content.strip()
        if not content:
            content = f"(No content)\nSubject: {subject}\nFrom: {msg.get('from',{}).get('emailAddress',{}).get('address','')}\n"
        title = f"{subject} — {msg.get('receivedDateTime','')}"
        print(f"[Processor] Sending to printer: {self.printer_name}")
        print_text(self.printer_name, title, content)
        print(f"[Processor] Print job sent successfully for: {subject}")
        return imid
