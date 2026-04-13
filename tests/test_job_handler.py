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
        job = self._make_job()
        result = handle_print_job(job, self.printer_name, self.state_dir, dry_run=False)

        self.assertEqual(result["status"], "completed")
        mock_print.assert_called_once()
        call_kwargs = mock_print.call_args
        self.assertEqual(call_kwargs.kwargs.get("copies") or call_kwargs[1].get("copies", 1), 1)

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

    @patch("printbot.job_handler.list_printers")
    @patch("printbot.job_handler.print_pdf")
    def test_unknown_target_printer_preflight(self, mock_print, mock_list):
        """Unknown target_printer should fail fast with `unknown_printer` error."""
        mock_list.return_value = [
            {"name": "standaard"}, {"name": "briefpapier"},
        ]
        job = self._make_job(job_id="unknown-001")
        job["metadata"]["target_printer"] = "does-not-exist"

        result = handle_print_job(job, self.printer_name, self.state_dir, dry_run=False)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "unknown_printer")
        self.assertIn("does-not-exist", result["details"])
        mock_print.assert_not_called()

    @patch("printbot.job_handler.list_printers")
    @patch("printbot.job_handler.print_pdf")
    def test_known_target_printer_proceeds(self, mock_print, mock_list):
        """Known target_printer should pass pre-flight and invoke print_pdf."""
        mock_list.return_value = [
            {"name": "standaard"}, {"name": "briefpapier"},
        ]
        job = self._make_job(job_id="known-001")
        job["metadata"]["target_printer"] = "briefpapier"

        result = handle_print_job(job, self.printer_name, self.state_dir, dry_run=False)

        self.assertEqual(result["status"], "completed")
        mock_print.assert_called_once()
        # Confirm print_pdf was called with the target_printer, not the default
        kwargs = mock_print.call_args.kwargs
        self.assertEqual(kwargs.get("printer_name"), "briefpapier")

    @patch("printbot.job_handler.list_printers")
    @patch("printbot.job_handler.print_pdf")
    def test_no_target_printer_skips_preflight(self, mock_print, mock_list):
        """Jobs without explicit target_printer should not call list_printers."""
        job = self._make_job(job_id="default-001")
        # No target_printer in metadata

        result = handle_print_job(job, self.printer_name, self.state_dir, dry_run=False)

        self.assertEqual(result["status"], "completed")
        mock_list.assert_not_called()

    @patch("printbot.job_handler.list_printers")
    @patch("printbot.job_handler.print_pdf")
    def test_dry_run_skips_preflight(self, mock_print, mock_list):
        """In dry_run mode the pre-flight check should be skipped."""
        job = self._make_job(job_id="dry-001")
        job["metadata"]["target_printer"] = "whatever"

        result = handle_print_job(job, self.printer_name, self.state_dir, dry_run=True)

        self.assertEqual(result["status"], "completed")
        mock_list.assert_not_called()

    @patch("printbot.job_handler.list_printers", side_effect=RuntimeError("cups down"))
    @patch("printbot.job_handler.print_pdf")
    def test_preflight_failure_does_not_block(self, mock_print, mock_list):
        """If list_printers fails, pre-flight should not reject the job."""
        job = self._make_job(job_id="list-fail-001")
        job["metadata"]["target_printer"] = "briefpapier"

        result = handle_print_job(job, self.printer_name, self.state_dir, dry_run=False)

        # When list_printers fails we cannot validate, so we fall through to lp
        self.assertEqual(result["status"], "completed")
        mock_print.assert_called_once()


if __name__ == "__main__":
    unittest.main()
