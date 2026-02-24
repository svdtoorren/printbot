import base64
import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timezone

from .printing import print_pdf

logger = logging.getLogger(__name__)

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS printed_jobs (
    job_id TEXT PRIMARY KEY,
    printed_utc TEXT NOT NULL
);
"""


def _init_db(state_dir: str) -> str:
    os.makedirs(state_dir, exist_ok=True)
    db_path = os.path.join(state_dir, "state.db")
    con = sqlite3.connect(db_path)
    try:
        con.execute(DB_SCHEMA)
        con.commit()
    finally:
        con.close()
    return db_path


def _already_printed(db_path: str, job_id: str) -> bool:
    con = sqlite3.connect(db_path)
    try:
        cur = con.execute("SELECT 1 FROM printed_jobs WHERE job_id = ?", (job_id,))
        return cur.fetchone() is not None
    finally:
        con.close()


def _mark_printed(db_path: str, job_id: str) -> None:
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            "INSERT OR IGNORE INTO printed_jobs (job_id, printed_utc) VALUES (?, ?)",
            (job_id, datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
    finally:
        con.close()


def handle_print_job(job: dict, printer_name: str, state_dir: str, dry_run: bool = False) -> dict:
    """Handle a print job received from the server.

    Args:
        job: WebSocket message with type=print, job_id, payload (base64 PDF), metadata
        printer_name: CUPS printer name
        state_dir: Directory for state database
        dry_run: Simulate printing

    Returns:
        {"status": "completed"} or {"status": "failed", "error": "..."}
    """
    job_id = job.get("job_id", "unknown")
    payload = job.get("payload", "")
    payload_type = job.get("payload_type", "pdf")
    metadata = job.get("metadata", {})

    db_path = _init_db(state_dir)

    # Deduplication
    if _already_printed(db_path, job_id):
        logger.info("Job %s already printed, skipping", job_id)
        return {"status": "completed"}

    if payload_type != "pdf":
        return {"status": "failed", "error": f"Unsupported payload type: {payload_type}"}

    title = metadata.get("title", f"Job {job_id[:8]}")
    copies = metadata.get("copies", 1)
    duplex = metadata.get("duplex", False)

    # Decode base64 PDF to temp file
    fd, pdf_path = tempfile.mkstemp(prefix="printbot_", suffix=".pdf")
    try:
        pdf_bytes = base64.b64decode(payload)
        with os.fdopen(fd, "wb") as f:
            f.write(pdf_bytes)

        logger.info("Job %s: printing '%s' (%d bytes, copies=%d, duplex=%s)", job_id, title, len(pdf_bytes), copies, duplex)

        print_pdf(
            printer_name=printer_name,
            title=title,
            pdf_path=pdf_path,
            cleanup=True,
            copies=copies,
            duplex=duplex,
            dry_run=dry_run,
        )

        _mark_printed(db_path, job_id)
        logger.info("Job %s completed", job_id)
        return {"status": "completed"}

    except Exception as e:
        logger.exception("Job %s failed: %s", job_id, e)
        # Clean up temp file on error
        try:
            os.remove(pdf_path)
        except OSError:
            pass
        return {"status": "failed", "error": str(e)}
