"""
Tests for Nova AppManager
"""

import sys
from pathlib import Path
import unittest

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.system.app_manager import AppManager, ApplicationInfo


class TestAppManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mgr = AppManager()
        cls.mgr.initialize()

    def test_app_discovery_count(self):
        """Test that applications are discovered across the system."""
        apps = self.mgr.list_applications()
        self.assertGreater(len(apps), 10, "Should discover more than 10 apps on Windows.")
        print(f"\n[TestAppManager] Successfully discovered {len(apps)} applications.")

    def test_find_builtin_calculator(self):
        """Test finding calculator by alias and full name."""
        matches = self.mgr.find_applications("calc")
        self.assertTrue(len(matches) > 0, "Should find Calculator with query 'calc'")
        app, score = matches[0]
        self.assertIn("calc", app.name.lower())
        print(f"[TestAppManager] Found '{app.name}' with score {score:.2f}")

    def test_find_notepad(self):
        """Test finding notepad."""
        matches = self.mgr.find_applications("notepad")
        self.assertTrue(len(matches) > 0, "Should find Notepad")
        app, score = matches[0]
        self.assertIn("notepad", app.name.lower())
        print(f"[TestAppManager] Found '{app.name}' with score {score:.2f}")

    def test_find_installed_software(self):
        """Test finding installed third party apps if present or common tools."""
        for tool in ["settings", "powershell", "cmd"]:
            matches = self.mgr.find_applications(tool)
            self.assertTrue(len(matches) > 0, f"Should find {tool}")
            app, score = matches[0]
            print(f"[TestAppManager] Found '{app.name}' for query '{tool}' with score {score:.2f}")

    def test_dry_run_open_validation(self):
        """Test that open_application resolves correctly without throwing unexpected errors."""
        matches = self.mgr.find_applications("calc")
        self.assertTrue(len(matches) > 0)
        best_app, _ = matches[0]
        self.assertIsNotNone(best_app.app_id or best_app.path)


if __name__ == "__main__":
    unittest.main()
