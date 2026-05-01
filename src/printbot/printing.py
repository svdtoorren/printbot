import logging
import os
import re
import shlex
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def _parse_lp_request_id(stdout: str) -> Optional[int]:
    """Extract the CUPS job-id from ``lp`` stdout under LC_ALL=C.

    Format is always ``request id is <queue>-<id> (<n> file(s))`` —
    deterministic in the C locale. Returns None if the line is absent or
    malformed (caller logs a warning and continues; we never crash on a
    missing id).
    """
    if not stdout:
        return None
    m = re.search(r"request id is \S+-(\d+)\b", stdout)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (ValueError, OverflowError):
        return None


def print_raw(
    printer_name: str,
    title: str,
    file_path: str,
    cleanup: bool = True,
    dry_run: bool = False,
) -> Optional[int]:
    """Send raw data to CUPS printer. Returns the assigned CUPS job-id, or None.

    None covers dry-run, parse failure, and the (unreachable) success-without-output case.
    """
    if dry_run:
        logger.info("[DRY_RUN] Would send raw data to '%s': %s", printer_name, title)
        if cleanup:
            try:
                os.remove(file_path)
            except OSError:
                pass
        return None

    cmd_parts = ["lp", "-o", "raw"]
    if printer_name.strip():
        cmd_parts.extend(["-d", shlex.quote(printer_name)])
    cmd_parts.extend(["-t", shlex.quote(title)])
    cmd_parts.append(shlex.quote(file_path))
    cmd = " ".join(cmd_parts)

    logger.info("Sending raw print job to CUPS queue '%s': %s", printer_name, title)
    logger.debug("CUPS command: %s", cmd)

    cups_job_id: Optional[int] = None
    try:
        # LC_ALL=C so "request id is …" stays in English regardless of host locale.
        result = subprocess.run(
            cmd, shell=True, check=True, capture_output=True, text=True,
            timeout=30, env=_c_locale_env(),
        )
        cups_job_id = _parse_lp_request_id(result.stdout)
        if cups_job_id is not None:
            logger.info("Raw print job submitted to CUPS as job-id %d", cups_job_id)
        else:
            logger.warning("Could not parse CUPS job-id from lp output: %r",
                           (result.stdout or "").strip())
        if result.stdout:
            logger.debug("CUPS output: %s", result.stdout.strip())
    except subprocess.CalledProcessError as e:
        logger.error("CUPS command failed (exit %d): %s", e.returncode, e.stderr)
        raise RuntimeError(f"Failed to submit raw print job: {e.stderr}") from e
    except subprocess.TimeoutExpired:
        logger.error("CUPS command timed out after 30 seconds")
        raise RuntimeError("Raw print job submission timed out") from None
    finally:
        if cleanup:
            try:
                os.remove(file_path)
            except OSError:
                pass

    return cups_job_id


def _parse_lpoptions_output(output: str) -> dict[str, str]:
    """Parse ``lpoptions -p <printer>`` output into a dict.

    The output format is space-separated key=value pairs where values
    containing spaces are single-quoted: ``key1=val1 key2='long value'``.
    """
    opts: dict[str, str] = {}
    for token in shlex.split(output):
        if "=" in token:
            k, v = token.split("=", 1)
            opts[k] = v
    return opts


