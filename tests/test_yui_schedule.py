"""Offline tests for daily schedule retries and explicit manual refreshes."""

import contextlib
import io
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yui_schedule
from yui_card import CardError


class YuiScheduleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.readme = Path(self.directory.name) / "README.md"
        self.write_note("2026-09-25")

    def write_note(self, day):
        self.readme.write_text(
            "# Existing profile\n<!-- YUI_START -->\n"
            + day + " · パパ、今日も一歩ずつ進みましょう。\n"
            "<!-- YUI_END -->\nOther content remains unchanged.\n",
            encoding="utf-8")

    def test_scheduled_run_skips_today_without_writing_files(self):
        before = self.readme.read_bytes()
        now = datetime(2026, 9, 25, 0, 17, tzinfo=timezone.utc)
        self.assertFalse(yui_schedule.needs_update(self.readme, "schedule", now))
        self.assertEqual(self.readme.read_bytes(), before)
        self.assertEqual(list(self.readme.parent.iterdir()), [self.readme])

    def test_scheduled_run_retries_yesterdays_note(self):
        self.write_note("2026-09-24")
        now = datetime(2026, 9, 25, 14, 17, tzinfo=timezone.utc)
        self.assertTrue(yui_schedule.needs_update(self.readme, "schedule", now))

    def test_manual_dispatch_forces_generation_even_when_today_is_present(self):
        now = datetime(2026, 9, 25, 0, 17, tzinfo=timezone.utc)
        self.assertTrue(yui_schedule.needs_update(self.readme, "workflow_dispatch", now))

    def test_delayed_retry_waits_until_jst_nine_after_midnight(self):
        before_midnight = datetime(2026, 9, 25, 14, 59, tzinfo=timezone.utc)
        after_midnight = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)
        before_nine = datetime(2026, 9, 25, 23, 59, tzinfo=timezone.utc)
        at_nine = datetime(2026, 9, 26, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(yui_schedule.needs_update(self.readme, "schedule", before_midnight))
        self.assertFalse(yui_schedule.needs_update(self.readme, "schedule", after_midnight))
        self.assertFalse(yui_schedule.needs_update(self.readme, "schedule", before_nine))
        self.assertTrue(yui_schedule.needs_update(self.readme, "schedule", at_nine))

    def test_manual_dispatch_is_allowed_before_jst_nine(self):
        now = datetime(2026, 9, 24, 16, 0, tzinfo=timezone.utc)  # JST September 25, 01:00
        self.assertTrue(yui_schedule.needs_update(self.readme, "workflow_dispatch", now))

    def test_future_note_date_fails_for_both_event_types(self):
        self.write_note("2026-09-26")
        before = self.readme.read_bytes()
        now = datetime(2026, 9, 25, 0, 17, tzinfo=timezone.utc)
        for event in ("schedule", "workflow_dispatch"):
            with self.subTest(event=event):
                with self.assertRaisesRegex(yui_schedule.ScheduleError, "future"):
                    yui_schedule.needs_update(self.readme, event, now)
                self.assertEqual(self.readme.read_bytes(), before)

    def test_invalid_note_fails_instead_of_silently_skipping(self):
        valid = self.readme.read_bytes()
        for broken in (b"missing markers",
                       valid + b"<!-- YUI_START -->\n",
                       valid.replace(b"2026-09-25", b"2026-02-30")):
            for event in ("schedule", "workflow_dispatch"):
                with self.subTest(event=event, broken=broken[:30]):
                    self.readme.write_bytes(broken)
                    with self.assertRaises(CardError):
                        yui_schedule.needs_update(self.readme, event)
                    self.assertEqual(self.readme.read_bytes(), broken)

    def test_cli_invalid_note_returns_failure_without_github_output(self):
        self.readme.write_text("invalid private content", encoding="utf-8")
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = yui_schedule.main(["--readme", str(self.readme), "--event", "schedule"])
        self.assertEqual(status, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("precheck failed", stderr.getvalue())
        self.assertNotIn("invalid private content", stderr.getvalue())

    def test_cli_emits_false_for_current_scheduled_note(self):
        stdout = io.StringIO()
        with patch.object(yui_schedule, "datetime") as clock, \
                contextlib.redirect_stdout(stdout):
            clock.now.return_value = datetime(2026, 9, 25, 0, 17, tzinfo=timezone.utc)
            status = yui_schedule.main(["--readme", str(self.readme), "--event", "schedule"])
        self.assertEqual(status, 0)
        self.assertEqual(stdout.getvalue(), "needs_update=false\n")

    def test_cli_emits_true_for_manual_dispatch(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = yui_schedule.main([
                "--readme", str(self.readme), "--event", "workflow_dispatch"])
        self.assertEqual(status, 0)
        self.assertEqual(stdout.getvalue(), "needs_update=true\n")


if __name__ == "__main__":
    unittest.main()
