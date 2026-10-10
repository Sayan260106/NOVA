"""
Integration tests for Phase 3:
NovaBrain with PersistentMemory, ActionHistory, Context-aware command resolution,
and verified Undo / Rollback workflows.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from nova.agent.brain import NovaBrain
from nova.agent.intent_parser import NovaIntent
from nova.core.memory import PersistentMemory
from nova.core.action_history import ActionHistory


class TestPhase3BrainIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="nova_phase3_test_")
        self.mem_db = Path(self.temp_dir) / "test_memory.db"
        self.hist_db = Path(self.temp_dir) / "test_history.db"

        # Instantiate brain and assign isolated databases and workspace root
        self.brain = NovaBrain(dry_run_power=True)
        self.brain.memory = PersistentMemory(db_path=self.mem_db)
        self.brain.action_history = ActionHistory(db_path=self.hist_db)
        self.brain.app_manager.memory = self.brain.memory
        self.brain.planner.memory = self.brain.memory
        self.brain.executor.memory = self.brain.memory
        self.brain.executor.action_history = self.brain.action_history
        self.brain.file_manager.default_root = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_remember_and_open_project(self):
        proj_dir = (Path(self.temp_dir) / "NOVA").resolve()
        proj_dir.mkdir()

        # 1. "Remember that my NOVA project is in <proj_dir>"
        res = self.brain.process(f"Remember that my NOVA project is in {proj_dir}")
        self.assertTrue(res.get("success"))
        self.assertEqual(Path(self.brain.memory.get_project_location("nova")).resolve(), proj_dir)

        # 2. "What do you remember"
        res_recall = self.brain.process("what do you remember")
        self.assertTrue(res_recall.get("success"))
        self.assertIn("nova", res_recall.get("response", "").lower())

        # 3. Context-aware resolution: "Create folder tests there"
        # Since last project was remembered / set in context
        res_create = self.brain.process("Create folder tests there")
        self.assertTrue(res_create.get("success"))
        self.assertTrue((proj_dir / "tests").exists())

        # 4. "Forget my NOVA project"
        res_forget = self.brain.process("Forget my NOVA project")
        self.assertTrue(res_forget.get("success"))
        self.assertIsNone(self.brain.memory.get_project_location("nova"))
        # Verify the actual directory was NOT deleted (privacy/memory management rule)
        self.assertTrue(proj_dir.exists())

    def test_action_history_and_undo_flow(self):
        # Create a file
        f_path = Path(self.temp_dir) / "report.txt"
        f_path.write_text("Quarterly figures", encoding="utf-8")
        archive_dir = Path(self.temp_dir) / "Archive"
        archive_dir.mkdir()

        # Move file: "move report.txt to Archive"
        move_res = self.brain.process("move report.txt to Archive")
        self.assertTrue(move_res.get("success"))
        self.assertFalse(f_path.exists())
        self.assertTrue((archive_dir / "report.txt").exists())

        # Ask: "What files did you move today?"
        hist_res = self.brain.process("What files did you move today?")
        self.assertTrue(hist_res.get("success"))
        self.assertIn("report.txt", hist_res.get("response"))

        # Ask: "Undo the last file move"
        undo_res = self.brain.process("Undo the last file move")
        self.assertTrue(undo_res.get("success"))
        self.assertTrue(f_path.exists())
        self.assertFalse((archive_dir / "report.txt").exists())

        # If user tries to undo again when no undoable actions remain
        undo_again = self.brain.process("undo")
        self.assertFalse(undo_again.get("success"))
        self.assertIn("no", undo_again.get("response").lower())

    def test_memory_across_brain_restarts(self):
        # 1. Set preference in brain 1
        self.brain.process("Remember that my editor is VS Code")
        self.assertEqual(self.brain.memory.get("editor", category="preference"), "VS Code")

        # 2. Restart brain with same database
        restarted_brain = NovaBrain(dry_run_power=True)
        restarted_brain.memory = PersistentMemory(db_path=self.mem_db)
        restarted_brain.action_history = ActionHistory(db_path=self.hist_db)
        restarted_brain.app_manager.memory = restarted_brain.memory
        restarted_brain.planner.memory = restarted_brain.memory
        restarted_brain.executor.memory = restarted_brain.memory
        restarted_brain.executor.action_history = restarted_brain.action_history

        # 3. Query preference in new session
        res = restarted_brain.process("recall editor")
        self.assertTrue(res.get("success"))
        self.assertIn("VS Code", res.get("response"))


if __name__ == "__main__":
    unittest.main()
