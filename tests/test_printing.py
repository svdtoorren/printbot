"""Tests for printing module."""

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from printbot.printing import (
    accept_jobs,
    cancel_job,
    clear_queue,
    disable_printer,
    enable_printer,
    get_printer_detail,
    get_printer_status,
    list_jobs,
    print_pdf,
    reject_jobs,
    _extract_reasons,
    _parse_state_line,
)


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


class TestQueueAdminCommands(unittest.TestCase):
    """Wrappers around cupsenable/cupsdisable/cupsaccept/cupsreject/cancel."""

    def _ok(self):
        return MagicMock(returncode=0, stdout="", stderr="")

    def _fail(self, msg="boom"):
        return MagicMock(returncode=1, stdout="", stderr=msg)

    @patch("printbot.printing.subprocess.run")
    def test_enable_printer_invokes_cupsenable(self, mock_run):
        mock_run.return_value = self._ok()
        enable_printer("hp")
        self.assertEqual(mock_run.call_args[0][0], ["cupsenable", "hp"])

    @patch("printbot.printing.subprocess.run")
    def test_enable_printer_raises_on_failure(self, mock_run):
        mock_run.return_value = self._fail("lpadmin: Not authorized")
        with self.assertRaises(RuntimeError) as ctx:
            enable_printer("hp")
        self.assertIn("Not authorized", str(ctx.exception))

    @patch("printbot.printing.subprocess.run")
    def test_disable_printer_no_reason(self, mock_run):
        mock_run.return_value = self._ok()
        disable_printer("hp")
        self.assertEqual(mock_run.call_args[0][0], ["cupsdisable", "hp"])

    @patch("printbot.printing.subprocess.run")
    def test_disable_printer_with_reason(self, mock_run):
        mock_run.return_value = self._ok()
        disable_printer("hp", reason="maintenance")
        self.assertEqual(mock_run.call_args[0][0], ["cupsdisable", "-r", "maintenance", "hp"])

    @patch("printbot.printing.subprocess.run")
    def test_accept_jobs(self, mock_run):
        mock_run.return_value = self._ok()
        accept_jobs("hp")
        self.assertEqual(mock_run.call_args[0][0], ["cupsaccept", "hp"])

    @patch("printbot.printing.subprocess.run")
    def test_reject_jobs_with_reason(self, mock_run):
        mock_run.return_value = self._ok()
        reject_jobs("hp", reason="paper out")
        self.assertEqual(mock_run.call_args[0][0], ["cupsreject", "-r", "paper out", "hp"])

    @patch("printbot.printing.subprocess.run")
    def test_cancel_job_numeric(self, mock_run):
        mock_run.return_value = self._ok()
        cancel_job(42)
        self.assertEqual(mock_run.call_args[0][0], ["cancel", "42"])

    @patch("printbot.printing.subprocess.run")
    def test_cancel_job_namespaced_with_purge(self, mock_run):
        mock_run.return_value = self._ok()
        cancel_job("hp-42", purge=True)
        self.assertEqual(mock_run.call_args[0][0], ["cancel", "-x", "hp-42"])

    @patch("printbot.printing.subprocess.run")
    def test_clear_queue(self, mock_run):
        mock_run.return_value = self._ok()
        clear_queue("hp")
        self.assertEqual(mock_run.call_args[0][0], ["cancel", "-a", "hp"])

    @patch("printbot.printing.subprocess.run")
    def test_clear_queue_purge(self, mock_run):
        mock_run.return_value = self._ok()
        clear_queue("hp", purge=True)
        self.assertEqual(mock_run.call_args[0][0], ["cancel", "-a", "-x", "hp"])

    @patch("printbot.printing.subprocess.run", side_effect=FileNotFoundError())
    def test_missing_binary_raises(self, _mock_run):
        with self.assertRaises(RuntimeError) as ctx:
            enable_printer("hp")
        self.assertIn("not found", str(ctx.exception))


class TestParseStateLine(unittest.TestCase):
    def test_idle(self):
        state, summary = _parse_state_line("printer hp is idle.  enabled since Mon Apr 24 10:00:00 2026")
        self.assertEqual(state, "idle")
        self.assertIn("idle", summary)

    def test_printing(self):
        state, _ = _parse_state_line("printer hp now printing hp-42.  enabled since Mon Apr 24 10:00:00 2026")
        self.assertEqual(state, "printing")

    def test_disabled_means_stopped(self):
        state, _ = _parse_state_line("printer hp disabled since Mon Apr 24 10:00:00 2026 -")
        self.assertEqual(state, "stopped")

    def test_unrecognized(self):
        state, _ = _parse_state_line("garbage line")
        self.assertEqual(state, "unknown")


class TestExtractReasons(unittest.TestCase):
    def test_alerts_line(self):
        blob = "\tAlerts: cover-open, marker-supply-low-warning\n"
        reasons = _extract_reasons(blob)
        self.assertIn("cover-open", reasons)
        self.assertIn("marker-supply-low-warning", reasons)

    def test_reasons_label(self):
        blob = "\treasons: media-empty\n"
        self.assertIn("media-empty", _extract_reasons(blob))

    def test_keyword_in_message(self):
        blob = "Drum end of life — please replace; marker-supply-empty"
        self.assertIn("marker-supply-empty", _extract_reasons(blob))

    def test_none_filtered(self):
        blob = "\tAlerts: none\n"
        self.assertEqual(_extract_reasons(blob), [])

    def test_dedup(self):
        blob = "\tAlerts: cover-open, cover-open\n"
        self.assertEqual(_extract_reasons(blob).count("cover-open"), 1)


