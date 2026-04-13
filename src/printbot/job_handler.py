import base64
import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timezone

from .printing import list_printers, print_pdf, print_raw

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

    title = metadata.get("title", f"Job {job_id[:8]}")
    target_printer = metadata.get("target_printer")
    effective_printer = target_printer or printer_name

    # Pre-flight check: if server explicitly specified a target_printer,
    # verify it exists on this gateway before invoking lp. This returns a
    # stable "unknown_printer" error that the admin UI can surface cleanly,
    # instead of relying on the raw CUPS error message.
    if target_printer and not dry_run:
        try:
            known = {p.get("name", "") for p in list_printers()}
        except Exception as e:
            logger.warning("Could not list printers for pre-flight check: %s", e)
            known = set()
        if known and target_printer not in known:
            logger.error(
                "Job %s: target_printer '%s' not found on gateway (known=%s)",
                job_id, target_printer, sorted(known),
            )
            return {
                "status": "failed",
                "error": "unknown_printer",
                "details": f"Queue '{target_printer}' not found on gateway",
            }

    if payload_type == "raw":
        if not effective_printer.strip():
            return {"status": "failed", "error": "No target printer specified for raw job"}
        fd, file_path = tempfile.mkstemp(prefix="printbot_", suffix=".prn")
        try:
            raw_bytes = base64.b64decode(payload)
            with os.fdopen(fd, "wb") as f:
                f.write(raw_bytes)
            logger.info("Job %s: raw print to '%s' (%d bytes)", job_id, effective_printer, len(raw_bytes))
            print_raw(
                printer_name=effective_printer,
                title=title,
                file_path=file_path,
                cleanup=True,
                dry_run=dry_run,
            )
            _mark_printed(db_path, job_id)
            return {"status": "completed"}
        except Exception as e:
            logger.exception("Job %s failed: %s", job_id, e)
            try:
                os.remove(file_path)
            except OSError:
                pass
            return {"status": "failed", "error": str(e)}

    elif payload_type == "pdf":
        copies = metadata.get("copies", 1)
        duplex = metadata.get("duplex", False)
        printer_options = metadata.get("printer_options")

        fd, pdf_path = tempfile.mkstemp(prefix="printbot_", suffix=".pdf")
        try:
            pdf_bytes = base64.b64decode(payload)
            with os.fdopen(fd, "wb") as f:
                f.write(pdf_bytes)

            logger.info("Job %s: printing '%s' (%d bytes, copies=%d, duplex=%s)", job_id, title, len(pdf_bytes), copies, duplex)

            print_pdf(
                printer_name=effective_printer,
                title=title,
                pdf_path=pdf_path,
                cleanup=True,
                copies=copies,
                duplex=duplex,
                dry_run=dry_run,
                printer_options=printer_options,
            )

            _mark_printed(db_path, job_id)
            logger.info("Job %s completed", job_id)
            return {"status": "completed"}

        except Exception as e:
            logger.exception("Job %s failed: %s", job_id, e)
            try:
                os.remove(pdf_path)
            except OSError:
                pass
            return {"status": "failed", "error": str(e)}

    else:
        return {"status": "failed", "error": f"Unsupported payload type: {payload_type}"}
