"""Tests for ota_updater module."""

import hashlib
import io
import os
import tarfile
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from printbot.ota_updater import perform_ota_update, restart_service


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
        archive = _make_tar_gz({"requirements.txt": b"requests\n"})
        checksum = hashlib.sha256(archive).hexdigest()

        response = MagicMock()
        response.iter_content.return_value = [archive]
        response.raise_for_status = MagicMock()
        mock_get.return_value = response

        with patch("printbot.ota_updater.tarfile.open") as mock_tar_open:
            mock_tar = MagicMock()
            member = MagicMock()
            member.name = "requirements.txt"
            mock_tar.getmembers.return_value = [member]
            mock_tar.__enter__ = MagicMock(return_value=mock_tar)
            mock_tar.__exit__ = MagicMock(return_value=False)
            mock_tar_open.return_value = mock_tar

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


class TestRestartService(unittest.TestCase):
    @patch("printbot.ota_updater.subprocess.run")
    def test_restart_service(self, mock_run):
        restart_service()
        mock_run.assert_called_once_with(
            ["sudo", "systemctl", "restart", "printbot"],
            check=True,
            timeout=30,
        )


if __name__ == "__main__":
    unittest.main()