class TestGetPrinterDetail(unittest.TestCase):
    def _mock_lpstat(self, lp_l_p_stdout: str, lp_a_stdout: str):
        """Return a side_effect that returns different MagicMocks per call."""
        results = [
            MagicMock(returncode=0, stdout=lp_l_p_stdout, stderr=""),
            MagicMock(returncode=0, stdout=lp_a_stdout, stderr=""),
        ]
        return results

    @patch("printbot.printing.subprocess.run")
    def test_idle_accepting(self, mock_run):
        mock_run.side_effect = self._mock_lpstat(
            "printer hp is idle.  enabled since Mon Apr 24 10:00:00 2026\n"
            "\tDescription: HP\n"
            "\tLocation: Office\n",
            "hp accepting requests since Mon Apr 24 10:00:00 2026\n",
        )
        d = get_printer_detail("hp")
        self.assertEqual(d["state"], "idle")
        self.assertTrue(d["accepting_jobs"])
        self.assertEqual(d["state_reasons"], [])

    @patch("printbot.printing.subprocess.run")
    def test_stopped_with_reason(self, mock_run):
        mock_run.side_effect = self._mock_lpstat(
            "printer hp disabled since Mon Apr 24 10:00:00 2026 -\n"
            "\tDrum end of life — marker-supply-empty\n"
            "\tDescription: HP\n",
            "hp accepting requests since Mon Apr 24 10:00:00 2026\n",
        )
        d = get_printer_detail("hp")
        self.assertEqual(d["state"], "stopped")
        self.assertIn("marker-supply-empty", d["state_reasons"])
        self.assertIn("Drum end of life", d["state_message"])
        self.assertTrue(d["accepting_jobs"])

    @patch("printbot.printing.subprocess.run")
    def test_not_accepting_jobs(self, mock_run):
        mock_run.side_effect = self._mock_lpstat(
            "printer hp is idle.  enabled since Mon Apr 24 10:00:00 2026\n",
            "hp not accepting requests since Mon Apr 24 10:00:00 2026 -\n\tmaintenance window\n",
        )
        d = get_printer_detail("hp")
        self.assertFalse(d["accepting_jobs"])

    @patch("printbot.printing.subprocess.run", side_effect=Exception("no lpstat"))
    def test_lpstat_failure_returns_defaults(self, _mock_run):
        d = get_printer_detail("hp")
        self.assertEqual(d["state"], "unknown")
        self.assertEqual(d["state_reasons"], [])
        self.assertFalse(d["accepting_jobs"])

    @patch("printbot.printing.subprocess.run")
    def test_alerts_line_parsed(self, mock_run):
        mock_run.side_effect = self._mock_lpstat(
            "printer hp is idle.  enabled since Mon Apr 24 10:00:00 2026\n"
            "\tAlerts: cover-open, media-low\n",
            "hp accepting requests since Mon Apr 24 10:00:00 2026\n",
        )
        d = get_printer_detail("hp")
        self.assertIn("cover-open", d["state_reasons"])
        self.assertIn("media-low", d["state_reasons"])


class TestListJobs(unittest.TestCase):
    @patch("printbot.printing.subprocess.run")
    def test_empty_queue(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        self.assertEqual(list_jobs("hp"), [])

    @patch("printbot.printing.subprocess.run")
    def test_lpstat_failure_returns_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
        self.assertEqual(list_jobs("hp"), [])

    @patch("printbot.printing.subprocess.run")
    def test_parses_single_job(self, mock_run):
        # Date in 2020 → age_seconds will be huge; we just assert it's parsed (>0).
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="hp-42                 alice          12345   Mon Jan  6 10:00:00 2020\n",
            stderr="",
        )
        jobs = list_jobs("hp")
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job["job_id"], 42)
        self.assertEqual(job["job_name"], "hp-42")
        self.assertEqual(job["printer_name"], "hp")
        self.assertEqual(job["user"], "alice")
        self.assertEqual(job["size_bytes"], 12345)
        self.assertNotEqual(job["submitted_at"], "")
        self.assertGreater(job["age_seconds"], 0)

    @patch("printbot.printing.subprocess.run")
    def test_parses_multiple_jobs_preserves_order(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "hp-42                 alice          12345   Mon Jan  6 10:00:00 2020\n"
                "hp-43                 bob            54321   Mon Jan  6 10:01:00 2020\n"
                "hp-44                 carol          999     Mon Jan  6 10:02:00 2020\n"
            ),
            stderr="",
        )
        jobs = list_jobs("hp")
        self.assertEqual([j["job_id"] for j in jobs], [42, 43, 44])
        self.assertEqual([j["user"] for j in jobs], ["alice", "bob", "carol"])

    @patch("printbot.printing.subprocess.run")
    def test_handles_namespaced_printer(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="my-printer-99         alice          100     Mon Jan  6 10:00:00 2020\n",
            stderr="",
        )
        jobs = list_jobs("my-printer")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["job_id"], 99)
        self.assertEqual(jobs[0]["printer_name"], "my-printer")

    @patch("printbot.printing.subprocess.run")
    def test_skips_unparseable_lines(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "garbage line that doesnt match\n"
                "hp-42                 alice          12345   Mon Jan  6 10:00:00 2020\n"
            ),
            stderr="",
        )
        jobs = list_jobs("hp")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["job_id"], 42)

    @patch("printbot.printing.subprocess.run")
    def test_unparseable_date_marks_age_negative(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="hp-42                 alice          12345   not-a-date-at-all\n",
            stderr="",
        )
        jobs = list_jobs("hp")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["age_seconds"], -1)
        self.assertEqual(jobs[0]["submitted_at"], "")


if __name__ == "__main__":
    unittest.main()
