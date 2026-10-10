"""
Tests for Phase 3: PersistentMemory and ActionHistory.
Verifies persistence across restarts, query methods, audit logging,
pre-flight rollback validation, collision protection, and graceful error handling.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from nova.core.memory import PersistentMemory
from nova.core.action_history import ActionHistory
from nova.agent.intent_parser import NovaIntent
from nova.agent.policy import NovaPolicy
from nova.system.file_manager import FileManager


class TestPersistentMemory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="nova_mem_test_")
        self.db_path = Path(self.temp_dir) / "test_memory.db"
        self.memory = PersistentMemory(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_basic_crud(self):
        # Set preference
        self.memory.set("editor", "VS Code", category="preference")
        self.assertEqual(self.memory.get("editor", category="preference"), "VS Code")

        # Update preference
        self.memory.set("editor", "PyCharm", category="preference")
        self.assertEqual(self.memory.get("editor", category="preference"), "PyCharm")

        # Delete preference
        self.assertTrue(self.memory.delete("editor", category="preference"))
        self.assertIsNone(self.memory.get("editor", category="preference"))

    def test_project_locations(self):
        proj_dir = (Path(self.temp_dir) / "MyProject").resolve()
        proj_dir.mkdir()
        self.memory.set_project_location("nova", str(proj_dir))
        self.assertEqual(Path(self.memory.get_project_location("nova")).resolve(), proj_dir)
        self.assertEqual(Path(self.memory.get_project_location("NOVA")).resolve(), proj_dir)

        projects = self.memory.list_projects()
        self.assertIn("nova", projects)
        self.assertEqual(Path(projects["nova"]).resolve(), proj_dir)

        self.assertTrue(self.memory.delete_project_location("nova"))
        self.assertIsNone(self.memory.get_project_location("nova"))

    def test_app_aliases_and_common_dirs(self):
        self.memory.set_app_alias("browser", "Google Chrome")
        self.assertEqual(self.memory.get_app_alias("browser"), "Google Chrome")

        self.memory.set_common_directory("downloads", "D:/Downloads")
        self.assertEqual(Path(self.memory.get_common_directory("downloads")), Path("D:/Downloads"))

        all_mems = self.memory.list_all()
        categories = {item["category"] for item in all_mems}
        self.assertIn("app_alias", categories)
        self.assertIn("common_directory", categories)

    def test_persistence_across_restarts(self):
        # Store preferences in memory instance 1
        self.memory.set_project_location("jarvis", "D:/Projects/Jarvis")
        self.memory.set("theme", "dark", category="preference")

        # Instantiate brand-new PersistentMemory pointing to same database
        restarted_memory = PersistentMemory(db_path=self.db_path)
        self.assertEqual(Path(restarted_memory.get_project_location("jarvis")), Path("D:/Projects/Jarvis"))
        self.assertEqual(restarted_memory.get("theme", category="preference"), "dark")

    def test_clear_all_and_category(self):
        self.memory.set("k1", "v1", category="c1")
        self.memory.set("k2", "v2", category="c2")
        self.memory.clear_category("c1")
        self.assertIsNone(self.memory.get("k1", category="c1"))
        self.assertEqual(self.memory.get("k2", category="c2"), "v2")

        self.memory.clear_all()
        self.assertEqual(self.memory.list_all(), [])


class TestActionHistoryAndRollback(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="nova_hist_test_")
        self.db_path = Path(self.temp_dir) / "test_history.db"
        self.history = ActionHistory(db_path=self.db_path)
        self.file_manager = FileManager(default_root=Path(self.temp_dir))
        self.policy = NovaPolicy()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_record_and_query_actions(self):
        self.history.record_action(
            command="move file doc.txt to Archive",
            intent=NovaIntent.MOVE_ITEM,
            planned_operations=[{"step_id": 1, "action": "move_item"}],
            affected_paths=["D:/doc.txt", "D:/Archive/doc.txt"],
            success=True,
            result_message="Moved doc.txt to Archive",
        )

        today_actions = self.history.get_actions_today()
        self.assertEqual(len(today_actions), 1)
        self.assertEqual(today_actions[0]["intent"], NovaIntent.MOVE_ITEM)
        self.assertEqual(today_actions[0]["command"], "move file doc.txt to Archive")

        # Filter by intent
        move_actions = self.history.get_actions_today(intent=NovaIntent.MOVE_ITEM)
        self.assertEqual(len(move_actions), 1)
        rename_actions = self.history.get_actions_today(intent=NovaIntent.RENAME_ITEM)
        self.assertEqual(len(rename_actions), 0)

    def test_safe_rollback_file_move(self):
        # Create a file and move it
        src_file = Path(self.temp_dir) / "data.csv"
        src_file.write_text("col1,col2\n1,2", encoding="utf-8")
        dest_dir = Path(self.temp_dir) / "Backup"
        dest_dir.mkdir()

        # Perform move
        res = self.file_manager.move_item("data.csv", "Backup")
        self.assertTrue(res.success)
        self.assertIsNotNone(res.undo_info)

        # Record action
        action_id = self.history.record_action(
            command="move data.csv to Backup",
            intent=NovaIntent.MOVE_ITEM,
            planned_operations=[{"step_id": 1, "action": "move_item"}],
            affected_paths=[str(src_file), str(dest_dir / "data.csv")],
            success=True,
            undo_info=res.undo_info,
        )

        # Fetch last undoable action
        record = self.history.get_last_undoable_action()
        self.assertIsNotNone(record)
        self.assertEqual(record["id"], action_id)

        # Validate rollback pre-flight
        is_valid, err = self.history.validate_rollback(record["undo_info"], policy=self.policy)
        self.assertTrue(is_valid)
        self.assertIsNone(err)

        # Execute rollback
        rollback_res = self.history.execute_rollback(record, file_manager=self.file_manager, policy=self.policy)
        self.assertTrue(rollback_res.success)
        self.assertTrue(src_file.exists())
        self.assertFalse((dest_dir / "data.csv").exists())

        # Ensure action is marked undone and no longer returned as undoable
        record_after = self.history.get_last_undoable_action()
        self.assertIsNone(record_after)

    def test_rollback_collision_prevention(self):
        # Move file A to B
        src_file = Path(self.temp_dir) / "notes.txt"
        src_file.write_text("original notes", encoding="utf-8")
        dest_dir = Path(self.temp_dir) / "Archive"
        dest_dir.mkdir()

        res = self.file_manager.move_item("notes.txt", "Archive")
        self.assertTrue(res.success)

        self.history.record_action(
            command="move notes.txt to Archive",
            intent=NovaIntent.MOVE_ITEM,
            planned_operations=[],
            affected_paths=[],
            success=True,
            undo_info=res.undo_info,
        )

        record = self.history.get_last_undoable_action()

        # Now simulate collision: someone recreated notes.txt at the original location
        src_file.write_text("new conflicting file", encoding="utf-8")

        # Rollback validation MUST reject to prevent accidental overwrite
        is_valid, err = self.history.validate_rollback(record["undo_info"], policy=self.policy)
        self.assertFalse(is_valid)
        self.assertIn("already exists", err)

        # Execute rollback should also fail safely
        rollback_res = self.history.execute_rollback(record, file_manager=self.file_manager, policy=self.policy)
        self.assertFalse(rollback_res.success)
        self.assertIn("already exists", rollback_res.error)


if __name__ == "__main__":
    unittest.main()
