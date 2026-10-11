"""
Unit tests for Nova Task Scheduler & Automation (Phase 4).
Validates persistent scheduling, restart recovery, execution of registered validated actions,
policy rejection of arbitrary/destructive commands, and background execution.
"""

import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from nova.tools.scheduler import TaskScheduler
from nova.agent.intent_parser import NovaIntent
from nova.core.results import ToolResult


class TestTaskScheduler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_schedules.db"
        self.mock_executor = MagicMock()
        self.mock_executor.execute_plan.return_value = ToolResult.ok(message="Mock task executed successfully")
        self.scheduler = TaskScheduler(db_path=self.db_path, executor=self.mock_executor)

    def tearDown(self):
        self.scheduler.stop()
        self.temp_dir.cleanup()

    def test_schedule_approved_action(self):
        res = self.scheduler.schedule_task(
            name="Open college project",
            intent=NovaIntent.OPEN_PROJECT,
            parameters={"project": "college project"},
            schedule_type="daily_at",
            time_of_day="09:00",
        )
        self.assertTrue(res.success)
        self.assertIn("scheduled", res.message.lower())
        sched_id = res.data["id"]

        list_res = self.scheduler.list_schedules()
        self.assertTrue(list_res.success)
        self.assertEqual(list_res.data["count"], 1)
        self.assertEqual(list_res.data["schedules"][0]["name"], "Open college project")

    def test_reject_unapproved_or_arbitrary_commands(self):
        # Destructive intent should be rejected by scheduler policy
        res_del = self.scheduler.schedule_task(
            name="Delete folder",
            intent=NovaIntent.DELETE_ITEM,
            parameters={"name": "ImportantFolder"},
            schedule_type="daily_at",
            time_of_day="09:00",
        )
        self.assertFalse(res_del.success)
        self.assertIn("not permitted", res_del.message.lower())

        # Arbitrary shell execution intent should be rejected
        res_shell = self.scheduler.schedule_task(
            name="Run bash script",
            intent="RUN_ARBITRARY_SHELL",
            parameters={"cmd": "rm -rf /"},
            schedule_type="daily_at",
            time_of_day="09:00",
        )
        self.assertFalse(res_shell.success)
        self.assertIn("not permitted", res_shell.message.lower())

    def test_cancel_pause_resume_schedule(self):
        res = self.scheduler.schedule_task(
            name="Open VS Code",
            intent=NovaIntent.OPEN_APP,
            parameters={"name": "code"},
            schedule_type="daily_at",
            time_of_day="10:00",
        )
        sched_id = res.data["id"]

        # Pause
        pause_res = self.scheduler.pause_schedule(sched_id)
        self.assertTrue(pause_res.success)
        self.assertFalse(pause_res.data["is_active"])

        # Resume
        resume_res = self.scheduler.resume_schedule(sched_id)
        self.assertTrue(resume_res.success)
        self.assertTrue(resume_res.data["is_active"])

        # Cancel
        cancel_res = self.scheduler.cancel_schedule(sched_id)
        self.assertTrue(cancel_res.success)

        # Confirm deleted
        list_res = self.scheduler.list_schedules()
        self.assertEqual(list_res.data["count"], 0)

    def test_task_execution_dispatch(self):
        # Schedule interval task due in the past
        past_target = time.time() - 5
        res = self.scheduler.schedule_task(
            name="Instant Summary",
            intent=NovaIntent.SUMMARIZE,
            parameters={"target_type": "context"},
            schedule_type="once",
            target_time=past_target,
        )
        self.assertTrue(res.success)

        # Run check_and_execute_due_tasks
        executed = self.scheduler.check_and_execute_due_tasks()
        self.assertEqual(len(executed), 1)
        self.assertEqual(executed[0]["name"], "Instant Summary")
        self.mock_executor.execute_plan.assert_called_once()

    def test_restart_recovery(self):
        # Schedule daily task
        res = self.scheduler.schedule_task(
            name="Daily Project Open",
            intent=NovaIntent.OPEN_PROJECT,
            parameters={"project": "CollegeProject"},
            schedule_type="daily_at",
            time_of_day="09:00",
        )
        self.assertTrue(res.success)

        # Simulate restart with a new TaskScheduler instance
        new_scheduler = TaskScheduler(db_path=self.db_path, executor=self.mock_executor)
        # Recover on startup
        recovered = new_scheduler.recover_on_startup()
        # Verify active task was retained
        list_res = new_scheduler.list_schedules(active_only=True)
        self.assertTrue(list_res.success)
        self.assertEqual(list_res.data["count"], 1)
        self.assertEqual(list_res.data["schedules"][0]["name"], "Daily Project Open")
        new_scheduler.stop()


if __name__ == "__main__":
    unittest.main()
