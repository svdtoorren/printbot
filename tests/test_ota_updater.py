"""Tests for ota_updater module."""

import hashlib
import io
import os
import tarfile
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from printbot.ota_updater import perform_ota_update, request_restart


def _make_tar_gz(files: dict) -> bytes:
    """Create an in-memory .tar.gz with the given filename->content mapping."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _make_traversal_tar_gz() -> bytes:
    """Create a .tar.gz containing a path-traversal member."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="../etc/passwd")
        info.size = 4
        tar.addfile(info, io.BytesIO(b"evil"))
    return buf.getvalue()


class TestPerformOtaUpdate(unittest.TestCase):
    def setUp(self):
        self.install_dir = tempfile.mkdtemp(prefix="printbot_ota_test_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.install_dir, ignore_errors=True)

    @patch("printbot.ota_updater.subprocess.run")
    @patch("printbot.ota_updater.requests.get")
    def test_successful_update(self, mock_get, mock_run):
        # Build an archive matching GitHub tarball structure:
        # archive-root/src/printbot/__init__.py + archive-root/requirements.txt
        archive = _make_tar_gz({
            "printbot-abc123/requirements.txt": b"requests\n",
            "printbot-abc123/src/printbot/__init__.py": b"__version__ = '0.3.0'\n",
            "printbot-abc123/src/printbot/main.py": b"# main\n",
        })
        checksum = hashlib.sha256(archive).hexdigest()

        response = MagicMock()
        response.iter_content.return_value = [archive]
        response.raise_for_status = MagicMock()
        mock_get.return_value = response

        # Mock shutil ops and the version file write, but let real file I/O
        # happen for temp file download + checksum verification
        with patch("printbot.ota_updater.shutil.rmtree"), \
             patch("printbot.ota_updater.shutil.copytree"), \
             patch("printbot.ota_updater.shutil.copy2"):
            # Patch the version file write at /opt/printbot/VERSION
            original_open = open
            def patched_open(path, *args, **kwargs):
                if isinstance(path, str) and path == "/opt/printbot/VERSION":
                    return MagicMock()
                return original_open(path, *args, **kwargs)

            with patch("builtins.open", side_effect=patched_open):
                perform_ota_update(
                    url="https://example.com/update.tar.gz",
                    checksum=f"sha256:{checksum}",
                    version="0.3.0",
                )

        # pip install should have been called
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        self.assertIn("pip", args[0])
        self.assertIn("install", args)

    @patch("printbot.ota_updater.requests.get")
    def test_checksum_mismatch(self, mock_get):
        archive = _make_tar_gz({"requirements.txt": b"requests\n"})

        response = MagicMock()
        response.iter_content.return_value = [archive]
        response.raise_for_status = MagicMock()
        mock_get.return_value = response

        with self.assertRaises(ValueError) as ctx:
            perform_ota_update(
                url="https://example.com/update.tar.gz",
                checksum="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                version="0.3.0",
            )
        self.assertIn("Checksum mismatch", str(ctx.exception))

    @patch("printbot.ota_updater.requests.get")
    def test_path_traversal_blocked(self, mock_get):
        archive = _make_traversal_tar_gz()
        checksum = hashlib.sha256(archive).hexdigest()

        response = MagicMock()
        response.iter_content.return_value = [archive]
        response.raise_for_status = MagicMock()
        mock_get.return_value = response

        with self.assertRaises(ValueError) as ctx:
            perform_ota_update(
                url="https://example.com/update.tar.gz",
                checksum=f"sha256:{checksum}",
                version="0.3.0",
            )
        self.assertIn("Unsafe path", str(ctx.exception))

    @patch("printbot.ota_updater.requests.get")
    def test_download_failure(self, mock_get):
        from requests.exceptions import HTTPError

        response = MagicMock()
        response.raise_for_status.side_effect = HTTPError("404 Not Found")
        mock_get.return_value = response

        with self.assertRaises(HTTPError):
            perform_ota_update(
                url="https://example.com/missing.tar.gz",
                checksum="sha256:abc",
                version="0.3.0",
            )


class TestRequestRestart(unittest.TestCase):
    @patch("printbot.ota_updater.os.kill")
    @patch("printbot.ota_updater.os.getpid", return_value=12345)
    def test_request_restart_sends_sigterm(self, mock_getpid, mock_kill):
        import signal
        request_restart()
        mock_kill.assert_called_once_with(12345, signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
