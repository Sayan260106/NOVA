"""
Tests for Nova FileManager (Zero-Path file/folder operations, D: drive default, rename, and all-drive search)
"""

import sys
import shutil
import unittest
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.system.file_manager import FileManager
from nova.core.indexer import Indexer
from nova.config import DEFAULT_WORKSPACE, D_DRIVE


class TestFileManager(unittest.TestCase):
    def setUp(self):
        # Use an isolated test database for Indexer
        self.test_dir = DEFAULT_WORKSPACE / "_test_nova_sandbox"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.test_db = self.test_dir / "test_index.db"
        self.indexer = Indexer(db_path=self.test_db)
        self.fm = FileManager(indexer=self.indexer)

    def tearDown(self):
        # Clean up sandbox
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_default_creation_in_d_drive(self):
        """Test that unspecified creations default to D: drive."""
        res_folder = self.fm.create_folder("NovaDdriveTestFolder")
        self.assertTrue(res_folder["success"], f"Failed to create folder: {res_folder}")
        folder_p = Path(res_folder["path"])
        self.assertTrue(folder_p.exists())
        self.assertTrue(str(folder_p).lower().startswith("d:"), f"Expected D: drive, got {folder_p}")

        res_file = self.fm.create_file("nova_ddrive_test.txt", content="Testing D drive default")
        self.assertTrue(res_file["success"])
        file_p = Path(res_file["path"])
        self.assertTrue(file_p.exists())
        self.assertTrue(str(file_p).lower().startswith("d:"), f"Expected D: drive, got {file_p}")

        print(f"\n[TestFileManager] Verified default creation in D: drive: {folder_p} and {file_p}")
        # Clean up
        self.fm.delete_item("NovaDdriveTestFolder", permanent=True)
        self.fm.delete_item("nova_ddrive_test.txt", permanent=True)

    def test_create_folder_inside_parent_zero_path(self):
        """Test creating folder inside an existing specific folder by name only."""
        # 1. Create parent
        res1 = self.fm.create_folder("ParentFolderX")
        self.assertTrue(res1["success"])

        # 2. Create child by referencing parent name only!
        res2 = self.fm.create_folder("ChildFolderY", parent_name="ParentFolderX")
        self.assertTrue(res2["success"], f"Failed to create child: {res2}")
        child_path = Path(res2["path"])
        self.assertTrue(child_path.exists())
        self.assertEqual(child_path.parent.name, "ParentFolderX")
        print(f"[TestFileManager] Resolved parent by name and created child at: {child_path}")

        # Clean up
        self.fm.delete_item("ParentFolderX", permanent=True)

    def test_rename_zero_path(self):
        """Test renaming files and folders without specifying full paths."""
        # 1. Test renaming file
        self.fm.create_file("rename_me.txt", content="Initial content")
        rename_file_res = self.fm.rename_item("rename_me.txt", "renamed_done.txt")
        self.assertTrue(rename_file_res["success"], f"Rename file failed: {rename_file_res}")
        self.assertFalse((DEFAULT_WORKSPACE / "rename_me.txt").exists())
        self.assertTrue((DEFAULT_WORKSPACE / "renamed_done.txt").exists())
        print(f"[TestFileManager] File renamed successfully: {rename_file_res['old_name']} -> {rename_file_res['new_name']}")

        # 2. Test renaming folder
        self.fm.create_folder("OldFolderName")
        rename_folder_res = self.fm.rename_item("OldFolderName", "NewFolderName")
        self.assertTrue(rename_folder_res["success"], f"Rename folder failed: {rename_folder_res}")
        self.assertFalse((DEFAULT_WORKSPACE / "OldFolderName").exists())
        self.assertTrue((DEFAULT_WORKSPACE / "NewFolderName").exists())
        print(f"[TestFileManager] Folder renamed successfully: {rename_folder_res['old_name']} -> {rename_folder_res['new_name']}")

        # Clean up
        self.fm.delete_item("renamed_done.txt", permanent=True)
        self.fm.delete_item("NewFolderName", permanent=True)

    def test_copy_and_move_zero_path(self):
        """Test copying and moving without explicit paths."""
        # Setup source file and folders
        self.fm.create_folder("SourceDir")
        self.fm.create_folder("DestDirA")
        self.fm.create_folder("DestDirB")

        self.fm.create_file("document.txt", content="Important data", parent_name="SourceDir")

        # 1. Copy document.txt into DestDirA (only by names!)
        copy_res = self.fm.copy_item("document.txt", "DestDirA")
        self.assertTrue(copy_res["success"], f"Copy failed: {copy_res}")
        copied_file = Path(copy_res["destination"])
        self.assertTrue(copied_file.exists())
        self.assertEqual(copied_file.parent.name, "DestDirA")
        print(f"[TestFileManager] Successfully copied without paths: {copy_res['source']} -> {copy_res['destination']}")

        # 2. Move copied file from DestDirA into DestDirB (only by names!)
        move_res = self.fm.move_item("document.txt", "DestDirB")
        self.assertTrue(move_res["success"], f"Move failed: {move_res}")
        moved_file = Path(move_res["destination"])
        self.assertTrue(moved_file.exists())
        self.assertEqual(moved_file.parent.name, "DestDirB")
        print(f"[TestFileManager] Successfully moved without paths: {move_res['source']} -> {move_res['destination']}")

        # Clean up
        self.fm.delete_item("SourceDir", permanent=True)
        self.fm.delete_item("DestDirA", permanent=True)
        self.fm.delete_item("DestDirB", permanent=True)

    def test_find_items_across_file_explorer(self):
        """Test finding files and folders across File Explorer drives."""
        self.fm.create_folder("TargetSearchFolder")
        self.fm.create_file("query_target.csv", content="col1,col2\n1,2")

        found_folders = self.fm.find_items("TargetSearchFolder", kind="folder")
        self.assertTrue(len(found_folders) > 0)
        self.assertEqual(found_folders[0]["name"], "TargetSearchFolder")

        found_files = self.fm.find_items("query_target.csv", kind="file")
        self.assertTrue(len(found_files) > 0)
        self.assertEqual(found_files[0]["name"], "query_target.csv")
        print(f"[TestFileManager] Find successfully located folder '{found_folders[0]['name']}' and file '{found_files[0]['name']}'")

        # Clean up
        self.fm.delete_item("TargetSearchFolder", permanent=True)
        self.fm.delete_item("query_target.csv", permanent=True)

    def test_delete_zero_path(self):
        """Test safe deletion without path."""
        self.fm.create_file("temporary_delete_test.txt", content="temp")
        del_res = self.fm.delete_item("temporary_delete_test.txt", permanent=True)
        self.assertTrue(del_res["success"])
        self.assertFalse(Path(del_res["path"]).exists())
        print(f"[TestFileManager] Successfully deleted: {del_res['path']}")


if __name__ == "__main__":
    unittest.main()
