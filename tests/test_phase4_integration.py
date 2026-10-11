"""
End-to-End Integration tests for Nova Phase 4 Productivity Tools.
Validates natural language processing and execution through NovaBrain:
- Notes management
- Reminders and duplicate prevention
- Clipboard utilities and privacy safeguards
- System diagnostics and slow PC analysis without termination
- Task scheduling and policy security verification
"""

import time
import tempfile
import unittest
from pathlib import Path

from nova.agent.brain import NovaBrain
from nova.agent.intent_parser import NovaIntent
from nova.tools.clipboard import ClipboardManager
from nova.tools.notes import NotesManager
from nova.tools.reminders import ReminderManager
from nova.tools.scheduler import TaskScheduler


class TestPhase4Integration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.notes_db = Path(self.temp_dir.name) / "notes.db"
        self.reminders_db = Path(self.temp_dir.name) / "reminders.db"
        self.schedules_db = Path(self.temp_dir.name) / "schedules.db"

        self.brain = NovaBrain(dry_run_power=True)
        # Point managers to test databases to avoid altering live user databases
        self.brain.notes_manager = NotesManager(db_path=self.notes_db)
        self.brain.reminder_manager = ReminderManager(db_path=self.reminders_db)
        self.brain.clipboard_manager = ClipboardManager(in_memory_fallback=True)
        self.brain.executor._notes_manager = self.brain.notes_manager
        self.brain.executor._reminder_manager = self.brain.reminder_manager
        self.brain.executor._clipboard_manager = self.brain.clipboard_manager
        self.brain.scheduler = TaskScheduler(db_path=self.schedules_db, executor=self.brain.executor)
        self.brain.executor._scheduler = self.brain.scheduler

        self.brain.initialize()

    def tearDown(self):
        self.brain.shutdown()
        self.temp_dir.cleanup()

    def test_notes_flow(self):
        # 1. Save note
        res1 = self.brain.process("Save a note that I need to revise operating systems tonight")
        self.assertTrue(res1.get("success"))
        self.assertIn("Saved note", res1.get("message", ""))

        # 2. List notes
        res2 = self.brain.process("List notes")
        self.assertTrue(res2.get("success"))
        self.assertIn("revise operating systems tonight", res2.get("message", ""))

        # 3. Search notes
        res3 = self.brain.process("Search notes for operating systems")
        self.assertTrue(res3.get("success"))
        self.assertIn("operating systems", res3.get("message", ""))

    def test_reminders_flow(self):
        # 1. Add reminder
        res1 = self.brain.process("Remind me at 8 PM to revise operating systems")
        self.assertTrue(res1.get("success"))
        self.assertIn("Reminder", res1.get("message", ""))
        self.assertIn("revise operating systems", res1.get("message", ""))

        # 2. Duplicate detection
        res_dup = self.brain.process("Remind me at 8 PM to revise operating systems")
        self.assertFalse(res_dup.get("success"))
        self.assertIn("duplicate", str(res_dup).lower())

        # 3. List reminders
        res2 = self.brain.process("List reminders")
        self.assertTrue(res2.get("success"))
        self.assertIn("revise operating systems", res2.get("message", ""))

        # 4. Complete reminder
        rem_id = res1.get("data", {}).get("id") or 1
        res3 = self.brain.process(f"Complete reminder {rem_id}")
        self.assertTrue(res3.get("success"))

    def test_clipboard_flow(self):
        # Set clipboard with normal text
        self.brain.clipboard_manager.set_clipboard_text("Important research summary from paper.")

        # Read clipboard
        read_res = self.brain.process("Read clipboard")
        self.assertTrue(read_res.get("success"))
        self.assertIn("Important research summary", read_res.get("message", ""))

        # Save clipboard as note
        save_note_res = self.brain.process("Save the current clipboard text as a note")
        self.assertTrue(save_note_res.get("success"))
        self.assertIn("Saved clipboard content as note", save_note_res.get("message", ""))

        # Verify in notes
        list_notes = self.brain.notes_manager.list_notes()
        self.assertEqual(list_notes.data["count"], 1)

    def test_clipboard_sensitive_masking_flow(self):
        # Set clipboard with sensitive token
        token = "ghp_123456789012345678901234567890123456"
        self.brain.clipboard_manager.set_clipboard_text(token)

        # Read clipboard should mask for safety
        read_res = self.brain.process("What's in my clipboard")
        self.assertTrue(read_res.get("success"))
        self.assertIn("SENSITIVE CONTENT DETECTED", read_res.get("message", ""))
        self.assertIn("****", read_res.get("message", ""))

    def test_system_diagnostics_flow(self):
        # Full diagnostics
        res_diag = self.brain.process("System diagnostics")
        self.assertTrue(res_diag.get("success"))
        self.assertIn("CPU Usage", res_diag.get("message", ""))
        self.assertIn("RAM Usage", res_diag.get("message", ""))

        # Check why computer is running slowly
        res_slow = self.brain.process("Check why my computer is running slowly")
        self.assertTrue(res_slow.get("success"))
        self.assertIn("Performance Analysis", res_slow.get("message", ""))
        self.assertIn("No processes terminated", res_slow.get("message", ""))

    def test_scheduled_task_flow(self):
        # Schedule approved task: "Every day at 9 AM, open my college project"
        sched_res = self.brain.process("Every day at 9 AM, open my college project")
        self.assertTrue(sched_res.get("success"))
        self.assertIn("scheduled", sched_res.get("message", "").lower())

        # List scheduled tasks
        list_sched = self.brain.process("List scheduled tasks")
        self.assertTrue(list_sched.get("success"))
        self.assertIn("Daily at 09:00", list_sched.get("message", ""))

        # Cancel schedule
        sched_id = sched_res.get("data", {}).get("id") or 1
        cancel_res = self.brain.process(f"Cancel scheduled task {sched_id}")
        self.assertTrue(cancel_res.get("success"))


if __name__ == "__main__":
    unittest.main()
