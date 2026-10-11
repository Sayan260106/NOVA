"""
Unit tests for Nova Quick Notes & Scratchpad (Phase 4).
Validates SQLite persistence across restarts, CRUD, tagging, keyword search,
and undo restoration.
"""

import tempfile
import unittest
from pathlib import Path

from nova.tools.notes import NotesManager


class TestNotesManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_notes.db"
        self.manager = NotesManager(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_add_and_get_note(self):
        res = self.manager.add_note(
            content="I need to revise operating systems tonight.",
            tags=["study", "exams"],
        )
        self.assertTrue(res.success)
        self.assertIn("Saved note", res.message)
        note_id = res.data["id"]

        get_res = self.manager.get_note(note_id)
        self.assertTrue(get_res.success)
        note = get_res.data
        self.assertEqual(note["content"], "I need to revise operating systems tonight.")
        self.assertIn("study", note["tags"])
        self.assertIn("exams", note["tags"])

    def test_empty_note_fails(self):
        res = self.manager.add_note(content="")
        self.assertFalse(res.success)
        self.assertIn("empty", res.error.lower())

    def test_list_and_filter_by_tag(self):
        self.manager.add_note("Note 1", tags=["work"])
        self.manager.add_note("Note 2", tags=["personal"])
        self.manager.add_note("Note 3", tags=["work", "urgent"])

        all_notes = self.manager.list_notes()
        self.assertTrue(all_notes.success)
        self.assertEqual(all_notes.data["count"], 3)

        work_notes = self.manager.list_notes(tag="work")
        self.assertTrue(work_notes.success)
        self.assertEqual(work_notes.data["count"], 2)

    def test_search_notes(self):
        self.manager.add_note("Review database transactions and ACID properties.")
        self.manager.add_note("Buy groceries tomorrow.")

        search_res = self.manager.search_notes("ACID")
        self.assertTrue(search_res.success)
        self.assertEqual(search_res.data["count"], 1)
        self.assertIn("Review database", search_res.data["notes"][0]["content"])

        empty_res = self.manager.search_notes("nonexistent_keyword_xyz")
        self.assertTrue(empty_res.success)
        self.assertEqual(empty_res.data["count"], 0)

    def test_update_and_append_note(self):
        add_res = self.manager.add_note("Initial note content.")
        note_id = add_res.data["id"]

        upd_res = self.manager.update_note(note_id, content="Updated content.")
        self.assertTrue(upd_res.success)
        self.assertEqual(upd_res.data["content"], "Updated content.")

        app_res = self.manager.update_note(note_id, content="Appended extra info.", append=True)
        self.assertTrue(app_res.success)
        self.assertIn("Updated content.", app_res.data["content"])
        self.assertIn("Appended extra info.", app_res.data["content"])

    def test_delete_and_restore_note(self):
        add_res = self.manager.add_note("Note to be deleted.", title="Temporary")
        note_id = add_res.data["id"]

        del_res = self.manager.delete_note(note_id)
        self.assertTrue(del_res.success)
        self.assertIsNotNone(del_res.undo_info)

        # Verify it no longer exists
        get_res = self.manager.get_note(note_id)
        self.assertFalse(get_res.success)

        # Restore using undo_info
        rest_res = self.manager.restore_note(del_res.undo_info)
        self.assertTrue(rest_res.success)

        # Verify restored
        get_res2 = self.manager.get_note(note_id)
        self.assertTrue(get_res2.success)
        self.assertEqual(get_res2.data["title"], "Temporary")

    def test_persistence_across_restarts(self):
        self.manager.add_note("Persistent note across sessions.", title="SessionCheck")

        # Simulate restart by creating a new manager instance with same db_path
        new_manager = NotesManager(db_path=self.db_path)
        list_res = new_manager.list_notes()
        self.assertTrue(list_res.success)
        self.assertEqual(list_res.data["count"], 1)
        self.assertEqual(list_res.data["notes"][0]["title"], "SessionCheck")


if __name__ == "__main__":
    unittest.main()
