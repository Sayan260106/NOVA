"""
Phase 1 Pipeline Tests for Nova
Validates:
1. Standardized ToolResult format (success, message, data, error, undo_info)
2. NovaPlanner step dependency generation & ordering
3. NovaPolicy path safety, drive root protection, system folder guarding, and confirmation checks
4. NovaExecutor safe execution, dependency resolution, failure halting, and post-verification
5. Policy rejection of destructive / protected operations
6. Ambiguity detection and confirmation behavior
"""

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.core.results import ToolResult
from nova.agent.intent_parser import NovaIntent
from nova.agent.planner import NovaPlanner, PlanStep, ExecutionPlan
from nova.agent.policy import NovaPolicy, PolicyDecision
from nova.agent.executor import NovaExecutor
from nova.agent.brain import NovaBrain
from nova.system.file_manager import FileManager


class TestPhase1Pipeline(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sandbox = Path(self.temp_dir.name)
        self.file_manager = FileManager()
        self.policy = NovaPolicy(strict_mode=True, require_confirmation=False, require_disambiguation=False)
        self.planner = NovaPlanner()
        self.executor = NovaExecutor(
            file_manager=self.file_manager,
            policy=self.policy,
            dry_run_power=True,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------
    # 1. Standardized ToolResult Tests
    # -------------------------------------------------------------
    def test_tool_result_structure(self):
        """Verify ToolResult conforms to the standardized contract."""
        res_ok = ToolResult.ok(
            message="Operation succeeded",
            data={"key": "value"},
            undo_info={"action": "delete", "target": "some_path"},
        )
        self.assertTrue(res_ok.success)
        self.assertEqual(res_ok.message, "Operation succeeded")
        self.assertEqual(res_ok.data, {"key": "value"})
        self.assertIsNone(res_ok.error)
        self.assertEqual(res_ok.undo_info, {"action": "delete", "target": "some_path"})
        # Dict backwards-compatibility check
        self.assertTrue(res_ok["success"])
        self.assertEqual(res_ok["message"], "Operation succeeded")
        self.assertEqual(res_ok["key"], "value")

        res_fail = ToolResult.fail(
            error="Access denied",
            message="Failed to access resource",
            data={"attempted": "C:\\Windows"},
        )
        self.assertFalse(res_fail.success)
        self.assertEqual(res_fail.error, "Access denied")
        self.assertEqual(res_fail.message, "Failed to access resource")
        self.assertIsNone(res_fail.undo_info)
        self.assertFalse(res_fail["success"])
        self.assertEqual(res_fail["error"], "Access denied")

    # -------------------------------------------------------------
    # 2. NovaPolicy Safety Tests
    # -------------------------------------------------------------
    def test_policy_blocks_drive_root_deletion(self):
        """Policy must strictly block deletion of drive roots like C:, C:\\, D:, D:\\."""
        protected_targets = ["C:", "c:\\", "D:", "d:/", "C: drive", "D drive"]
        for target in protected_targets:
            step = PlanStep(
                step_id=1,
                action="delete_item",
                intent=NovaIntent.DELETE_ITEM,
                parameters={"name": target, "permanent": True},
            )
            decision = self.policy.check_step(step, file_manager=self.file_manager)
            self.assertFalse(
                decision.allowed,
                f"Policy should have blocked deletion of drive root '{target}'",
            )
            self.assertIn("drive root", decision.reason.lower())

    def test_policy_blocks_critical_system_directories(self):
        """Policy must block deletion or tampering of critical system directories."""
        protected_dirs = ["Windows", "System32", "Program Files", ".git", ".venv", "node_modules"]
        for pdir in protected_dirs:
            step = PlanStep(
                step_id=1,
                action="delete_item",
                intent=NovaIntent.DELETE_ITEM,
                parameters={"name": pdir},
            )
            decision = self.policy.check_step(step, file_manager=self.file_manager)
            self.assertFalse(
                decision.allowed,
                f"Policy should have blocked deletion of protected directory '{pdir}'",
            )
            self.assertIn("protected", decision.reason.lower())

    def test_policy_unsupported_operation_whitelist(self):
        """Policy must block unknown or non-whitelisted intents."""
        step = PlanStep(
            step_id=1,
            action="format_drive",
            intent="MALICIOUS_FORMAT_DRIVE",
            parameters={"target": "C:"},
        )
        decision = self.policy.check_step(step)
        self.assertFalse(decision.allowed)
        self.assertIn("whitelist", decision.reason.lower())

    def test_policy_requires_confirmation_when_strict(self):
        """Policy must flag confirmation for permanent deletion when require_confirmation is True."""
        strict_policy = NovaPolicy(require_confirmation=True)
        step = PlanStep(
            step_id=1,
            action="delete_item",
            intent=NovaIntent.DELETE_ITEM,
            parameters={"name": "test_file.txt", "permanent": True},
        )
        decision = strict_policy.check_step(step)
        self.assertTrue(decision.requires_confirmation)
        self.assertEqual(decision.risk_level, "high")
        self.assertIn("permanently delete", decision.confirmation_prompt)

    # -------------------------------------------------------------
    # 3. Planner Multi-Step & Dependency Tests
    # -------------------------------------------------------------
    def test_planner_creates_dependent_steps_for_compound_commands(self):
        """Planner must decompose compound commands into dependent execution steps."""
        utterance = "Make a folder Alpha inside Beta and create a file note.txt inside Alpha"
        plan = self.planner.build_plan(utterance)
        self.assertTrue(plan.is_compound())
        self.assertGreaterEqual(len(plan.steps), 2)

        # Step 2 must declare dependency on Step 1
        step1 = plan.steps[0]
        step2 = plan.steps[1]
        self.assertEqual(step1.step_id, 1)
        self.assertEqual(step2.step_id, 2)
        self.assertIn(1, step2.dependencies)
        self.assertEqual(step1.intent, NovaIntent.CREATE_FOLDER)
        self.assertEqual(step2.intent, NovaIntent.CREATE_FILE)

    # -------------------------------------------------------------
    # 4. Executor Dependency Halting & Safe Execution Tests
    # -------------------------------------------------------------
    def test_executor_halts_on_step_failure(self):
        """Executor must halt immediately when a dependent step fails, skipping remaining steps."""
        # Create an artificial plan where Step 1 fails (attempting to delete non-existent item)
        # and Step 2 depends on Step 1
        plan = ExecutionPlan(
            intent=NovaIntent.COMPLEX_COMMAND,
            raw_utterance="failed step test",
            steps=[
                PlanStep(
                    step_id=1,
                    action="delete_item",
                    intent=NovaIntent.DELETE_ITEM,
                    parameters={"name": "non_existent_folder_xyz_12345"},
                ),
                PlanStep(
                    step_id=2,
                    action="create_file",
                    intent=NovaIntent.CREATE_FILE,
                    parameters={"name": "should_not_be_created.txt"},
                    dependencies=[1],
                ),
            ],
        )

        result = self.executor.execute_plan(plan)
        self.assertFalse(result.success)
        # Executor halted immediately on step 1 failure
        executed_steps = result.data.get("steps", [])
        self.assertEqual(len(executed_steps), 1)
        self.assertFalse(executed_steps[0]["success"])

    def test_executor_blocks_policy_violations(self):
        """Executor must block steps that fail policy validation and report clear failure."""
        plan = ExecutionPlan(
            intent=NovaIntent.DELETE_ITEM,
            raw_utterance="delete Windows folder",
            steps=[
                PlanStep(
                    step_id=1,
                    action="delete_item",
                    intent=NovaIntent.DELETE_ITEM,
                    parameters={"name": "Windows", "permanent": True},
                )
            ],
        )

        result = self.executor.execute_plan(plan)
        self.assertFalse(result.success)
        self.assertIn("Policy Block", result.message)

    # -------------------------------------------------------------
    # 5. Isolated Sandbox File Operations & Verification
    # -------------------------------------------------------------
    def test_sandbox_file_crud_and_verification(self):
        """Verify real filesystem operations inside an isolated test directory."""
        folder_name = "Phase1TestFolder"
        file_name = "phase1_test.txt"
        file_content = "Safe Isolated Test Content"

        # 1. Create folder in sandbox
        res_folder = self.file_manager.create_folder(folder_name, parent_name=str(self.sandbox))
        self.assertTrue(res_folder.success)
        folder_path = Path(res_folder["path"])
        self.assertTrue(folder_path.exists())

        # 2. Create file in sandbox folder
        res_file = self.file_manager.create_file(
            file_name,
            content=file_content,
            parent_name=str(folder_path),
        )
        self.assertTrue(res_file.success)
        file_path = Path(res_file["path"])
        self.assertTrue(file_path.exists())
        self.assertEqual(file_path.read_text(encoding="utf-8"), file_content)

        # 3. Rename file
        new_file_name = "phase1_renamed.txt"
        res_rename = self.file_manager.rename_item(
            old_name=str(file_path),
            new_name=new_file_name,
        )
        self.assertTrue(res_rename.success)
        new_file_path = folder_path / new_file_name
        self.assertTrue(new_file_path.exists())
        self.assertFalse(file_path.exists())

        # 4. Safe deletion via FileManager
        res_del = self.file_manager.delete_path(new_file_path, permanent=True)
        self.assertTrue(res_del.success)
        self.assertFalse(new_file_path.exists())

    # -------------------------------------------------------------
    # 6. Ambiguity Handling via Brain Disambiguation
    # -------------------------------------------------------------
    def test_ambiguity_detection_and_handling(self):
        """Verify that multiple targets with the same name are detected and handled properly."""
        dir1 = self.sandbox / "SubDir1"
        dir2 = self.sandbox / "SubDir2"
        dir1.mkdir()
        dir2.mkdir()

        (dir1 / "ambiguous.txt").write_text("file 1", encoding="utf-8")
        (dir2 / "ambiguous.txt").write_text("file 2", encoding="utf-8")

        # Use policy with require_disambiguation=True
        policy = NovaPolicy(require_disambiguation=True)
        step = PlanStep(
            step_id=1,
            action="delete_item",
            intent=NovaIntent.DELETE_ITEM,
            parameters={"name": "ambiguous.txt"},
        )
        # Mock file manager finding candidates
        candidates = [dir1 / "ambiguous.txt", dir2 / "ambiguous.txt"]
        decision = PolicyDecision.confirm(
            prompt="Found 2 items with name 'ambiguous.txt'. Disambiguation required.",
            is_ambiguous=True,
            candidates=candidates,
        )
        self.assertTrue(decision.is_ambiguous)
        self.assertEqual(len(decision.candidates), 2)
        self.assertTrue(decision.requires_confirmation)


if __name__ == "__main__":
    unittest.main()
