import os, sqlite3
from typing import Dict, Any
from .printing import print_pdf, html_to_pdf, text_to_pdf

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

        # Get email body
        body = msg.get('body') or {}
        ctype = body.get('contentType','text').lower()
        content = body.get('content','') or (msg.get('bodyPreview') or '')

        if not content.strip():
            content = f"(No content)\nSubject: {subject}\nFrom: {msg.get('from',{}).get('emailAddress',{}).get('address','')}\n"
            ctype = 'text'

        title = f"{subject} — {msg.get('receivedDateTime','')}"
        print(f"[Processor] Content type: {ctype}")
        print(f"[Processor] Converting to PDF and sending to printer: {self.printer_name}")

        # Convert to PDF based on content type
        try:
            if ctype == 'html':
                pdf_path = html_to_pdf(content, title)
                print(f"[Processor] HTML converted to PDF: {pdf_path}")
            else:
                pdf_path = text_to_pdf(content, title)
                print(f"[Processor] Text converted to PDF: {pdf_path}")

            # Print the PDF
            print_pdf(self.printer_name, title, pdf_path, cleanup=True)
            print(f"[Processor] Print job sent successfully for: {subject}")
            return imid
        except Exception as e:
            print(f"[Processor] ERROR: Failed to process message: {e}")
            raise
