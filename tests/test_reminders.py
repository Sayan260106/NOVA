"""
Unit tests for Nova Reminders & Task Tracking (Phase 4).
Validates natural language time parsing, invalid dates handling, duplicate reminder rejection,
completion status, recurrence, background alerts, and SQLite restart persistence.
"""

import time
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta

from nova.tools.reminders import ReminderManager


class TestReminderManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_reminders.db"
        self.manager = ReminderManager(db_path=self.db_path)

    def tearDown(self):
        self.manager.stop_background_checker()
        self.temp_dir.cleanup()

    def test_parse_valid_due_times(self):
        # Relative
        ts, err = self.manager.parse_due_time("in 10 minutes")
        self.assertIsNone(err)
        self.assertGreater(ts, time.time())

        # Absolute 12-hour
        ts, err = self.manager.parse_due_time("at 8 PM")
        self.assertIsNone(err)
        self.assertIsNotNone(ts)

        # Tomorrow at 9 AM
        ts, err = self.manager.parse_due_time("tomorrow at 9 AM")
        self.assertIsNone(err)
        self.assertGreater(ts, time.time())

    def test_invalid_dates_handling(self):
        # Invalid hour
        ts, err = self.manager.parse_due_time("at 25:00")
        self.assertIsNone(ts)
        self.assertIn("Invalid 24-hour hour", err)

        # Invalid minute
        ts, err = self.manager.parse_due_time("at 8:99")
        self.assertIsNone(ts)
        self.assertIn("Invalid minute", err)

        # Empty string
        ts, err = self.manager.parse_due_time("")
        self.assertIsNone(ts)
        self.assertIn("empty", err.lower())

        # Unparseable gibberish
        ts, err = self.manager.parse_due_time("whenever you feel like it")
        self.assertIsNone(ts)
        self.assertIn("Could not parse", err)

        # Creating reminder with invalid time returns failed ToolResult
        res = self.manager.add_reminder("Invalid reminder", "not-a-date")
        self.assertFalse(res.success)
        self.assertIn("parsing error", res.message.lower())

    def test_duplicate_reminder_detection(self):
        # Add initial reminder
        res1 = self.manager.add_reminder("Revise operating systems", "tomorrow at 8 PM")
        self.assertTrue(res1.success)

        # Attempt to add exact duplicate
        res2 = self.manager.add_reminder("Revise operating systems", "tomorrow at 8 PM")
        self.assertFalse(res2.success)
        self.assertIn("duplicate", res2.error.lower())

        # Adding with allow_duplicate=True succeeds
        res3 = self.manager.add_reminder("Revise operating systems", "tomorrow at 8 PM", allow_duplicate=True)
        self.assertTrue(res3.success)

    def test_complete_and_dismiss_reminders(self):
        res = self.manager.add_reminder("Call doctor", "tomorrow at 10 AM")
        self.assertTrue(res.success)
        rem_id = res.data["id"]

        # Complete reminder
        comp_res = self.manager.complete_reminder(rem_id)
        self.assertTrue(comp_res.success)
        self.assertEqual(comp_res.data["status"], "completed")

        # It should no longer appear in default pending list
        list_res = self.manager.list_reminders()
        self.assertEqual(list_res.data["count"], 0)

        # It should appear when include_completed=True
        list_all = self.manager.list_reminders(include_completed=True)
        self.assertEqual(list_all.data["count"], 1)

    def test_recurrence_and_due_check(self):
        # Add an already due reminder with daily recurrence
        past_time = time.time() - 10
        res = self.manager.add_reminder("Daily morning check", past_time, recurrence="daily")
        self.assertTrue(res.success)
        rem_id = res.data["id"]

        # Run check_due_reminders
        triggered = self.manager.check_due_reminders()
        self.assertEqual(len(triggered), 1)
        self.assertEqual(triggered[0]["id"], rem_id)

        # Verify it was rescheduled for tomorrow
        list_res = self.manager.list_reminders()
        self.assertEqual(list_res.data["count"], 1)
        rescheduled = list_res.data["reminders"][0]
        self.assertEqual(rescheduled["status"], "pending")
        self.assertGreater(rescheduled["due_time"], time.time())

    def test_persistence_across_restarts(self):
        self.manager.add_reminder("Persistent reminder", "tomorrow at 5 PM")

        # Create new manager instance simulating restart
        new_manager = ReminderManager(db_path=self.db_path)
        list_res = new_manager.list_reminders()
        self.assertTrue(list_res.success)
        self.assertEqual(list_res.data["count"], 1)
        self.assertEqual(list_res.data["reminders"][0]["message"], "Persistent reminder")


if __name__ == "__main__":
    unittest.main()
