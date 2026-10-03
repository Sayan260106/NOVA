"""
Nova Brain - Complex Commands & Summarization Tests
Validates the user requirements:
Goal a) Understand complex / compound commands:
       e.g. "Make a folder 'Demo' in Project folder and create a file 'xyz.txt'"
Goal b) Summarize any text, file, or context for the user without any API keys,
       leveraging local Ollama or offline intelligence.
"""

import sys
import unittest
import shutil
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.agent.brain import NovaBrain
from nova.agent.intent_parser import NovaIntent
from nova.config import DEFAULT_WORKSPACE


class TestComplexBrain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.brain = NovaBrain(dry_run_power=True)
        cls.brain.initialize()

    def setUp(self):
        # Clean up any test folders from previous runs
        for f in ["Project", "TestSuite", "ScratchArea", "SummaryVault"]:
            p = DEFAULT_WORKSPACE / f
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)
                self.brain.indexer.remove_item(p)

    def tearDown(self):
        # Clean up test artifacts
        for f in ["Project", "TestSuite", "ScratchArea", "SummaryVault"]:
            p = DEFAULT_WORKSPACE / f
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)
                self.brain.indexer.remove_item(p)

    def test_goal_a_exact_user_complex_command(self):
        """
        Goal a) Able to understand complex commands:
        'Make a folder 'Demo' in Project folder and create a file 'xyz.txt''
        """
        cmd = "Make a folder 'Demo' in Project folder and create a file 'xyz.txt'"
        result = self.brain.process(cmd)

        self.assertTrue(result.get("success", False), f"Command failed: {result}")
        print(f"\n[Goal A - User Complex Command Result]:\n{result.get('response')}")

        # Verify folder Project was created or resolved
        project_dir = DEFAULT_WORKSPACE / "Project"
        self.assertTrue(project_dir.exists(), f"Expected Project directory at {project_dir}")

        # Verify folder Demo was created inside Project
        demo_dir = project_dir / "Demo"
        self.assertTrue(demo_dir.exists(), f"Expected Demo directory at {demo_dir}")

        # Verify file xyz.txt was created inside Demo
        xyz_file = demo_dir / "xyz.txt"
        self.assertTrue(xyz_file.exists(), f"Expected xyz.txt at {xyz_file}")

    def test_goal_a_complex_command_with_content(self):
        """
        Goal a) Multi-step command with file content and specific locations.
        """
        cmd = "Create folder TestSuite in D: drive and create file results.txt with content 'All test cases passed' inside TestSuite"
        result = self.brain.process(cmd)

        self.assertTrue(result.get("success", False), f"Command failed: {result}")
        print(f"\n[Goal A - Command with Content]:\n{result.get('response')}")

        suite_dir = DEFAULT_WORKSPACE / "TestSuite"
        self.assertTrue(suite_dir.exists(), f"Expected TestSuite at {suite_dir}")

        results_file = suite_dir / "results.txt"
        self.assertTrue(results_file.exists(), f"Expected results.txt at {results_file}")
        self.assertIn("All test cases passed", results_file.read_text(encoding="utf-8"))

    def test_goal_b_summarize_direct_text(self):
        """
        Goal b) Summarize any text provided directly.
        """
        sample_text = (
            "Nova is a local virtual assistant designed to handle system automation, "
            "file management, application execution, and power controls. "
            "It operates completely offline without external cloud dependencies or API keys. "
            "By utilizing local LLMs via Ollama, Nova offers privacy-first intelligence "
            "and natural language comprehension for desktop environments."
        )
        cmd = f"summarize this text: {sample_text}"
        result = self.brain.process(cmd)

        self.assertTrue(result.get("success", False), f"Summarize text failed: {result}")
        self.assertEqual(result.get("intent"), NovaIntent.SUMMARIZE)
        self.assertTrue(len(result.get("response", "")) > 10)
        print(f"\n[Goal B - Summarize Text Result]:\n{result.get('response')}")

    def test_goal_b_summarize_file(self):
        """
        Goal b) Summarize content of an existing file.
        """
        # Create folder and file to summarize
        vault_dir = DEFAULT_WORKSPACE / "SummaryVault"
        vault_dir.mkdir(parents=True, exist_ok=True)
        report_file = vault_dir / "system_analysis.txt"
        report_file.write_text(
            "Project architecture review:\n"
            "1. The Core engine coordinates asynchronous file indexing and instant search.\n"
            "2. AppManager uses Windows shell protocols and Start Menu indexing for zero-latency launching.\n"
            "3. The LLM engine connects to local Ollama on localhost:11434 with zero API keys.\n"
            "4. A heuristic extractive summarizer acts as a high-reliability fallback.\n"
            "Overall the system delivers complete local autonomy and high responsiveness.",
            encoding="utf-8",
        )
        self.brain.indexer.record_item(report_file)

        cmd = "summarize file system_analysis.txt"
        result = self.brain.process(cmd)

        self.assertTrue(result.get("success", False), f"Summarize file failed: {result}")
        self.assertEqual(result.get("intent"), NovaIntent.SUMMARIZE)
        self.assertIn("Summary", result.get("response", ""))
        print(f"\n[Goal B - Summarize File Result]:\n{result.get('response')}")

    def test_goal_b_summarize_context_history(self):
        """
        Goal b) Summarize conversational and action context history.
        """
        # Generate some interaction history
        self.brain.process("create folder ScratchArea")
        self.brain.process("what is the battery status")

        cmd = "summarize context"
        result = self.brain.process(cmd)

        self.assertTrue(result.get("success", False), f"Summarize context failed: {result}")
        self.assertEqual(result.get("intent"), NovaIntent.SUMMARIZE)
        self.assertTrue(len(result.get("response", "")) > 0)
        print(f"\n[Goal B - Summarize Context Result]:\n{result.get('response')}")

    def test_offline_fallback_summarizer(self):
        """
        Verifies that extractive summarization works 100% offline even if Ollama is unreachable.
        """
        from nova.core.llm import OllamaClient
        text = (
            "Machine learning enables computers to learn from experience without being explicitly programmed. "
            "Supervised learning trains models on labeled datasets to make predictions. "
            "Unsupervised learning finds hidden patterns and structures in unlabeled data. "
            "Reinforcement learning trains agents to make sequences of decisions to maximize cumulative reward."
        )
        summary = OllamaClient._local_extractive_summary(text, max_sentences=2)
        self.assertTrue(len(summary) > 0)
        self.assertIn("•", summary)
        print(f"\n[Offline Fallback Summary Output]:\n{summary}")


if __name__ == "__main__":
    unittest.main()