def get_printer_defaults(printer_name: str) -> dict[str, str]:
    """Read current CUPS defaults for a printer via lpoptions."""
    try:
        result = subprocess.run(
            ["lpoptions", "-p", printer_name],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            logger.debug("lpoptions -p %s failed (exit %d)", printer_name, result.returncode)
            return {}
        return _parse_lpoptions_output(result.stdout)
    except Exception as e:
        logger.debug("Failed to read printer defaults for '%s': %s", printer_name, e)
        return {}


def print_pdf(
    printer_name: str,
    title: str,
    pdf_path: str,
    cleanup: bool = True,
    copies: int = 1,
    duplex: bool = False,
    dry_run: bool = False,
    printer_options: dict[str, str] | None = None,
) -> Optional[int]:
    """Print PDF file to CUPS printer. Returns the assigned CUPS job-id, or None.

    Args:
        printer_name: Name of the CUPS printer
        title: Job title for the print queue
        pdf_path: Path to the PDF file to print
        cleanup: If True, delete the PDF file after printing
        copies: Number of copies to print
        duplex: If True, enable two-sided printing
        dry_run: If True, simulate printing without actual CUPS command
        printer_options: Extra CUPS options that override printer defaults
    """
    if dry_run:
        logger.info("[DRY_RUN] Would print PDF to '%s': %s (copies=%d, duplex=%s)", printer_name, title, copies, duplex)
        if cleanup:
            try:
                os.remove(pdf_path)
            except OSError:
                pass
        return None

    # Build merged options: CUPS defaults -> server overrides -> hardcoded fallbacks
    defaults = get_printer_defaults(printer_name) if printer_name.strip() else {}
    merged = dict(defaults)
    if printer_options:
        merged.update(printer_options)
    # Hardcoded fallbacks only if not already set
    merged.setdefault("media", "A4")
    merged.setdefault("orientation-requested", "3")
    if duplex:
        merged["sides"] = "two-sided-long-edge"

    cmd_parts = ["lp"]
    if printer_name.strip():
        cmd_parts.extend(["-d", shlex.quote(printer_name)])
    for key, value in merged.items():
        cmd_parts.extend(["-o", f"{shlex.quote(key)}={shlex.quote(value)}"])
    cmd_parts.extend([
        "-n", str(copies),
        "-t", shlex.quote(title),
    ])

    cmd_parts.append(shlex.quote(pdf_path))
    cmd = " ".join(cmd_parts)

    logger.info("Sending print job to CUPS: %s (copies=%d, duplex=%s)", title, copies, duplex)
    logger.debug("CUPS command: %s", cmd)

    cups_job_id: Optional[int] = None
    try:
        # LC_ALL=C so "request id is …" stays in English regardless of host locale.
        result = subprocess.run(
            cmd, shell=True, check=True, capture_output=True, text=True,
            timeout=30, env=_c_locale_env(),
        )
        cups_job_id = _parse_lp_request_id(result.stdout)
        if cups_job_id is not None:
            logger.info("Print job submitted to CUPS as job-id %d", cups_job_id)
        else:
            logger.warning("Could not parse CUPS job-id from lp output: %r",
                           (result.stdout or "").strip())
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

    return cups_job_id


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
    # IPP Everywhere can't query attributes over raw sockets — use raw driver
    if model == "everywhere" and (
        "_pdl-datastream._tcp" in device_uri
        or device_uri.startswith("socket://")
    ):
        model = "raw"
        logger.info("URI is raw socket; using 'raw' model instead of 'everywhere'")
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


def list_printers() -> list[dict]:
    """List all CUPS printers with their status, URI, and default flag.

    Uses a single ``lpstat -p -v -d`` call to avoid sequential timeouts
    when cupsd is slow (worst case 10s instead of 30s with three calls).

    Returns a list of dicts with keys: name, uri, state, info, is_default.
    """
    printers: dict[str, dict] = {}
    default_name: str = ""

    try:
        result = subprocess.run(
            ["lpstat", "-p", "-v", "-d"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            # "printer <name> is idle/disabled/..."
            m = re.match(r"printer\s+(\S+)\s+(.*)", line)
            if m:
                name = m.group(1)
                rest = m.group(2).lower()
                if "idle" in rest:
                    state = "idle"
                elif "printing" in rest or "processing" in rest:
                    state = "processing"
                elif "disabled" in rest or "stopped" in rest:
                    state = "stopped"
                else:
                    state = "unknown"
                printers.setdefault(name, {"name": name, "uri": "", "state": "unknown", "info": "", "is_default": False})
                printers[name]["state"] = state
                continue

            # "device for <name>: <uri>"
            m = re.match(r"device for (\S+):\s+(\S+)", line)
            if m:
                name, uri = m.group(1), m.group(2)
                printers.setdefault(name, {"name": name, "uri": "", "state": "unknown", "info": "", "is_default": False})
                printers[name]["uri"] = uri
                continue

            # "system default destination: <name>"
            m = re.match(r"system default destination:\s+(\S+)", line)
            if m:
                default_name = m.group(1)
    except Exception as e:
        logger.warning("lpstat -pvd failed: %s", e)

    if default_name and default_name in printers:
        printers[default_name]["is_default"] = True

    printer_list = list(printers.values())
    logger.info("Listed %d CUPS printer(s)", len(printer_list))
    return printer_list


def remove_printer(printer_name: str) -> None:
    """Remove a printer from CUPS using lpadmin -x."""
    logger.info("Removing printer '%s'", printer_name)
    try:
        result = subprocess.run(
            ["lpadmin", "-x", printer_name],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        raise RuntimeError("CUPS is not installed (lpadmin not found)")
    except subprocess.TimeoutExpired:
        raise RuntimeError("lpadmin timed out after 30 seconds")

    if result.returncode != 0:
        error_msg = result.stderr.strip() or f"lpadmin exited with code {result.returncode}"
        raise RuntimeError(f"Failed to remove printer: {error_msg}")

    logger.info("Printer '%s' removed successfully", printer_name)


def set_default_printer(printer_name: str) -> None:
    """Set the default CUPS printer using lpadmin -d."""
    logger.info("Setting default printer to '%s'", printer_name)
    try:
        result = subprocess.run(
            ["lpadmin", "-d", printer_name],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        raise RuntimeError("CUPS is not installed (lpadmin not found)")
    except subprocess.TimeoutExpired:
        raise RuntimeError("lpadmin timed out after 30 seconds")

    if result.returncode != 0:
        error_msg = result.stderr.strip() or f"lpadmin exited with code {result.returncode}"
        raise RuntimeError(f"Failed to set default printer: {error_msg}")

    logger.info("Default printer set to '%s'", printer_name)


def get_printer_options(printer_name: str) -> dict:
    """Get printer options with current values and choices via lpoptions -l.

    Returns dict of {option_name: {"current": str, "choices": list[str]}}.
    """
    logger.info("Getting printer options for '%s'", printer_name)
    try:
        result = subprocess.run(
            ["lpoptions", "-p", printer_name, "-l"],
            capture_output=True, text=True, timeout=15,
        )
    except FileNotFoundError:
        raise RuntimeError("CUPS is not installed (lpoptions not found)")
    except subprocess.TimeoutExpired:
        raise RuntimeError("lpoptions timed out after 15 seconds")

    if result.returncode != 0:
        error_msg = result.stderr.strip() or f"lpoptions exited with code {result.returncode}"
        raise RuntimeError(f"Failed to get printer options: {error_msg}")

    options = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or "/" not in line or ":" not in line:
            continue
        # Format: optionName/Label: choice1 *defaultChoice choice2
        option_name = line.split("/", 1)[0]
        choices_part = line.split(":", 1)[1].strip()
        choices = []
        current = ""
        for token in choices_part.split():
            if token.startswith("*"):
                value = token[1:]
                current = value
                choices.append(value)
            else:
                choices.append(token)
        options[option_name] = {"current": current, "choices": choices}

    logger.info("Got %d option(s) for printer '%s'", len(options), printer_name)
    return options


def set_printer_options(printer_name: str, options: dict) -> None:
    """Set CUPS printer options via lpadmin -o.

    Args:
        printer_name: CUPS queue name
        options: Dict of option_name -> value, e.g. {"InputSlot": "Tray1"}
    """
    cmd = ["lpadmin", "-p", printer_name]
    for key, value in options.items():
        cmd.extend(["-o", f"{key}={value}"])

    logger.info("Setting printer options for '%s': %s", printer_name, options)
    logger.debug("lpadmin command: %s", cmd)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        raise RuntimeError("CUPS is not installed (lpadmin not found)")
    except subprocess.TimeoutExpired:
        raise RuntimeError("lpadmin timed out after 30 seconds")

    if result.returncode != 0:
        error_msg = result.stderr.strip() or f"lpadmin exited with code {result.returncode}"
        raise RuntimeError(f"Failed to set printer options: {error_msg}")

    logger.info("Printer options set successfully for '%s'", printer_name)


def get_printer_status(printer_name: str) -> str:
    """Get printer status via lpstat. Returns 'idle', 'printing', 'disabled', or 'unknown'."""
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


# --- CUPS queue control + diagnostics -------------------------------------

# Force C locale for lpstat parsing — CUPS formats timestamps using LC_TIME,
# so without this the parsing would break under non-English system locales.
def _c_locale_env() -> dict:
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    return env


def _run_admin(cmd: list[str], description: str, timeout: int = 30) -> None:
    """Run a CUPS admin command and raise RuntimeError with stderr on failure."""
    logger.info("%s: %s", description, " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise RuntimeError(f"CUPS command not found: {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"{cmd[0]} timed out after {timeout} seconds") from e

    if result.returncode != 0:
        error_msg = result.stderr.strip() or f"{cmd[0]} exited with code {result.returncode}"
        raise RuntimeError(f"{description} failed: {error_msg}")


def enable_printer(printer_name: str) -> None:
    """Enable (resume) a CUPS print queue via cupsenable."""
    _run_admin(["cupsenable", printer_name], f"Enable printer '{printer_name}'")


def _sanitize_reason(reason: str) -> str:
    """Make a reason safe for ``cupsdisable -r`` / ``cupsreject -r``.

    CUPS only accepts latin-1 reasons up to 255 chars; non-latin-1 codepoints
    are replaced with ``?`` so the call doesn't crash on UTF-8 emoji etc.
    """
    if not reason:
        return ""
    sanitized = reason.encode("latin-1", errors="replace").decode("latin-1")
    return sanitized[:255]


def disable_printer(printer_name: str, reason: str = "") -> None:
    """Disable (stop) a CUPS print queue via cupsdisable, optional reason."""
    cmd = ["cupsdisable"]
    if reason:
        cmd.extend(["-r", _sanitize_reason(reason)])
    cmd.append(printer_name)
    _run_admin(cmd, f"Disable printer '{printer_name}'")


def accept_jobs(printer_name: str) -> None:
    """Configure a CUPS queue to accept new jobs via cupsaccept."""
    _run_admin(["cupsaccept", printer_name], f"Accept jobs on '{printer_name}'")


def reject_jobs(printer_name: str, reason: str = "") -> None:
    """Configure a CUPS queue to reject new jobs via cupsreject, optional reason."""
    cmd = ["cupsreject"]
    if reason:
        cmd.extend(["-r", _sanitize_reason(reason)])
    cmd.append(printer_name)
    _run_admin(cmd, f"Reject jobs on '{printer_name}'")


def cancel_job(job_id: str | int, purge: bool = False) -> None:
    """Cancel a single CUPS job. job_id may be numeric ('42') or namespaced ('hp-42').

    If purge=True, also remove the job's data files (cancel -x).
    """
    cmd = ["cancel"]
    if purge:
        cmd.append("-x")
    cmd.append(str(job_id))
    _run_admin(cmd, f"Cancel job '{job_id}'")


def clear_queue(printer_name: str, purge: bool = False) -> None:
    """Cancel every pending job on a printer (cancel -a). purge=True removes data files."""
    cmd = ["cancel", "-a"]
    if purge:
        cmd.append("-x")
    cmd.append(printer_name)
    _run_admin(cmd, f"Clear queue '{printer_name}'")


def _parse_state_line(line: str) -> tuple[str, str]:
    """Map first line of ``lpstat -p`` output to (state, summary).

    State enum is the IPP/server-aligned set: idle | processing | stopped | unknown.
    """
    m = re.match(r"printer\s+\S+\s+(.*)", line)
    if not m:
        return "unknown", ""
    rest = m.group(1)
    lower = rest.lower()
    if "now printing" in lower or "processing" in lower:
        return "processing", rest
    if "is idle" in lower:
        return "idle", rest
    if "disabled" in lower or "stopped" in lower:
        return "stopped", rest
    return "unknown", rest


_REASON_KEYWORDS = (
    # Hardware state we want surfaced as machine-readable reasons even when
    # CUPS only printed them as a free-text message.
    "cover-open", "media-empty", "media-jam", "media-low",
    "marker-supply-empty", "marker-supply-low",
    "marker-waste-full", "marker-waste-almost-full",
    "toner-empty", "toner-low",
    "input-tray-missing", "output-tray-missing", "output-area-full",
    "offline-report", "paused", "spool-area-full",
    "shutdown", "timed-out", "connecting-to-device",
    "door-open", "fuser-over-temp", "fuser-under-temp",
    "interpreter-resource-unavailable",
)


def _extract_reasons(text: str) -> list[str]:
    """Pull IPP-style state-reason tokens from a free-form text blob.

    Looks for explicit ``Alerts:`` / ``reasons:`` lines and well-known keywords
    so we surface a usable state_reasons list regardless of CUPS version.
    """
    reasons: list[str] = []
    seen: set[str] = set()

    def add(token: str) -> None:
        token = token.strip().lower()
        if not token or token == "none" or token in seen:
            return
        seen.add(token)
        reasons.append(token)

    # Explicit reason/alert lines (CUPS dumps them indented).
    for label_match in re.finditer(r"(?im)^\s*(?:alerts|reasons)\s*:\s*(.+)$", text):
        for token in re.split(r"[,\s]+", label_match.group(1)):
            add(token)

    # Well-known reason keywords appearing anywhere in the blob (with optional
    # severity suffix). Strip the suffix when matching but keep it on the token.
    for keyword in _REASON_KEYWORDS:
        for match in re.finditer(
            rf"\b{re.escape(keyword)}(?:-error|-warning|-report)?\b",
            text,
            flags=re.IGNORECASE,
        ):
            add(match.group(0))

    return reasons


def get_printer_detail(printer_name: str) -> dict:
    """Get detailed CUPS queue diagnostics for a single printer.

    Returns a dict with keys:
      - state: "idle" | "processing" | "stopped" | "unknown"
      - state_reasons: list[str]  (IPP-style tokens, e.g. ["cover-open"])
      - accepting_jobs: bool
      - state_message: str  (free-text, may include reason from cupsdisable -r)
    """
    detail = {
        "state": "unknown",
        "state_reasons": [],
        "accepting_jobs": False,
        "state_message": "",
    }

    try:
        p = subprocess.run(
            ["lpstat", "-l", "-p", printer_name],
            capture_output=True, text=True, timeout=10, env=_c_locale_env(),
        )
    except Exception as e:
        logger.warning("lpstat -l -p %s failed: %s", printer_name, e)
        return detail

    lines = p.stdout.splitlines()
    if lines:
        first_line = lines[0].strip()
        state, summary = _parse_state_line(first_line)
        detail["state"] = state
        # Indented continuation lines after the state line carry the operator
        # message (from cupsdisable -r) and possibly Alerts/reasons output.
        message_parts = []
        for line in lines[1:]:
            if line.startswith((" ", "\t")):
                stripped = line.strip()
                if stripped and not stripped.startswith(("Description:", "Location:", "Connection:", "Interface:")):
                    message_parts.append(stripped)
            else:
                # Stop at the next non-indented block (defensive — shouldn't happen
                # for single-printer lpstat).
                break
        detail["state_message"] = " ".join(message_parts).strip()
        detail["state_reasons"] = _extract_reasons(p.stdout + " " + summary)

    try:
        a = subprocess.run(
            ["lpstat", "-a", printer_name],
            capture_output=True, text=True, timeout=10, env=_c_locale_env(),
        )
        detail["accepting_jobs"] = "not accepting" not in a.stdout.lower() and bool(a.stdout.strip())
    except Exception as e:
        logger.warning("lpstat -a %s failed: %s", printer_name, e)

    return detail


# Format under LC_ALL=C: "Mon Apr 24 10:00:00 2026" (asctime).
_LPSTAT_DATE_FMT = "%a %b %d %H:%M:%S %Y"


def _parse_lpstat_date(text: str) -> Optional[float]:
    """Parse the trailing date from an lpstat -o line into an epoch float, or None."""
    import time as _time
    text = text.strip()
    try:
        return _time.mktime(_time.strptime(text, _LPSTAT_DATE_FMT))
    except (ValueError, OverflowError):
        return None


def list_jobs(printer_name: str) -> list[dict]:
    """List pending+active jobs via ``lpstat -l -W not-completed -o``.

    Returns IPP-attribute kebab-case dicts in queue order (server-aligned schema):
      - "job-id" (int, REQUIRED)
      - "job-originating-user-name" (str)
      - "job-k-octets" (int)              # third lpstat column is k-octets
      - "time-at-creation" (Unix int)     # omitted on parse failure
      - "job-state" (str, default "pending")

    Fields the CLI cannot reliably surface (job-name title, job-state-reasons,
    document-format, …) are OMITTED — the server applies its own defaults.
    They will appear naturally once a pycups-based backend lands.
    """
    jobs: list[dict] = []
    try:
        result = subprocess.run(
            ["lpstat", "-l", "-W", "not-completed", "-o", printer_name],
            capture_output=True, text=True, timeout=10, env=_c_locale_env(),
        )
    except Exception as e:
        logger.warning("lpstat -l -W not-completed -o %s failed: %s", printer_name, e)
        return jobs

    if result.returncode != 0:
        # Empty queue still gives exit 0; non-zero means a real error
        # (unknown printer, cupsd unreachable).
        logger.debug("lpstat -l -W -o %s exited %d: %s",
                     printer_name, result.returncode, result.stderr.strip())
        return jobs

    # Header line: "<queue>-<id>  <user>  <kbytes>  <weekday> <mon> <day> HH:MM:SS YYYY"
    # With -l, indented detail lines follow each header — we skip those.
    pattern = re.compile(
        r"^(?P<jobname>\S+?)-(?P<job_id>\d+)\s+"
        r"(?P<user>\S+)\s+"
        r"(?P<size>\d+)\s+"
        r"(?P<date>.+?)\s*$"
    )
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        if line.startswith((" ", "\t")):
            continue  # detail line under a previous header
        m = pattern.match(line)
        if not m:
            logger.debug("Skipping unparseable lpstat -o line: %r", line)
            continue
        job: dict = {
            "job-id": int(m.group("job_id")),
            "job-originating-user-name": m.group("user"),
            "job-k-octets": int(m.group("size")),
            "job-state": "pending",
        }
        epoch = _parse_lpstat_date(m.group("date"))
        if epoch is not None:
            job["time-at-creation"] = int(epoch)
        jobs.append(job)

    logger.info("Listed %d pending job(s) on '%s'", len(jobs), printer_name)
    return jobs
