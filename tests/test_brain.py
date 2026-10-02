"""
End-to-End Tests for Nova Virtual Assistant Brain
Validates:
a) Application discovery and launching
b) Zero-path file and folder CRUD (create, delete, move, copy, open)
c) Power management (lock, sleep, restart, shutdown, abort)
d) Universal search for files, folders, and applications
e) JARVIS Component Architecture Language Chart
"""

import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.agent.brain import NovaBrain
from nova.agent.intent_parser import NovaIntent


class TestNovaBrainE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Initialize brain with safe power dry-run mode
        cls.brain = NovaBrain(dry_run_power=True)
        cls.brain.initialize()

    def test_goal_a_app_opening(self):
        """Goal a: Able to open all the applications present in the laptop."""
        # Test parsing and resolving app opening for common and installed tools
        commands = [
            "open calculator",
            "launch notepad",
            "start powershell",
            "open settings",
        ]
        for cmd in commands:
            res = self.brain.process(cmd)
            self.assertEqual(res["intent"], NovaIntent.OPEN_APP)
            self.assertTrue(res["success"], f"Failed on command '{cmd}': {res}")
            print(f"[Goal A - App Launch] Command '{cmd}' -> {res['response']}")

        # Cleanup test processes
        import psutil
        for p in psutil.process_iter(['name']):
            try:
                pname = (p.info['name'] or '').lower()
                if any(x in pname for x in ['notepad.exe', 'calculator.exe', 'calculatorapp.exe']):
                    p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def test_goal_b_zero_path_file_folder_operations(self):
        """Goal b: Able to create, delete, move, copy, open any folder and file without telling path explicitly."""
        # 1. Create a root folder without path (defaults to D: drive)
        res_cf1 = self.brain.process("create folder BrainTestProject")
        self.assertTrue(res_cf1["success"])
        self.assertTrue(str(res_cf1["details"]["path"]).lower().startswith("d:"), f"Expected D: drive, got {res_cf1['details']['path']}")
        print(f"[Goal B - Create Folder in D:] {res_cf1['response']}")

        # 2. Create another folder without path
        res_cf2 = self.brain.process("create folder BrainBackupVault")
        self.assertTrue(res_cf2["success"])
        print(f"[Goal B - Create Folder 2] {res_cf2['response']}")

        # 3. Create a subfolder inside BrainTestProject without specifying parent path!
        res_sub = self.brain.process("create folder SubModule inside BrainTestProject")
        self.assertTrue(res_sub["success"])
        print(f"[Goal B - Create Subfolder Zero-Path] {res_sub['response']}")

        # 4. Create a file inside BrainTestProject without specifying path
        res_file = self.brain.process("create file report.txt with content 'JARVIS Nova Online' inside BrainTestProject")
        self.assertTrue(res_file["success"])
        print(f"[Goal B - Create File Zero-Path] {res_file['response']}")

        # 5. Rename file without path!
        res_ren_file = self.brain.process("rename file report.txt to final_report.txt")
        self.assertTrue(res_ren_file["success"])
        self.assertEqual(res_ren_file["intent"], NovaIntent.RENAME_ITEM)
        print(f"[Goal B - Rename File Zero-Path] {res_ren_file['response']}")

        # 6. Rename folder without path!
        res_ren_dir = self.brain.process("rename folder SubModule to CoreModule")
        self.assertTrue(res_ren_dir["success"])
        self.assertEqual(res_ren_dir["intent"], NovaIntent.RENAME_ITEM)
        print(f"[Goal B - Rename Folder Zero-Path] {res_ren_dir['response']}")

        # 7. Copy file to BrainBackupVault without specifying paths!
        res_copy = self.brain.process("copy file final_report.txt to BrainBackupVault")
        self.assertTrue(res_copy["success"])
        print(f"[Goal B - Copy Zero-Path] {res_copy['response']}")

        # 8. Move file inside BrainBackupVault to CoreModule without paths!
        res_move = self.brain.process("move file final_report.txt to CoreModule")
        self.assertTrue(res_move["success"])
        print(f"[Goal B - Move Zero-Path] {res_move['response']}")

        # 9. Delete file without specifying path
        res_del_file = self.brain.process("delete file final_report.txt permanently")
        self.assertTrue(res_del_file["success"])
        print(f"[Goal B - Delete Zero-Path] {res_del_file['response']}")

        # 10. Clean up created test folders
        self.brain.process("delete folder CoreModule permanently")
        self.brain.process("delete folder BrainTestProject permanently")
        self.brain.process("delete folder BrainBackupVault permanently")

    def test_goal_c_power_operations(self):
        """Goal c: Able to make the laptop lock, sleep, restart and shut down."""
        # Test lock
        res_lock = self.brain.process("lock laptop")
        self.assertTrue(res_lock["success"])
        print(f"[Goal C - Lock] {res_lock['response']}")

        # Test sleep
        res_sleep = self.brain.process("put laptop to sleep")
        self.assertTrue(res_sleep["success"])
        print(f"[Goal C - Sleep] {res_sleep['response']}")

        # Test restart (in safe dry-run mode as user instructed not to restart now)
        res_restart = self.brain.process("restart laptop in 60 seconds")
        self.assertTrue(res_restart["success"])
        print(f"[Goal C - Restart Dry Run] {res_restart['response']}")

        # Test shutdown (in safe dry-run mode as user instructed not to shut down now)
        res_shutdown = self.brain.process("shut down laptop in 120 seconds")
        self.assertTrue(res_shutdown["success"])
        print(f"[Goal C - Shutdown Dry Run] {res_shutdown['response']}")

        # Test abort power
        res_abort = self.brain.process("cancel shutdown")
        self.assertTrue(res_abort["success"])
        print(f"[Goal C - Abort Power] {res_abort['response']}")

        # Test battery
        res_battery = self.brain.process("what is the battery status")
        self.assertTrue(res_battery["success"])
        print(f"[Goal C - Battery] {res_battery['response']}")

    def test_goal_d_find_anything(self):
        """Goal d: Able to find any file, folder, application present in the laptop."""
        # Find applications
        res_app = self.brain.process("find app chrome")
        self.assertTrue(res_app["success"])
        print(f"[Goal D - Find App] Found: {len(res_app['results'])} app(s)")

        res_calc = self.brain.process("find app calculator")
        self.assertTrue(res_calc["success"])
        self.assertGreater(len(res_calc["results"]), 0)

        # Find folders
        res_folder = self.brain.process("find folder Documents")
        self.assertTrue(res_folder["success"])
        print(f"[Goal D - Find Folder] Found: {len(res_folder['results'])} folder(s)")

        # Find general entity
        res_gen = self.brain.process("search for notepad")
        self.assertTrue(res_gen["success"])
        print(f"[Goal D - General Find] Found {len(res_gen['results'])} item(s)")

    def test_language_chart_retrieval(self):
        """Test retrieving the saved JARVIS Component Architecture Language Chart."""
        res = self.brain.process("show language chart")
        self.assertTrue(res["success"])
        self.assertIn("chart", res)
        self.assertEqual(res["chart"]["Main AI / Agent Brain"], "Python")
        self.assertEqual(res["chart"]["Windows OS Automation"], "Python")
        self.assertEqual(res["chart"]["JARVIS Desktop UI"], "TypeScript + React")
        print("\n[Language Chart Retained in Nova's Memory]:")
        for k, v in list(res["chart"].items())[:6]:
            print(f"  - {k}: {v}")


if __name__ == "__main__":
    unittest.main()
