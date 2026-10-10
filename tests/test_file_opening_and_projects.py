"""
Tests for Phase 2 Steps 03, 04, and 05:
- Reliable file opening (with app, default app, disambiguation, missing files)
- Project-aware application launching (app aliases, project location resolution, editor launch)
- Daily workflow automation (compound multi-step project scaffolding and launching)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.agent.brain import NovaBrain
from nova.agent.intent_parser import IntentParser, NovaIntent
from nova.system.app_manager import AppManager
from nova.config import DEFAULT_WORKSPACE


class TestFileOpeningAndProjects(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.brain = NovaBrain(dry_run_power=True)
        cls.brain.initialize()
        cls.parser = IntentParser()
        cls.app_mgr = cls.brain.app_manager
        cls.file_mgr = cls.brain.file_manager

        cls.test_dir = DEFAULT_WORKSPACE / "NovaPhase2WorkflowTest"
        cls.test_dir.mkdir(parents=True, exist_ok=True)

        cls.sample_file = cls.test_dir / "report_q3.txt"
        cls.sample_file.write_text("Q3 Financial Overview: Revenue +15%", encoding="utf-8")
        cls.brain.indexer.record_item(cls.sample_file)

    @classmethod
    def tearDownClass(cls):
        import shutil
        if cls.test_dir.exists():
            try:
                shutil.rmtree(cls.test_dir)
            except OSError:
                pass

    # --- Step 03: Reliable File Opening ---

    def test_parse_open_file_with_app(self):
        """Test parsing commands that open a file with a specified application."""
        parsed = self.parser.parse("open report_q3.txt with notepad")
        self.assertEqual(parsed["intent"], NovaIntent.OPEN_ITEM)
        self.assertEqual(parsed["name"], "report_q3.txt")
        self.assertEqual(parsed["app"], "notepad")

        parsed2 = self.parser.parse("open file index.html in chrome")
        self.assertEqual(parsed2["intent"], NovaIntent.OPEN_ITEM)
        self.assertEqual(parsed2["name"], "index.html")
        self.assertEqual(parsed2["app"], "chrome")

    def test_open_file_with_app_execution(self):
        """Test executing open_item with an explicit app (mocking subprocess)."""
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_popen.return_value = mock_proc

            res = self.file_mgr.open_item("report_q3.txt", app="notepad", app_manager=self.app_mgr)
            self.assertTrue(res.success, f"Failed: {res.error}")
            self.assertIn("Notepad", res.message)
            mock_popen.assert_called_once()

    def test_open_missing_file_clean_error(self):
        """Test that opening a non-existent file reports a clean, helpful error."""
        res = self.file_mgr.open_item("completely_nonexistent_file_xyz_999.doc")
        self.assertFalse(res.success)
        self.assertIn("could not be found", res.error)

    # --- Step 04: Project-Aware Application Launching ---

    def test_parse_open_project_in_editor(self):
        """Test parsing project open commands into OPEN_PROJECT intent."""
        parsed = self.parser.parse("open my NOVA project in VS Code")
        self.assertEqual(parsed["intent"], NovaIntent.OPEN_PROJECT)
        self.assertIn("NOVA", parsed["project"])
        self.assertIn("VS Code", parsed["app"])

        parsed2 = self.parser.parse("open project Nova in code")
        self.assertEqual(parsed2["intent"], NovaIntent.OPEN_PROJECT)
        self.assertEqual(parsed2["project"], "Nova")
        self.assertEqual(parsed2["app"], "code")

        parsed3 = self.parser.parse("open project Analytics")
        self.assertEqual(parsed3["intent"], NovaIntent.OPEN_PROJECT)
        self.assertEqual(parsed3["project"], "Analytics")
        self.assertEqual(parsed3["app"], "Visual Studio Code")

    def test_resolve_project_path(self):
        """Test resolving project path for workspace or named project."""
        resolved = self.app_mgr.resolve_project_path("NOVA", file_manager=self.file_mgr)
        self.assertIsNotNone(resolved)
        self.assertTrue(resolved.exists())
        self.assertIn("nova", resolved.name.lower())

    def test_open_project_end_to_end_mocked(self):
        """Test brain processing 'open project Nova in code' through Planner -> Policy -> Executor."""
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_popen.return_value = mock_proc

            result = self.brain.process("open project Nova in code")
            self.assertTrue(result.success, f"Expected success, got: {result.error}")
            self.assertEqual(result.get("intent"), NovaIntent.OPEN_PROJECT)
            self.assertIn("Visual Studio Code", result.message)

    # --- Step 05: Daily Workflow Automation ---

    def test_compound_project_scaffolding_workflow(self):
        """
        Test multi-step automation:
        Create folder TestWorkflowProject in workspace, create README.md inside it, and open it in VS Code.
        """
        project_folder_name = "TestWorkflowProject"
        utterance = f"create folder {project_folder_name} in {self.test_dir.name} and create file README.md with content 'Project Docs' inside {project_folder_name} and open project {project_folder_name} in VS Code"

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_popen.return_value = mock_proc

            result = self.brain.process(utterance)
            self.assertTrue(result.success, f"Workflow failed: {result.error}")
            self.assertEqual(result.get("intent"), NovaIntent.COMPLEX_COMMAND)

            # Verify files were actually created on disk
            created_folder = self.test_dir / project_folder_name
            self.assertTrue(created_folder.exists(), "Project folder was not created.")
            created_readme = created_folder / "README.md"
            self.assertTrue(created_readme.exists(), "README.md was not created.")
            self.assertEqual(created_readme.read_text(encoding="utf-8"), "Project Docs")

            # Verify mock_popen was called for launching VS Code
            self.assertTrue(mock_popen.called, "VS Code was not invoked.")


if __name__ == "__main__":
    unittest.main()
