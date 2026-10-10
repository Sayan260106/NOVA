"""
Tests for Phase 2 - Step 02: Smarter File Organization
Validates:
1. Extension-based organization (Documents, Images, Code, etc.)
2. Safe dry-run previews without disk modification
3. Conflict resolution (no accidental overwrites, auto-renaming to 'name (1).ext')
4. Bulk move and bulk copy operations
5. Duplicate detection with SHA256 checksum grouping
6. End-to-end NovaBrain execution
"""

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.system.file_manager import FileManager
from nova.agent.brain import NovaBrain
from nova.agent.intent_parser import NovaIntent


class TestFileOrganization(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sandbox = Path(self.temp_dir.name)
        self.file_manager = FileManager()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_preview_folder_organization(self):
        """Preview mode must return planned operations without moving any files on disk."""
        test_dir = self.sandbox / "TestDownloads"
        test_dir.mkdir()

        (test_dir / "doc1.pdf").write_text("dummy", encoding="utf-8")
        (test_dir / "photo.jpg").write_text("dummy", encoding="utf-8")
        (test_dir / "script.py").write_text("dummy", encoding="utf-8")

        res = self.file_manager.organize_folder_by_type(str(test_dir), preview=True)
        self.assertTrue(res.success)
        self.assertTrue(res["preview"])
        self.assertEqual(res["count"], 3)

        # Confirm original files are still in their root locations
        self.assertTrue((test_dir / "doc1.pdf").exists())
        self.assertTrue((test_dir / "photo.jpg").exists())
        self.assertTrue((test_dir / "script.py").exists())
        # Confirm category subfolders were NOT created
        self.assertFalse((test_dir / "Documents").exists())

    def test_execute_folder_organization(self):
        """Organize folder moves files into category subfolders safely."""
        test_dir = self.sandbox / "OrganizeTarget"
        test_dir.mkdir()

        (test_dir / "invoice.pdf").write_text("doc", encoding="utf-8")
        (test_dir / "landscape.png").write_text("img", encoding="utf-8")
        (test_dir / "server.py").write_text("code", encoding="utf-8")
        (test_dir / "archive.zip").write_text("zip", encoding="utf-8")
        # Existing subfolder should NOT be touched
        existing_sub = test_dir / "KeepMe"
        existing_sub.mkdir()
        (existing_sub / "nested.txt").write_text("keep", encoding="utf-8")

        res = self.file_manager.organize_folder_by_type(str(test_dir), preview=False)
        self.assertTrue(res.success)
        self.assertEqual(res["count"], 4)

        # Verify new locations
        self.assertTrue((test_dir / "Documents" / "invoice.pdf").exists())
        self.assertTrue((test_dir / "Images" / "landscape.png").exists())
        self.assertTrue((test_dir / "Code" / "server.py").exists())
        self.assertTrue((test_dir / "Archives" / "archive.zip").exists())

        # Verify existing subfolder is intact
        self.assertTrue(existing_sub.exists())
        self.assertTrue((existing_sub / "nested.txt").exists())

    def test_conflict_resolution_rename(self):
        """Conflict resolution renames target to 'name (1).ext' rather than overwriting."""
        test_dir = self.sandbox / "ConflictTest"
        test_dir.mkdir()
        docs_dir = test_dir / "Documents"
        docs_dir.mkdir()

        # Existing file in destination
        (docs_dir / "report.pdf").write_text("original content", encoding="utf-8")
        # Incoming file with exact same name in root
        (test_dir / "report.pdf").write_text("new content", encoding="utf-8")

        res = self.file_manager.organize_folder_by_type(str(test_dir), preview=False, conflict_strategy="rename")
        self.assertTrue(res.success)

        # Original must be preserved
        self.assertEqual((docs_dir / "report.pdf").read_text(encoding="utf-8"), "original content")
        # New file moved to conflict name
        renamed = docs_dir / "report (1).pdf"
        self.assertTrue(renamed.exists())
        self.assertEqual(renamed.read_text(encoding="utf-8"), "new content")

    def test_bulk_move_and_copy(self):
        """Bulk move and copy must process lists of items with conflict guards."""
        src_dir = self.sandbox / "SourceBatch"
        src_dir.mkdir()
        dest_dir = self.sandbox / "DestBatch"
        dest_dir.mkdir()

        f1 = src_dir / "item1.txt"
        f2 = src_dir / "item2.txt"
        f1.write_text("1", encoding="utf-8")
        f2.write_text("2", encoding="utf-8")

        # Bulk copy
        res_copy = self.file_manager.bulk_copy([str(f1), str(f2)], str(dest_dir))
        self.assertTrue(res_copy.success)
        self.assertTrue((dest_dir / "item1.txt").exists())
        self.assertTrue((dest_dir / "item2.txt").exists())
        self.assertTrue(f1.exists())

        # Bulk move
        move_dest = self.sandbox / "MovedBatch"
        move_dest.mkdir()
        res_move = self.file_manager.bulk_move([str(f1), str(f2)], str(move_dest))
        self.assertTrue(res_move.success)
        self.assertTrue((move_dest / "item1.txt").exists())
        self.assertFalse(f1.exists())

    def test_find_duplicates(self):
        """Detect duplicate files using size grouping and SHA256 checksum matching."""
        dup_dir = self.sandbox / "DupTest"
        dup_dir.mkdir()

        content_dup = b"IDENTICAL BINARY CONTENT FOR NOVA DUPLICATE DETECTION TEST 1234567890"
        (dup_dir / "file_a.txt").write_bytes(content_dup)
        (dup_dir / "file_b.txt").write_bytes(content_dup)
        (dup_dir / "unique.txt").write_bytes(b"Completely unique data")

        res = self.file_manager.find_duplicates(str(dup_dir))
        self.assertTrue(res.success)
        self.assertEqual(res["group_count"], 1)
        self.assertEqual(len(res["duplicate_groups"][0]["files"]), 2)
        self.assertEqual(res["wasted_bytes"], len(content_dup))

    def test_brain_organize_end_to_end(self):
        """NovaBrain handles natural language organize command end-to-end."""
        brain = NovaBrain(dry_run_power=True)
        brain.initialize()

        test_dir = self.sandbox / "BrainOrgTest"
        test_dir.mkdir()
        (test_dir / "data.csv").write_text("col1,col2", encoding="utf-8")
        (test_dir / "avatar.png").write_text("png", encoding="utf-8")

        cmd = f"organize folder {test_dir}"
        res = brain.process(cmd)
        self.assertEqual(res["intent"], NovaIntent.ORGANIZE_FOLDER)
        self.assertTrue(res["success"])
        self.assertTrue((test_dir / "Documents" / "data.csv").exists())
        self.assertTrue((test_dir / "Images" / "avatar.png").exists())


if __name__ == "__main__":
    unittest.main()
