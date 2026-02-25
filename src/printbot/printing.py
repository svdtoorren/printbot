import logging
import os
import shlex
import subprocess

logger = logging.getLogger(__name__)


def print_pdf(
    printer_name: str,
    title: str,
    pdf_path: str,
    cleanup: bool = True,
    copies: int = 1,
    duplex: bool = False,
    dry_run: bool = False,
) -> None:
    """Print PDF file to CUPS printer.

    Args:
        printer_name: Name of the CUPS printer
        title: Job title for the print queue
        pdf_path: Path to the PDF file to print
        cleanup: If True, delete the PDF file after printing
        copies: Number of copies to print
        duplex: If True, enable two-sided printing
        dry_run: If True, simulate printing without actual CUPS command
    """
    if dry_run:
        logger.info("[DRY_RUN] Would print PDF to '%s': %s (copies=%d, duplex=%s)", printer_name, title, copies, duplex)
        if cleanup:
            try:
                os.remove(pdf_path)
            except OSError:
                pass
        return

    cmd_parts = [
        "lp",
        "-d", shlex.quote(printer_name),
        "-o", "media=A4",
        "-o", "orientation-requested=3",
        "-n", str(copies),
        "-t", shlex.quote(title),
    ]
    if duplex:
        cmd_parts.extend(["-o", "sides=two-sided-long-edge"])

    cmd_parts.append(shlex.quote(pdf_path))
    cmd = " ".join(cmd_parts)

    logger.info("Sending print job to CUPS: %s (copies=%d, duplex=%s)", title, copies, duplex)
    logger.debug("CUPS command: %s", cmd)

    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True, timeout=30)
        logger.info("Print job submitted to CUPS")
        if result.stdout:
            logger.debug("CUPS output: %s", result.stdout.strip())
    except subprocess.CalledProcessError as e:
        logger.error("CUPS command failed (exit %d): %s", e.returncode, e.stderr)
        raise RuntimeError(f"Failed to submit print job to CUPS: {e.stderr}") from e
    except subprocess.TimeoutExpired:
        logger.error("CUPS command timed out after 30 seconds")
        raise RuntimeError("Print job submission timed out") from None
    finally:
        if cleanup:
            try:
                os.remove(pdf_path)
            except OSError:
                pass


def discover_devices(timeout: int = 10) -> list[dict]:
    """Discover available CUPS devices using lpinfo.

    Returns a list of dicts with keys: uri, make_model, info.
    """
    FILTERED_SCHEMES = {"cups-brf", "implicitclass"}

    try:
        result = subprocess.run(
            ["lpinfo", "-l", "-v"],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError("CUPS is not installed (lpinfo not found)")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Device discovery timed out after {timeout}s")

    if result.returncode != 0:
        raise RuntimeError(f"lpinfo failed (exit {result.returncode}): {result.stderr.strip()}")

    devices = []
    current: dict | None = None

    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("Device:"):
            # Flush previous device
            if current and "uri" in current:
                devices.append(current)
            # Start new device — "Device: uri = ..."
            parts = line.split("=", 1)
            uri = parts[1].strip() if len(parts) == 2 else ""
            current = {"uri": uri, "make_model": "", "info": ""}
        elif current is not None and "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key == "make-and-model":
                current["make_model"] = value
            elif key == "info":
                current["info"] = value

    # Flush last device
    if current and "uri" in current:
        devices.append(current)

    # Filter out meta-backends and bare backend names
    devices = [
        d for d in devices
        if "://" in d["uri"]
        and d["uri"].split("://")[0] not in FILTERED_SCHEMES
    ]

    logger.info("Discovered %d device(s)", len(devices))
    return devices


def get_printer_status(printer_name: str) -> str:
    """Get printer status via lpstat. Returns 'idle', 'printing', or 'unknown'."""
    try:
        result = subprocess.run(
            ["lpstat", "-p", printer_name],
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout.lower()
        if "idle" in output:
            return "idle"
        elif "printing" in output:
            return "printing"
        elif "disabled" in output:
            return "disabled"
        return "unknown"
    except Exception:
        return "unknown"
