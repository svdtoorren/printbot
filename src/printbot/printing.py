import logging
import os
import re
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


def _parse_backend_output(stdout: str) -> list[dict]:
    """Parse CUPS backend device-listing output.

    Each line has the format:
        <class> <uri> "<make_model>" "<info>" "<device_id>" ""
    e.g.:
        network dnssd://Printer._ipp._tcp.local/ "Maker Model" "Printer" "MFG:...;" ""
    """
    import shlex as _shlex

    FILTERED_SCHEMES = {"cups-brf", "implicitclass"}

    devices = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            tokens = _shlex.split(line)
        except ValueError:
            continue
        if len(tokens) < 2:
            continue
        uri = tokens[1]
        if "://" not in uri:
            continue
        scheme = uri.split("://")[0]
        if scheme in FILTERED_SCHEMES:
            continue
        devices.append({
            "uri": uri,
            "make_model": tokens[2] if len(tokens) > 2 else "",
            "info": tokens[3] if len(tokens) > 3 else "",
        })

    return devices


_BACKEND_DIR = "/usr/lib/cups/backend"
_DISCOVERY_BACKENDS = ["dnssd", "snmp"]


def _discover_ipp_services(timeout: int = 10) -> list[dict]:
    """Discover IPP services via avahi-browse.

    The CUPS dnssd backend reports only one URI per printer, preferring
    _pdl-datastream over _ipp.  This supplements discovery with explicit
    _ipp._tcp browsing so users can add printers with driverless IPP
    Everywhere support.
    """
    try:
        result = subprocess.run(
            ["avahi-browse", "-rpt", "_ipp._tcp"],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        logger.debug("avahi-browse not found, skipping IPP service discovery")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("avahi-browse timed out after %ds", timeout)
        return []

    devices = []
    seen: set[str] = set()
    for line in result.stdout.splitlines():
        if not line.startswith("="):
            continue
        parts = line.split(";")
        if len(parts) < 10:
            continue
        # Format: =;iface;proto;name;type;domain;host;addr;port;txt...
        name = parts[3]
        domain = parts[5]  # local

        key = f"{name}._ipp._tcp.{domain}"
        if key in seen:
            continue
        seen.add(key)

        # Parse TXT records: "key1=val1" "key2=val2" ...
        txt_raw = ";".join(parts[9:])
        make_model = ""
        uuid = ""
        for field in re.findall(r'"([^"]*)"', txt_raw):
            if field.startswith("ty="):
                make_model = field[3:]
            elif field.startswith("UUID="):
                uuid = field[5:]

        uri = f"dnssd://{name}._ipp._tcp.{domain}/"
        if uuid:
            uri += f"?uuid={uuid}"

        devices.append({"uri": uri, "make_model": make_model, "info": name})

    return devices


def discover_devices(timeout: int = 15) -> list[dict]:
    """Discover available CUPS devices by running backends directly.

    lpinfo -v on CUPS 2.4.x fails to enumerate dnssd devices, so we
    invoke the backend(s) directly — each outputs discovered devices
    on stdout when called with no arguments.  Additionally discovers
    _ipp._tcp services via avahi-browse for driverless IPP support.

    Args:
        timeout: Subprocess timeout in seconds per backend.

    Returns a list of dicts with keys: uri, make_model, info.
    """
    devices = []
    for backend in _DISCOVERY_BACKENDS:
        backend_path = f"{_BACKEND_DIR}/{backend}"
        try:
            result = subprocess.run(
                [backend_path],
                capture_output=True, text=True, timeout=timeout,
            )
        except FileNotFoundError:
            logger.warning("Backend %s not found at %s", backend, backend_path)
            continue
        except subprocess.TimeoutExpired:
            logger.warning("Backend %s timed out after %ds", backend, timeout)
            continue

        if result.returncode != 0:
            logger.warning("Backend %s failed (exit %d): %s",
                           backend, result.returncode, result.stderr.strip())
            continue

        devices.extend(_parse_backend_output(result.stdout))

    # Supplement with avahi-browse for _ipp._tcp driverless URIs
    devices.extend(_discover_ipp_services(timeout=timeout))

    # Deduplicate by URI (dnssd backend and avahi-browse may overlap)
    seen_uris: set[str] = set()
    unique = []
    for dev in devices:
        if dev["uri"] not in seen_uris:
            seen_uris.add(dev["uri"])
            unique.append(dev)

    logger.info("Discovered %d device(s)", len(unique))
    return unique


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
