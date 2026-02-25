import hashlib
import logging
import os
import subprocess
import tarfile
import tempfile

import requests

logger = logging.getLogger(__name__)


def restart_service() -> None:
    """Restart the printbot systemd service."""
    logger.info("Restarting printbot service")
    subprocess.run(["sudo", "systemctl", "restart", "printbot"], check=True, timeout=30)


def perform_ota_update(url: str, checksum: str, version: str, api_key: str = "") -> None:
    """Download, verify, extract, and install an OTA update.

    Args:
        url: URL to download the .tar.gz update package
        checksum: Expected SHA-256 checksum (format: "sha256:<hex>")
        version: Version string for logging
        api_key: Optional API key for authenticated downloads
    """
    logger.info("Starting OTA update to version %s", version)

    expected_hash = checksum.removeprefix("sha256:")

    fd, tmp_path = tempfile.mkstemp(prefix="printbot_ota_", suffix=".tar.gz")
    try:
        os.close(fd)

        # Download
        logger.info("Downloading update from %s", url)
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        resp = requests.get(url, timeout=120, stream=True, headers=headers)
        resp.raise_for_status()
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        # Verify checksum
        sha256 = hashlib.sha256()
        with open(tmp_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        actual_hash = sha256.hexdigest()

        if actual_hash != expected_hash:
            raise ValueError(f"Checksum mismatch: expected {expected_hash}, got {actual_hash}")
        logger.info("Checksum verified")

        # Extract to /opt/printbot
        install_dir = "/opt/printbot"
        logger.info("Extracting to %s", install_dir)
        with tarfile.open(tmp_path, "r:gz") as tar:
            # Security: check for path traversal
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in member.name:
                    raise ValueError(f"Unsafe path in archive: {member.name}")
            tar.extractall(path=install_dir)

        # Install new requirements
        logger.info("Installing updated requirements")
        subprocess.run(
            ["/opt/printbot/.venv/bin/pip", "install", "-r", f"{install_dir}/requirements.txt"],
            check=True, capture_output=True, timeout=120,
        )

    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
