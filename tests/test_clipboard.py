"""
Unit tests for Nova Clipboard Utilities (Phase 4).
Validates clipboard copy, read, clear operations, sensitive pattern scanning,
masking, and saving clipboard content as notes.
"""

import tempfile
import unittest
from pathlib import Path

from nova.tools.clipboard import ClipboardManager, SensitiveContentDetector
from nova.tools.notes import NotesManager


class TestClipboardUtilities(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_notes.db"
        self.notes_manager = NotesManager(db_path=self.db_path)
        # Use in-memory mode for reliable headless testing
        self.clipboard = ClipboardManager(in_memory_fallback=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_basic_copy_and_read(self):
        res = self.clipboard.set_clipboard_text("Hello Nova Assistant!")
        self.assertTrue(res.success)

        read_res = self.clipboard.get_clipboard_text()
        self.assertTrue(read_res.success)
        self.assertEqual(read_res.data["text"], "Hello Nova Assistant!")
        self.assertFalse(read_res.data["is_sensitive"])

    def test_clear_clipboard(self):
        self.clipboard.set_clipboard_text("Sensitive temp data")
        clear_res = self.clipboard.clear_clipboard()
        self.assertTrue(clear_res.success)

        read_res = self.clipboard.get_clipboard_text()
        self.assertTrue(read_res.success)
        self.assertEqual(read_res.data["text"], "")

    def test_sensitive_content_detection(self):
        # OpenAI key
        is_sens, cats = SensitiveContentDetector.scan("sk-proj-1234567890abcdef1234567890")
        self.assertTrue(is_sens)
        self.assertIn("OpenAI API Key", cats)

        # AWS key
        is_sens, cats = SensitiveContentDetector.scan("AKIAIOSFODNN7EXAMPLE")
        self.assertTrue(is_sens)
        self.assertIn("AWS Access Key", cats)

        # GitHub Token
        is_sens, cats = SensitiveContentDetector.scan("ghp_123456789012345678901234567890123456")
        self.assertTrue(is_sens)
        self.assertIn("GitHub Token", cats)

        # Private key
        is_sens, cats = SensitiveContentDetector.scan("-----BEGIN RSA PRIVATE KEY-----\nMIIE...")
        self.assertTrue(is_sens)
        self.assertIn("Private Key Header", cats)

        # Normal text
        is_sens, cats = SensitiveContentDetector.scan("Please review the operating systems syllabus.")
        self.assertFalse(is_sens)
        self.assertEqual(cats, [])

    def test_sensitive_content_masking(self):
        raw_key = "sk-1234567890abcdef1234567890"
        self.clipboard.set_clipboard_text(raw_key)

        # Default reading should mask sensitive tokens
        read_res = self.clipboard.get_clipboard_text(allow_sensitive=False)
        self.assertTrue(read_res.success)
        self.assertTrue(read_res.data["is_sensitive"])
        self.assertTrue(read_res.data["is_masked"])
        self.assertIn("****", read_res.data["text"])
        self.assertNotIn("abcdef", read_res.data["text"])

        # Explicit allow_sensitive returns raw text
        read_raw = self.clipboard.get_clipboard_text(allow_sensitive=True)
        self.assertEqual(read_raw.data["text"], raw_key)

    def test_save_clipboard_as_note(self):
        self.clipboard.set_clipboard_text("Important lecture notes on virtual memory paging.")
        save_res = self.clipboard.save_clipboard_as_note(self.notes_manager, title="Paging Notes")
        self.assertTrue(save_res.success)

        # Verify in notes manager
        note_id = save_res.data["id"]
        get_res = self.notes_manager.get_note(note_id)
        self.assertTrue(get_res.success)
        self.assertEqual(get_res.data["title"], "Paging Notes")
        self.assertEqual(get_res.data["content"], "Important lecture notes on virtual memory paging.")
        self.assertIn("clipboard", get_res.data["tags"])


if __name__ == "__main__":
    unittest.main()
