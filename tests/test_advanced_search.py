"""
Tests for Phase 2 - Step 01: Advanced File Search
Validates:
1. Indexer.search_advanced with multiple filters (filename, extension, directory, date, size)
2. Relevance ranking (exact match, prefix, recency score)
3. IntentParser natural language search filter extraction
4. End-to-end brain execution for advanced search queries
"""

import sys
import time
import tempfile
import unittest
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.core.indexer import Indexer, parse_size_str, format_size
from nova.agent.intent_parser import IntentParser, NovaIntent
from nova.system.file_manager import FileManager
from nova.agent.brain import NovaBrain


class TestAdvancedFileSearch(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sandbox = Path(self.temp_dir.name)
        self.db_path = self.sandbox / "test_index.db"
        self.indexer = Indexer(db_path=self.db_path)
        self.file_manager = FileManager(indexer=self.indexer)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_size_parsing_and_formatting(self):
        """Test parse_size_str and format_size utilities."""
        self.assertEqual(parse_size_str("500b"), 500)
        self.assertEqual(parse_size_str("10kb"), 10 * 1024)
        self.assertEqual(parse_size_str("5MB"), 5 * 1024 * 1024)
        self.assertEqual(parse_size_str("1.5GB"), int(1.5 * 1024 * 1024 * 1024))
        self.assertIsNone(parse_size_str(""))
        self.assertIsNone(parse_size_str("invalid"))

        self.assertEqual(format_size(500), "500 B")
        self.assertEqual(format_size(2048), "2.0 KB")
        self.assertEqual(format_size(5 * 1024 * 1024), "5.0 MB")

    def test_indexer_advanced_filters(self):
        """Test search_advanced by extension, directory, mtime, and size."""
        # Create test structure in sandbox
        proj_dir = self.sandbox / "MyProject"
        proj_dir.mkdir()
        docs_dir = self.sandbox / "Documents"
        docs_dir.mkdir()

        # Files in MyProject
        file_py = proj_dir / "main.py"
        file_py.write_text("print('hello')", encoding="utf-8")
        file_py_util = proj_dir / "utils.py"
        file_py_util.write_text("def helper(): pass", encoding="utf-8")
        file_txt = proj_dir / "notes.txt"
        file_txt.write_text("some notes" * 200, encoding="utf-8")  # ~2KB

        # File in Documents
        file_doc = docs_dir / "report.pdf"
        file_doc.write_bytes(b"%PDF-1.4 test")

        # Record into index
        for f in [file_py, file_py_util, file_txt, file_doc, proj_dir, docs_dir]:
            self.indexer.record_item(f)

        # 1. Filter by extension "python" in MyProject
        results = self.indexer.search_advanced(
            extension="python",
            directory=str(proj_dir),
        )
        self.assertEqual(len(results), 2)
        names = [r.name for r in results]
        self.assertIn("main.py", names)
        self.assertIn("utils.py", names)

        # 2. Filter by directory "Documents"
        results_doc = self.indexer.search_advanced(directory="Documents")
        self.assertEqual(len(results_doc), 1)
        self.assertEqual(results_doc[0].name, "report.pdf")

        # 3. Filter by minimum size
        results_large = self.indexer.search_advanced(min_size=1000)
        self.assertEqual(len(results_large), 1)
        self.assertEqual(results_large[0].name, "notes.txt")

        # 4. Filter by modification recency (last 1 day)
        results_recent = self.indexer.search_advanced(
            directory=str(proj_dir),
            modified_within_days=1.0,
        )
        self.assertGreaterEqual(len(results_recent), 3)

    def test_relevance_ranking(self):
        """Exact match should rank higher than prefix or substring."""
        f1 = self.sandbox / "test.py"
        f1.write_text("pass", encoding="utf-8")
        f2 = self.sandbox / "test_case_runner.py"
        f2.write_text("pass", encoding="utf-8")
        f3 = self.sandbox / "my_latest_test.py"
        f3.write_text("pass", encoding="utf-8")

        for f in [f1, f2, f3]:
            self.indexer.record_item(f)

        results = self.indexer.search_advanced(query="test", extension="python")
        self.assertEqual(len(results), 3)
        # Exact name stem match "test.py" should be ranked #1
        self.assertEqual(results[0].name, "test.py")
        # Prefix match "test_case_runner.py" should be ranked #2
        self.assertEqual(results[1].name, "test_case_runner.py")

    def test_natural_language_search_parsing(self):
        """Test IntentParser parsing rich natural language search queries."""
        parser = IntentParser()

        cmd1 = "Find all Python files in my NOVA project modified in the last 7 days"
        p1 = parser.parse(cmd1)
        self.assertEqual(p1["intent"], NovaIntent.FIND_ITEM)
        self.assertEqual(p1["extension"], "python")
        self.assertEqual(p1["directory"], "NOVA")
        self.assertEqual(p1["modified_within_days"], 7.0)

        cmd2 = "Find pdf files in Downloads larger than 5MB"
        p2 = parser.parse(cmd2)
        self.assertEqual(p2["intent"], NovaIntent.FIND_ITEM)
        self.assertEqual(p2["extension"], "pdf")
        self.assertEqual(p2["directory"], "Downloads")
        self.assertEqual(p2["min_size"], 5 * 1024 * 1024)

        cmd3 = "find file run_nova.py"
        p3 = parser.parse(cmd3)
        self.assertEqual(p3["intent"], NovaIntent.FIND_ITEM)
        self.assertEqual(p3["query"], "run_nova.py")
        self.assertEqual(p3["kind"], "file")

        cmd4 = "find app chrome"
        p4 = parser.parse(cmd4)
        self.assertEqual(p4["intent"], NovaIntent.FIND_ITEM)
        self.assertEqual(p4["query"], "chrome")
        self.assertEqual(p4["kind"], "app")

    def test_brain_advanced_search_end_to_end(self):
        """End-to-end test with NovaBrain running advanced search query."""
        brain = NovaBrain(dry_run_power=True)
        brain.initialize()

        res = brain.process("find all python files in NOVA project modified in the last 7 days")
        self.assertEqual(res["intent"], NovaIntent.FIND_ITEM)
        self.assertTrue(res["success"])
        results = res.get("results", [])
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        # Should have found python files in NOVA
        py_files = [r for r in results if r["name"].endswith(".py")]
        self.assertGreater(len(py_files), 0)


if __name__ == "__main__":
    unittest.main()
