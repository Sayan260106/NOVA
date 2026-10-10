"""
Nova Policy Engine
Enforces safety rules, path restrictions, operation whitelists, ambiguity detection,
and confirmation gates for all actions before execution begins.
"""

from pathlib import Path
import os
import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set, Tuple

from nova.agent.intent_parser import NovaIntent
from nova.agent.planner import PlanStep
from nova.config import USER_HOME, AVAILABLE_DRIVES

logger = logging.getLogger("nova.policy")


@dataclass
class PolicyDecision:
    """Represents safety assessment and execution clearance for a plan step."""
    allowed: bool
    requires_confirmation: bool = False
    risk_level: str = "low"  # 'low', 'medium', 'high', 'critical'
    reason: Optional[str] = None
    confirmation_prompt: Optional[str] = None
    is_ambiguous: bool = False
    candidates: List[Any] = field(default_factory=list)

    @classmethod
    def permit(cls, reason: str = "Permitted by policy.") -> "PolicyDecision":
        return cls(allowed=True, requires_confirmation=False, risk_level="low", reason=reason)

    @classmethod
    def confirm(
        cls,
        prompt: str,
        risk_level: str = "high",
        reason: str = "Risky operation requires user confirmation.",
        is_ambiguous: bool = False,
        candidates: Optional[List[Any]] = None,
    ) -> "PolicyDecision":
        return cls(
            allowed=True,
            requires_confirmation=True,
            risk_level=risk_level,
            reason=reason,
            confirmation_prompt=prompt,
            is_ambiguous=is_ambiguous,
            candidates=candidates or [],
        )

    @classmethod
    def block(cls, reason: str, risk_level: str = "critical") -> "PolicyDecision":
        return cls(allowed=False, requires_confirmation=False, risk_level=risk_level, reason=reason)


