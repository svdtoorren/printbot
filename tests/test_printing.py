"""Tests for printing module."""

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from printbot.printing import print_pdf, get_printer_status


class TestPrintPdf(unittest.TestCase):
    def setUp(self):
        # Create a temp PDF file for testing
        self.fd, self.pdf_path = tempfile.mkstemp(prefix="test_", suffix=".pdf")
        with os.fdopen(self.fd, "wb") as f:
            f.write(b"%PDF-1.0 test content")

    def tearDown(self):
        try:
            os.remove(self.pdf_path)
        except OSError:
            pass

    def test_dry_run(self):
        print_pdf("test-printer", "Test Job", self.pdf_path, cleanup=False, dry_run=True)
        # File should still exist with cleanup=False
        self.assertTrue(os.path.exists(self.pdf_path))

    def test_dry_run_with_cleanup(self):
        print_pdf("test-printer", "Test Job", self.pdf_path, cleanup=True, dry_run=True)
        # File should be cleaned up
        self.assertFalse(os.path.exists(self.pdf_path))

    @patch("printbot.printing.subprocess.run")
    def test_print_with_copies_and_duplex(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="request id is test-1")
        print_pdf("test-printer", "Test Job", self.pdf_path, cleanup=False, copies=3, duplex=True)

        cmd = mock_run.call_args[0][0]
        self.assertIn("-n 3", cmd)
        self.assertIn("sides=two-sided-long-edge", cmd)

    @patch("printbot.printing.subprocess.run")
    def test_print_without_duplex(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        print_pdf("test-printer", "Test Job", self.pdf_path, cleanup=False, copies=1, duplex=False)

        cmd = mock_run.call_args[0][0]
        self.assertNotIn("two-sided", cmd)


class TestGetPrinterStatus(unittest.TestCase):
    @patch("printbot.printing.subprocess.run")
    def test_idle_status(self, mock_run):
        mock_run.return_value = MagicMock(stdout="printer test-printer is idle.")
        self.assertEqual(get_printer_status("test-printer"), "idle")

    @patch("printbot.printing.subprocess.run")
    def test_printing_status(self, mock_run):
        mock_run.return_value = MagicMock(stdout="printer test-printer now printing.")
        self.assertEqual(get_printer_status("test-printer"), "printing")

    @patch("printbot.printing.subprocess.run", side_effect=Exception("no lpstat"))
    def test_error_returns_unknown(self, mock_run):
        self.assertEqual(get_printer_status("test-printer"), "unknown")


if __name__ == "__main__":
    unittest.main()
