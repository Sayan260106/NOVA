"""
Tests for Nova open candidate discovery and disambiguation.
Verifies that when multiple files or folders (or applications) share the same name:
1. All candidates are discovered by prepare_open.
2. The user is prompted / able to select which one to open.
3. Only the selected and confirmed item is executed.
4. Filtering by kind (folder vs file) works accurately.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.agent.brain import NovaBrain
from nova.config import DEFAULT_WORKSPACE


class TestOpenDisambiguation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.brain = NovaBrain(dry_run_power=True)
        cls.brain.initialize()

        # Setup test directory and files on D: drive
        cls.test_folder_a = DEFAULT_WORKSPACE / "OpenTestDirA"
        cls.test_folder_b = DEFAULT_WORKSPACE / "OpenTestDirB"
        cls.test_folder_a.mkdir(parents=True, exist_ok=True)
        cls.test_folder_b.mkdir(parents=True, exist_ok=True)

        # Same-named files in different folders
        cls.file_in_a = cls.test_folder_a / "duplicate_target.txt"
        cls.file_in_b = cls.test_folder_b / "duplicate_target.txt"
        cls.file_in_a.write_text("Content in DirA", encoding="utf-8")
        cls.file_in_b.write_text("Content in DirB", encoding="utf-8")

        # Folder and file of same base name
        cls.same_name_folder = DEFAULT_WORKSPACE / "DualIdentity"
        cls.same_name_folder.mkdir(parents=True, exist_ok=True)
        cls.same_name_file = DEFAULT_WORKSPACE / "DualIdentity.txt"
        cls.same_name_file.write_text("I am the file", encoding="utf-8")

        # Record in indexer
        cls.brain.indexer.record_item(cls.test_folder_a)
        cls.brain.indexer.record_item(cls.test_folder_b)
        cls.brain.indexer.record_item(cls.file_in_a)
        cls.brain.indexer.record_item(cls.file_in_b)
        cls.brain.indexer.record_item(cls.same_name_folder)
        cls.brain.indexer.record_item(cls.same_name_file)

    @classmethod
    def tearDownClass(cls):
        # Cleanup
        for p in [cls.file_in_a, cls.file_in_b, cls.same_name_file]:
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
        for d in [cls.same_name_folder, cls.test_folder_a, cls.test_folder_b]:
            if d.exists():
                try:
                    d.rmdir()
                except OSError:
                    pass

    def test_disambiguate_files_with_same_name_in_different_folders(self):
        """Test detecting duplicate files across directories when commanding to open."""
        prep = self.brain.prepare_open("duplicate_target.txt")
        self.assertEqual(prep["status"], "multiple")
        self.assertGreaterEqual(len(prep["candidates"]), 2)

        paths = [str(c.path).lower() for c in prep["candidates"]]
        self.assertIn(str(self.file_in_a).lower(), paths)
        self.assertIn(str(self.file_in_b).lower(), paths)

        # Mock os.startfile so we don't pop up notepad windows during test
        with patch("os.startfile") as mock_start:
            chosen = [c for c in prep["candidates"] if str(c.path).lower() == str(self.file_in_a).lower()][0]
            res = self.brain.execute_open(chosen)
            self.assertTrue(res["success"])
            mock_start.assert_called_once_with(str(self.file_in_a.resolve()))

    def test_disambiguate_folder_and_file_with_same_name(self):
        """Test detecting both a folder and a file sharing the same base name."""
        prep = self.brain.prepare_open("DualIdentity")
        self.assertEqual(prep["status"], "multiple")

        kinds = {c.kind for c in prep["candidates"]}
        self.assertIn("folder", kinds)
        self.assertIn("file", kinds)

        folder_cand = next(c for c in prep["candidates"] if c.kind == "folder")
        file_cand = next(c for c in prep["candidates"] if c.kind == "file")

        self.assertEqual(str(folder_cand.path).lower(), str(self.same_name_folder).lower())
        self.assertEqual(str(file_cand.path).lower(), str(self.same_name_file).lower())

        with patch("os.startfile") as mock_start:
            res_folder = self.brain.execute_open(folder_cand)
            self.assertTrue(res_folder["success"])
            self.assertEqual(res_folder["type"], "folder")
            mock_start.assert_called_with(str(self.same_name_folder.resolve()))

            res_file = self.brain.execute_open(file_cand)
            self.assertTrue(res_file["success"])
            self.assertEqual(res_file["type"], "file")
            mock_start.assert_called_with(str(self.same_name_file.resolve()))

    def test_kind_filter_resolves_specifically(self):
        """Test that passing kind='folder' or kind='file' resolves directly without ambiguity."""
        prep_folder = self.brain.prepare_open("DualIdentity", kind="folder")
        # Should only contain folders
        for c in prep_folder["candidates"]:
            self.assertTrue(c.is_dir())

        prep_file = self.brain.prepare_open("DualIdentity", kind="file")
        # Should only contain files
        for c in prep_file["candidates"]:
            self.assertTrue(c.is_file())


if __name__ == "__main__":
    unittest.main()
