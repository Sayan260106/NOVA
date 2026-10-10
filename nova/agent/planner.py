"""
Nova Planner
Converts parsed natural language intents and compound commands into structured,
ordered execution plans with validated parameters, safety flags, and dependency tracking.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import logging

from nova.agent.intent_parser import NovaIntent, IntentParser

logger = logging.getLogger("nova.planner")


@dataclass
class PlanStep:
    """Represents a single atomic operation in an execution plan."""
    step_id: int
    intent: str
    action: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[int] = field(default_factory=list)
    is_destructive: bool = False
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "intent": self.intent,
            "action": self.action,
            "parameters": self.parameters,
            "dependencies": self.dependencies,
            "is_destructive": self.is_destructive,
            "description": self.description,
        }


@dataclass
class ExecutionPlan:
    """Represents a complete ordered plan of operations to satisfy user command."""
    raw_utterance: str
    intent: str
    steps: List[PlanStep] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_valid: bool = True
    error: Optional[str] = None

    def is_compound(self) -> bool:
        return len(self.steps) > 1

    def has_destructive_steps(self) -> bool:
        return any(s.is_destructive for s in self.steps)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_utterance": self.raw_utterance,
            "intent": self.intent,
            "steps": [s.to_dict() for s in self.steps],
            "metadata": self.metadata,
            "is_valid": self.is_valid,
            "error": self.error,
        }


class NovaPlanner:
    """
    Analyzes user intent and builds ordered, dependency-aware ExecutionPlans.
    Validates arguments upfront before any operation touches the filesystem or OS.
    """

    DESTRUCTIVE_INTENTS = {
        NovaIntent.DELETE_ITEM,
        NovaIntent.SHUTDOWN_SYSTEM,
        NovaIntent.RESTART_SYSTEM,
    }

    INTENT_TO_ACTION = {
        NovaIntent.CREATE_FOLDER: "create_folder",
        NovaIntent.CREATE_FILE: "create_file",
        NovaIntent.RENAME_ITEM: "rename_item",
        NovaIntent.DELETE_ITEM: "delete_item",
        NovaIntent.COPY_ITEM: "copy_item",
        NovaIntent.MOVE_ITEM: "move_item",
        NovaIntent.OPEN_APP: "open_application",
        NovaIntent.OPEN_ITEM: "open_item",
        NovaIntent.FIND_ITEM: "find_item",
        NovaIntent.SUMMARIZE: "summarize",
        NovaIntent.LOCK_SYSTEM: "lock",
        NovaIntent.SLEEP_SYSTEM: "sleep",
        NovaIntent.RESTART_SYSTEM: "restart",
        NovaIntent.SHUTDOWN_SYSTEM: "shutdown",
        NovaIntent.ABORT_POWER: "abort_shutdown",
        NovaIntent.BATTERY_STATUS: "battery_status",
        NovaIntent.LANGUAGE_CHART: "language_chart",
        NovaIntent.HELP: "help",
    }

    def __init__(self, intent_parser: Optional[IntentParser] = None):
        self.intent_parser = intent_parser or IntentParser()

    def build_plan(
        self,
        utterance: str,
        parsed_intent: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExecutionPlan:
        """
        Builds a verified, ordered ExecutionPlan for single or compound commands.
        """
        ctx = dict(context or {})
        parsed = parsed_intent or self.intent_parser.parse(utterance)
        intent = parsed.get("intent", NovaIntent.UNKNOWN)

        if intent == NovaIntent.COMPLEX_COMMAND:
            return self._build_compound_plan(utterance, parsed, ctx)
        else:
            return self._build_single_plan(utterance, parsed, ctx)

    def _build_compound_plan(
        self,
        utterance: str,
        parsed: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ExecutionPlan:
        """Decomposes compound utterances into ordered steps with validated dependencies."""
        sub_commands = parsed.get("sub_commands") or self.intent_parser.split_compound(utterance)
        steps: List[PlanStep] = []
        step_id = 1
        last_created_folder_step: Optional[int] = None
        last_created_folder_name: Optional[str] = None

        for sub_cmd in sub_commands:
            sub_parsed = self.intent_parser.parse_single(sub_cmd)
            sub_intent = sub_parsed.get("intent", NovaIntent.UNKNOWN)

            # Argument validation and cleaning
            step_obj, err = self._create_step(step_id, sub_intent, sub_parsed, sub_cmd)
            if err:
                return ExecutionPlan(
                    raw_utterance=utterance,
                    intent=NovaIntent.COMPLEX_COMMAND,
                    steps=[],
                    is_valid=False,
                    error=f"Plan error in step '{sub_cmd}': {err}",
                )

            # Dependency & context linking
            if sub_intent == NovaIntent.CREATE_FOLDER:
                last_created_folder_step = step_id
                last_created_folder_name = step_obj.parameters.get("name")

            elif sub_intent == NovaIntent.CREATE_FILE:
                # If file creation does not specify a parent, or explicitly refers to the folder
                # created in preceding step, establish a formal step dependency
                file_parent = step_obj.parameters.get("parent")
                if not file_parent and last_created_folder_step is not None:
                    step_obj.parameters["parent"] = last_created_folder_name
                    step_obj.dependencies.append(last_created_folder_step)
                    step_obj.parameters["parent_from_step"] = last_created_folder_step
                elif file_parent and last_created_folder_name and file_parent.strip().lower() == last_created_folder_name.strip().lower():
                    step_obj.dependencies.append(last_created_folder_step)
                    step_obj.parameters["parent_from_step"] = last_created_folder_step

            elif sub_intent in (NovaIntent.MOVE_ITEM, NovaIntent.COPY_ITEM):
                # If target destination matches a preceding created folder
                dest = step_obj.parameters.get("destination")
                if dest and last_created_folder_name and dest.strip().lower() == last_created_folder_name.strip().lower():
                    if last_created_folder_step is not None:
                        step_obj.dependencies.append(last_created_folder_step)

            steps.append(step_obj)
            step_id += 1

        return ExecutionPlan(
            raw_utterance=utterance,
            intent=NovaIntent.COMPLEX_COMMAND,
            steps=steps,
            metadata={"source": "planner_compound_engine", "step_count": len(steps)},
            is_valid=True,
        )

    def _build_single_plan(
        self,
        utterance: str,
        parsed: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ExecutionPlan:
        """Constructs an ExecutionPlan for a single intent."""
        intent = parsed.get("intent", NovaIntent.UNKNOWN)
        step_obj, err = self._create_step(1, intent, parsed, utterance)

        if err:
            return ExecutionPlan(
                raw_utterance=utterance,
                intent=intent,
                steps=[],
                is_valid=False,
                error=err,
            )

        return ExecutionPlan(
            raw_utterance=utterance,
            intent=intent,
            steps=[step_obj],
            metadata={"source": "planner_single_engine"},
            is_valid=True,
        )

    def _create_step(
        self,
        step_id: int,
        intent: str,
        parsed_data: Dict[str, Any],
        raw_text: str,
    ) -> tuple[Optional[PlanStep], Optional[str]]:
        """Validates parameters and builds a PlanStep instance."""
        action = self.INTENT_TO_ACTION.get(intent, intent.lower())
        is_destructive = intent in self.DESTRUCTIVE_INTENTS
        params = dict(parsed_data)

        # Validate parameters according to intent rules
        if intent == NovaIntent.CREATE_FOLDER:
            name = params.get("name", "").strip().strip("'\" ")
            if not name:
                return None, "Folder name is missing or empty."
            params["name"] = name
            parent = params.get("parent")
            if parent:
                params["parent"] = parent.strip().strip("'\" ")
            desc = f"Create folder '{name}'" + (f" inside '{params['parent']}'" if parent else " in D: drive")

        elif intent == NovaIntent.CREATE_FILE:
            name = params.get("name", "").strip().strip("'\" ")
            if not name:
                return None, "File name is missing or empty."
            params["name"] = name
            parent = params.get("parent")
            if parent:
                params["parent"] = parent.strip().strip("'\" ")
            content = params.get("content", "")
            desc = f"Create file '{name}'" + (f" with {len(content)} chars" if content else "")

        elif intent == NovaIntent.RENAME_ITEM:
            old_name = params.get("old_name", params.get("old", "")).strip().strip("'\" ")
            new_name = params.get("new_name", params.get("new", "")).strip().strip("'\" ")
            if not old_name:
                return None, "Original item name to rename is missing."
            if not new_name:
                return None, "New item name is missing."
            params["old_name"] = old_name
            params["new_name"] = new_name
            desc = f"Rename '{old_name}' to '{new_name}'"

        elif intent == NovaIntent.DELETE_ITEM:
            name = params.get("name", "").strip().strip("'\" ")
            if not name:
                return None, "Item name to delete is missing."
            params["name"] = name
            permanent = bool(params.get("permanent", False))
            params["permanent"] = permanent
            is_destructive = True
            desc = f"Delete '{name}' {'permanently' if permanent else 'to Recycle Bin'}"

        elif intent in (NovaIntent.COPY_ITEM, NovaIntent.MOVE_ITEM):
            source = params.get("source", "").strip().strip("'\" ")
            dest = params.get("destination", "").strip().strip("'\" ")
            if not source:
                return None, "Source item is missing."
            if not dest:
                return None, "Destination folder is missing."
            params["source"] = source
            params["destination"] = dest
            if intent == NovaIntent.MOVE_ITEM:
                is_destructive = False  # Move is reversible, but tracked
            desc = f"{'Copy' if intent == NovaIntent.COPY_ITEM else 'Move'} '{source}' to '{dest}'"

        elif intent == NovaIntent.OPEN_APP:
            name = params.get("name", "").strip().strip("'\" ")
            if not name:
                return None, "Application name is missing."
            params["name"] = name
            desc = f"Launch application '{name}'"

        elif intent == NovaIntent.OPEN_ITEM:
            name = params.get("name", "").strip().strip("'\" ")
            if not name:
                return None, "Item name to open is missing."
            params["name"] = name
            desc = f"Open item '{name}'"

        elif intent == NovaIntent.FIND_ITEM:
            query = params.get("query", "").strip()
            if not query:
                return None, "Search query is empty."
            params["query"] = query
            desc = f"Search for '{query}'"

        elif intent == NovaIntent.SUMMARIZE:
            target_type = params.get("target_type", "text")
            desc = f"Summarize {target_type}"

        elif intent in (NovaIntent.RESTART_SYSTEM, NovaIntent.SHUTDOWN_SYSTEM):
            delay = int(params.get("delay", 0))
            if delay < 0:
                delay = 0
            params["delay"] = delay
            is_destructive = True
            desc = f"{'Restart' if intent == NovaIntent.RESTART_SYSTEM else 'Shutdown'} system in {delay}s"

        elif intent in (NovaIntent.LOCK_SYSTEM, NovaIntent.SLEEP_SYSTEM, NovaIntent.ABORT_POWER, NovaIntent.BATTERY_STATUS, NovaIntent.LANGUAGE_CHART, NovaIntent.HELP):
            desc = action.replace("_", " ").title()

        else:
            desc = f"Execute {intent}: {raw_text}"

        step = PlanStep(
            step_id=step_id,
            intent=intent,
            action=action,
            parameters=params,
            dependencies=[],
            is_destructive=is_destructive,
            description=desc,
        )
        return step, None