class NovaPolicy:
    """
    Validates filesystem paths, command parameters, ambiguity, and destructive actions.
    No action executes without passing NovaPolicy.
    """

    # Critical system directories that must NEVER be deleted or renamed
    PROTECTED_DIR_NAMES: Set[str] = {
        "windows",
        "system32",
        "syswow64",
        "program files",
        "program files (x86)",
        "programdata",
        "$recycle.bin",
        "system volume information",
        "recovery",
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
    }

    # Whitelist of approved intents
    SUPPORTED_INTENTS: Set[str] = {
        NovaIntent.CREATE_FOLDER,
        NovaIntent.CREATE_FILE,
        NovaIntent.RENAME_ITEM,
        NovaIntent.DELETE_ITEM,
        NovaIntent.COPY_ITEM,
        NovaIntent.MOVE_ITEM,
        NovaIntent.OPEN_APP,
        NovaIntent.OPEN_ITEM,
        NovaIntent.FIND_ITEM,
        NovaIntent.SUMMARIZE,
        NovaIntent.LOCK_SYSTEM,
        NovaIntent.SLEEP_SYSTEM,
        NovaIntent.RESTART_SYSTEM,
        NovaIntent.SHUTDOWN_SYSTEM,
        NovaIntent.ABORT_POWER,
        NovaIntent.BATTERY_STATUS,
        NovaIntent.LANGUAGE_CHART,
        NovaIntent.HELP,
        NovaIntent.ORGANIZE_FOLDER,
        NovaIntent.FIND_DUPLICATES,
        NovaIntent.OPEN_PROJECT,
        NovaIntent.REMEMBER,
        NovaIntent.RECALL,
        NovaIntent.FORGET,
        NovaIntent.ACTION_HISTORY,
        NovaIntent.UNDO,
        NovaIntent.COMPLEX_COMMAND,
    }

    def __init__(
        self,
        strict_mode: bool = False,
        require_confirmation: bool = False,
        require_disambiguation: bool = False,
    ):
        self.strict_mode = strict_mode
        self.require_confirmation = require_confirmation
        self.require_disambiguation = require_disambiguation

    def is_drive_root(self, path: Any) -> bool:
        r"""Determines if a path or string refers to a drive root (e.g. C:, C:\, D:, D:\)."""
        s = str(path).strip().rstrip("\\/").lower()
        if re.match(r"^[a-zA-Z]:?(\s*drive)?$", s):
            return True
        try:
            p = Path(path).resolve()
            if p.parent == p:
                return True
        except Exception:
            pass
        return False

    def is_protected_path(self, target: Any) -> Tuple[bool, str]:
        """
        Validates whether target is a protected system directory or drive root.
        Returns (is_protected, reason).
        """
        if not target:
            return False, ""

        str_target = str(target).strip()
        lower_target = str_target.lower()

        # Check drive root
        if self.is_drive_root(str_target):
            return True, f"Operation targeting drive root '{str_target}' is strictly prohibited."

        # Check raw target name against blacklist
        base_name = Path(str_target).name.lower()
        if base_name in self.PROTECTED_DIR_NAMES:
            return True, f"Directory '{base_name}' is a protected system or workspace directory."

        # Check resolved path
        try:
            resolved = Path(str_target).resolve()
            # Check drive root after resolution
            if resolved.parent == resolved:
                return True, f"Resolved target '{resolved}' is a logical drive root."

            # Check if within Windows OS folders
            win_dir = os.environ.get("WINDIR", r"C:\Windows").lower()
            prog_files = os.environ.get("ProgramFiles", r"C:\Program Files").lower()
            prog_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)").lower()

            str_resolved = str(resolved).lower()
            if str_resolved == win_dir or str_resolved.startswith(win_dir + "\\"):
                return True, f"Target '{resolved}' is located inside the Windows OS system directory."
            if str_resolved == prog_files or str_resolved.startswith(prog_files + "\\"):
                return True, f"Target '{resolved}' is located inside Program Files."
            if str_resolved == prog_files_x86 or str_resolved.startswith(prog_files_x86 + "\\"):
                return True, f"Target '{resolved}' is located inside Program Files (x86)."

            for part in resolved.parts:
                if part.lower() in self.PROTECTED_DIR_NAMES:
                    return True, f"Path contains protected directory component '{part}'."

        except Exception as e:
            logger.debug(f"Path resolution check notice: {e}")

        return False, ""

    def check_step(
        self,
        step: PlanStep,
        file_manager: Optional[Any] = None,
        dry_run_power: bool = True,
    ) -> PolicyDecision:
        """
        Evaluates a single PlanStep against safety policies, path validation, and confirmation rules.
        """
        intent = step.intent
        req_disambig = step.parameters.get("require_disambiguation", self.require_disambiguation)
        req_confirm = step.parameters.get("require_confirmation", self.require_confirmation)

        # 1. Operation Whitelist Check
        if intent not in self.SUPPORTED_INTENTS:
            return PolicyDecision.block(f"Action '{intent}' is not in supported operations whitelist.")

        # 2. Deletion Safety & Ambiguity
        if intent == NovaIntent.DELETE_ITEM:
            name = step.parameters.get("name", "")
            is_dir = step.parameters.get("is_dir")
            permanent = step.parameters.get("permanent", False)

            # Check if name points to a protected path or drive root
            is_prot, reason = self.is_protected_path(name)
            if is_prot:
                return PolicyDecision.block(f"Cannot delete protected path: {reason}")

            # If file_manager is provided, resolve target and check for ambiguity
            if file_manager is not None:
                candidates = file_manager.find_all_candidates(name, is_dir=is_dir)
                if not candidates:
                    single = file_manager.resolve_target(name, is_dir=is_dir)
                    if single and single.exists():
                        candidates = [single]

                # Check if resolved candidates contain protected paths
                for c in candidates:
                    c_prot, c_reason = self.is_protected_path(c)
                    if c_prot:
                        return PolicyDecision.block(f"Candidate '{c}' is protected: {c_reason}")

                # Ambiguity detected (multiple matching files/folders)
                if len(candidates) > 1 and req_disambig:
                    prompt = f"Found {len(candidates)} items with name '{name}'. Disambiguation required."
                    return PolicyDecision.confirm(
                        prompt=prompt,
                        risk_level="high",
                        reason="Multiple matching targets exist.",
                        is_ambiguous=True,
                        candidates=candidates,
                    )

            # High risk if permanent deletion
            if permanent and req_confirm:
                return PolicyDecision.confirm(
                    prompt=f"Are you sure you want to permanently delete '{name}'?",
                    risk_level="high",
                    reason="Permanent deletion cannot be undone via Recycle Bin.",
                )

            return PolicyDecision.permit(f"Safe deletion permitted for '{name}'.")

        # 3. Rename Safety
        elif intent == NovaIntent.RENAME_ITEM:
            old_name = step.parameters.get("old_name", "")
            new_name = step.parameters.get("new_name", "")

            is_prot, reason = self.is_protected_path(old_name)
            if is_prot:
                return PolicyDecision.block(f"Cannot rename protected path: {reason}")

            is_prot_new, reason_new = self.is_protected_path(new_name)
            if is_prot_new:
                return PolicyDecision.block(f"Cannot rename to protected name: {reason_new}")

            return PolicyDecision.permit()

        # 4. Folder / File Creation Safety
        elif intent in (NovaIntent.CREATE_FOLDER, NovaIntent.CREATE_FILE):
            parent = step.parameters.get("parent")
            if parent:
                # Disallow creating files/folders inside system directories
                is_prot, reason = self.is_protected_path(parent)
                # Note: creating inside drive root like D: or D:\ is allowed!
                if is_prot and not self.is_drive_root(parent):
                    return PolicyDecision.block(f"Cannot create items inside protected directory: {reason}")

            return PolicyDecision.permit()

        # 5. Move / Copy Safety
        elif intent in (NovaIntent.MOVE_ITEM, NovaIntent.COPY_ITEM):
            source = step.parameters.get("source", "")
            dest = step.parameters.get("destination", "")

            if intent == NovaIntent.MOVE_ITEM:
                is_prot, reason = self.is_protected_path(source)
                if is_prot:
                    return PolicyDecision.block(f"Cannot move protected path: {reason}")

            is_prot_dest, reason_dest = self.is_protected_path(dest)
            if is_prot_dest and not self.is_drive_root(dest):
                return PolicyDecision.block(f"Cannot copy/move into protected path: {reason_dest}")

            return PolicyDecision.permit()

        # 6. Power Commands Safety
        elif intent in (NovaIntent.RESTART_SYSTEM, NovaIntent.SHUTDOWN_SYSTEM):
            if not dry_run_power:
                action_name = "restart" if intent == NovaIntent.RESTART_SYSTEM else "shutdown"
                return PolicyDecision.confirm(
                    prompt=f"Confirmation required: Proceed with system {action_name}?",
                    risk_level="critical",
                    reason=f"Live system {action_name} will terminate running sessions.",
                )
            return PolicyDecision.permit("Dry-run power command permitted.")

        # 7. Folder Organization Safety
        elif intent == NovaIntent.ORGANIZE_FOLDER:
            folder = step.parameters.get("folder", "")
            is_prot, reason = self.is_protected_path(folder)
            if is_prot:
                return PolicyDecision.block(f"Cannot organize protected path: {reason}")
            return PolicyDecision.permit()

        return PolicyDecision.permit()
