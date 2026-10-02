"""
Tests for Nova deletion candidate discovery and disambiguation.
Verifies that when multiple files or folders have the exact same name:
1. All candidates are found.
2. The user is prompted to select which one to delete.
3. Only the selected and confirmed item is deleted.
"""

import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.agent.brain import NovaBrain
from nova.config import DEFAULT_WORKSPACE


class TestDeletionDisambiguation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.brain = NovaBrain(dry_run_power=True)
        cls.brain.initialize()

    def test_duplicate_name_detection_and_selective_deletion(self):
        """Test creating two files with same name in different folders and disambiguating deletion."""
        # 1. Create two folders
        res_f1 = self.brain.process("create folder FolderA")
        res_f2 = self.brain.process("create folder FolderB")
        self.assertTrue(res_f1["success"])
        self.assertTrue(res_f2["success"])

        # 2. Create identical file name in both folders
        res_file1 = self.brain.process("create file conflict.txt with content 'Content in FolderA' inside FolderA")
        res_file2 = self.brain.process("create file conflict.txt with content 'Content in FolderB' inside FolderB")
        self.assertTrue(res_file1["success"])
        self.assertTrue(res_file2["success"])

        # 3. Check prepare_deletion finds both candidates
        prep = self.brain.prepare_deletion("conflict.txt")
        self.assertEqual(prep["status"], "multiple", f"Expected 'multiple' status, got: {prep}")
        self.assertEqual(len(prep["candidates"]), 2)
        print(f"\n[TestDisambiguation] Successfully identified duplicate candidates:")
        for idx, c in enumerate(prep["candidates"], 1):
            print(f"  [{idx}] {c}")

        # 4. Select only candidate 1 to delete
        target_to_delete = prep["candidates"][0]
        target_to_keep = prep["candidates"][1]

        del_res = self.brain.execute_deletion(target_to_delete, permanent=True)
        self.assertTrue(del_res["success"])
        self.assertFalse(target_to_delete.exists(), "Target 1 should be deleted")
        self.assertTrue(target_to_keep.exists(), "Target 2 should still be preserved")
        print(f"[TestDisambiguation] Verified: deleted {target_to_delete} while preserving {target_to_keep}")

        # 5. Clean up second target and folders
        self.brain.execute_deletion(target_to_keep, permanent=True)
        self.brain.process("delete folder FolderA permanently")
        self.brain.process("delete folder FolderB permanently")


if __name__ == "__main__":
    unittest.main()
