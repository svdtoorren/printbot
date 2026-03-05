import hashlib
import logging
import os
import signal
import shutil
import subprocess
import tarfile
import tempfile

import requests

logger = logging.getLogger(__name__)


def request_restart() -> None:
    """Request a service restart by sending SIGTERM to ourselves.

    Systemd will restart the service automatically (Restart=always),
    picking up the newly installed code.
    """
    logger.info("Sending SIGTERM to self for restart (pid=%d)", os.getpid())
    os.kill(os.getpid(), signal.SIGTERM)


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

        # Extract to temp dir, then install mirroring Ansible layout
        install_dir = "/opt/printbot"
        logger.info("Extracting update for %s", install_dir)
        with tempfile.TemporaryDirectory(prefix="printbot_ota_extract_") as extract_dir:
            with tarfile.open(tmp_path, "r:gz") as tar:
                for member in tar.getmembers():
                    if member.name.startswith("/") or ".." in member.name:
                        raise ValueError(f"Unsafe path in archive: {member.name}")
                tar.extractall(path=extract_dir)

            # GitHub archives have a single top-level directory
            entries = os.listdir(extract_dir)
            if len(entries) != 1 or not os.path.isdir(os.path.join(extract_dir, entries[0])):
                raise ValueError(f"Expected single top-level dir in archive, got: {entries}")
            archive_root = os.path.join(extract_dir, entries[0])

            # Mirror Ansible layout: src/printbot/ → /opt/printbot/printbot/
            src_pkg = os.path.join(archive_root, "src", "printbot")
            if not os.path.isdir(src_pkg):
                raise ValueError("Expected src/printbot/ in archive, not found")

            dest_pkg = os.path.join(install_dir, "printbot")
            if os.path.exists(dest_pkg):
                shutil.rmtree(dest_pkg)
            shutil.copytree(src_pkg, dest_pkg)

            # Copy requirements.txt
            src_req = os.path.join(archive_root, "requirements.txt")
            if os.path.isfile(src_req):
                shutil.copy2(src_req, os.path.join(install_dir, "requirements.txt"))

        # Write version file so heartbeat reports the correct version
        version_file = os.path.join(install_dir, "VERSION")
        with open(version_file, "w") as f:
            f.write(version)

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
