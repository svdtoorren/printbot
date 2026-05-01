"""Tests for job_handler module."""

import base64
import os
import tempfile
import unittest
from unittest.mock import patch

from printbot.job_handler import handle_print_job


# Minimal valid PDF
MINIMAL_PDF = b"%PDF-1.0\n1 0 obj<</Pages 2 0 R>>endobj\n2 0 obj<</Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</MediaBox[0 0 595 842]>>endobj\nxref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF"


class TestJobHandler(unittest.TestCase):
    def setUp(self):
        self.state_dir = tempfile.mkdtemp(prefix="printbot_test_")
        self.printer_name = "test-printer"

    def tearDown(self):
        # Clean up state dir
        import shutil
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _make_job(self, job_id="test-001", payload_type="pdf", copies=1, duplex=False):
        return {
            "type": "print",
            "job_id": job_id,
            "payload": base64.b64encode(MINIMAL_PDF).decode(),
            "payload_type": payload_type,
            "metadata": {
                "title": "Test Job",
                "copies": copies,
                "duplex": duplex,
            },
        }

    @patch("printbot.job_handler.print_pdf")
    def test_successful_print(self, mock_print):
        mock_print.return_value = 142
        job = self._make_job()
        result = handle_print_job(job, self.printer_name, self.state_dir, dry_run=False)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["cups_job_id"], 142)
        mock_print.assert_called_once()
        call_kwargs = mock_print.call_args
        self.assertEqual(call_kwargs.kwargs.get("copies") or call_kwargs[1].get("copies", 1), 1)

    @patch("printbot.job_handler.print_pdf")
    def test_successful_print_without_parseable_id(self, mock_print):
        # If lp output couldn't be parsed, cups_job_id is None — propagated as-is.
        mock_print.return_value = None
        job = self._make_job(job_id="no-id-001")
        result = handle_print_job(job, self.printer_name, self.state_dir, dry_run=False)

        self.assertEqual(result["status"], "completed")
        self.assertIsNone(result["cups_job_id"])

    @patch("printbot.job_handler.print_raw")
    def test_raw_print_propagates_cups_job_id(self, mock_print_raw):
        mock_print_raw.return_value = 55
        job = self._make_job(job_id="raw-001", payload_type="raw")
        result = handle_print_job(job, self.printer_name, self.state_dir, dry_run=False)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["cups_job_id"], 55)

    @patch("printbot.job_handler.print_pdf")
    def test_deduplication(self, mock_print):
        job = self._make_job(job_id="dedup-001")

        # First call: should print
        result1 = handle_print_job(job, self.printer_name, self.state_dir)
        self.assertEqual(result1["status"], "completed")
        self.assertEqual(mock_print.call_count, 1)

        # Second call: should skip (already printed)
        result2 = handle_print_job(job, self.printer_name, self.state_dir)
        self.assertEqual(result2["status"], "completed")
        self.assertEqual(mock_print.call_count, 1)  # Not called again

    def test_unsupported_payload_type(self):
        job = self._make_job(payload_type="escpos")
        result = handle_print_job(job, self.printer_name, self.state_dir)
        self.assertEqual(result["status"], "failed")
        self.assertIn("Unsupported payload type", result["error"])

    @patch("printbot.job_handler.print_pdf", side_effect=RuntimeError("CUPS error"))
    def test_print_failure(self, mock_print):
        job = self._make_job(job_id="fail-001")
        result = handle_print_job(job, self.printer_name, self.state_dir)
        self.assertEqual(result["status"], "failed")
        self.assertIn("CUPS error", result["error"])


if __name__ == "__main__":
    unittest.main()
