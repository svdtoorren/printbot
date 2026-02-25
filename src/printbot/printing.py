import logging
import os
import shlex
import subprocess
from typing import Optional

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


def _parse_lpinfo_output(stdout: str) -> list[dict]:
    """Parse lpinfo -l -v output into a list of device dicts."""
    FILTERED_SCHEMES = {"cups-brf", "implicitclass"}

    devices = []
    current: Optional[dict] = None

    for line in stdout.splitlines():
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
    return [
        d for d in devices
        if "://" in d["uri"]
        and d["uri"].split("://")[0] not in FILTERED_SCHEMES
    ]


def discover_devices(timeout: int = 10) -> list[dict]:
    """Discover available CUPS devices using lpinfo.

    Args:
        timeout: Subprocess timeout in seconds.

    Returns a list of dicts with keys: uri, make_model, info.
    """
    cmd = ["lpinfo", "-l", "-v"]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError("CUPS is not installed (lpinfo not found)")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Device discovery timed out after {timeout}s")

    if result.returncode != 0:
        raise RuntimeError(f"lpinfo failed (exit {result.returncode}): {result.stderr.strip()}")

    devices = _parse_lpinfo_output(result.stdout)
    logger.info("Discovered %d device(s)", len(devices))
    return devices


def add_printer(
    printer_name: str,
    device_uri: str,
    ppd: str = "",
    description: str = "",
    location: str = "",
    options: Optional[dict] = None,
) -> None:
    """Add a printer to CUPS using lpadmin.

    Args:
        printer_name: CUPS queue name
        device_uri: Device URI (e.g. ipp://..., usb://...)
        ppd: PPD or model string; defaults to 'everywhere' (driverless IPP)
        description: Human-readable description
        location: Physical location string
        options: Additional CUPS options as key=value pairs
    """
    cmd = ["lpadmin", "-p", printer_name, "-v", device_uri]

    model = ppd.strip() if ppd else "everywhere"
    cmd.extend(["-m", model])

    if description:
        cmd.extend(["-D", description])
    if location:
        cmd.extend(["-L", location])

    cmd.append("-E")  # enable and accept jobs

    if options:
        for key, value in options.items():
            cmd.extend(["-o", f"{key}={value}"])

    logger.info("Adding printer '%s' (uri=%s, model=%s)", printer_name, device_uri, model)
    logger.debug("lpadmin command: %s", cmd)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        raise RuntimeError("CUPS is not installed (lpadmin not found)")
    except subprocess.TimeoutExpired:
        raise RuntimeError("lpadmin timed out after 30 seconds")

    if result.returncode != 0:
        error_msg = result.stderr.strip() or f"lpadmin exited with code {result.returncode}"
        raise RuntimeError(f"Failed to add printer: {error_msg}")

    logger.info("Printer '%s' added successfully", printer_name)


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
