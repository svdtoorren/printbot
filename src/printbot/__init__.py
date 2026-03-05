from pathlib import Path

_VERSION_FILE = Path("/opt/printbot/VERSION")

def _read_version() -> str:
    try:
        return _VERSION_FILE.read_text().strip()
    except OSError:
        return "0.4.0"

__version__ = _read_version()
