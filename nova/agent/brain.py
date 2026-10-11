"""
Nova Brain
Central orchestrator for Nova Virtual Assistant.
Integrates AppManager, FileManager, PowerManager, Indexer, IntentParser,
and local LLM intelligence via Ollama.
"""

from pathlib import Path
import logging
from typing import Dict, List, Optional, Any
import threading

from nova.config import LANGUAGE_CHART, DEFAULT_WORKSPACE
from nova.core.indexer import Indexer
from nova.core.llm import OllamaClient
from nova.core.memory import PersistentMemory
from nova.core.action_history import ActionHistory
from nova.system.app_manager import AppManager
from nova.system.file_manager import FileManager
from nova.system.power_manager import PowerManager
from nova.agent.intent_parser import IntentParser, NovaIntent
from nova.agent.planner import NovaPlanner, PlanStep, ExecutionPlan
from nova.agent.policy import NovaPolicy, PolicyDecision
from nova.agent.executor import NovaExecutor
from nova.core.results import ToolResult
from nova.tools.notes import NotesManager
from nova.tools.reminders import ReminderManager
from nova.tools.clipboard import ClipboardManager
from nova.tools.system_diagnostics import SystemDiagnostics
from nova.tools.scheduler import TaskScheduler

logger = logging.getLogger("nova.brain")


class OpenCandidate:
    """Represents a candidate item (file, folder, or application) to be opened."""

    def __init__(
        self,
        kind: str,
        name: str,
        path: Any,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.kind = kind  # 'file', 'folder', or 'application'
        self.name = name
        self.path = Path(path) if kind in ("file", "folder") and not isinstance(path, Path) else path
        self.details = details or {}

    def is_dir(self) -> bool:
        return self.kind == "folder"

    def is_file(self) -> bool:
        return self.kind == "file"

    def is_app(self) -> bool:
        return self.kind == "application"

    def exists(self) -> bool:
        if isinstance(self.path, Path):
            return self.path.exists()
        return True

    def stat(self):
        if isinstance(self.path, Path):
            return self.path.stat()
        raise OSError("Stat not available for application")

    def __str__(self) -> str:
        return str(self.path)

    def __repr__(self) -> str:
        return f"<OpenCandidate {self.kind}: {self.name} -> {self.path}>"

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        if item in self.details:
            return self.details[item]
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        return self.details.get(item, default)


class NovaBrain:
    """The central intelligence and execution engine of Nova Virtual Assistant."""

    def __init__(self, dry_run_power: bool = True):
        self.dry_run_power = dry_run_power
        self.memory = PersistentMemory()
        self.action_history = ActionHistory()
        self.indexer = Indexer()
        self.app_manager = AppManager(memory=self.memory)
        self.file_manager = FileManager(indexer=self.indexer)
        self.power_manager = PowerManager()
        self.intent_parser = IntentParser()
        self.ollama = OllamaClient()

        # Phase 4 Productivity Managers
        self.notes_manager = NotesManager()
        self.reminder_manager = ReminderManager()
        self.clipboard_manager = ClipboardManager()
        self.diagnostics_manager = SystemDiagnostics(power_manager=self.power_manager)

        self.history: List[Dict[str, Any]] = []
        self._last_context: Dict[str, Any] = {}
        self._initialized = False

        # Phase 1, 2, 3 & 4: Planner, Policy, Executor with Memory, History & Productivity Tools
        self.planner = NovaPlanner(intent_parser=self.intent_parser, memory=self.memory)
        self.policy = NovaPolicy(strict_mode=True)
        self.executor = NovaExecutor(
            file_manager=self.file_manager,
            app_manager=self.app_manager,
            power_manager=self.power_manager,
            ollama_client=self.ollama,
            policy=self.policy,
            dry_run_power=self.dry_run_power,
            memory=self.memory,
            action_history=self.action_history,
            notes_manager=self.notes_manager,
            reminder_manager=self.reminder_manager,
            clipboard_manager=self.clipboard_manager,
            diagnostics_manager=self.diagnostics_manager,
        )
        self.scheduler = TaskScheduler(executor=self.executor, action_history=self.action_history)
        self.executor._scheduler = self.scheduler

    def initialize(self) -> None:
        """Initialize all sub-modules, index applications, and check resources."""
        if self._initialized:
            return
        logger.info("Initializing Nova Assistant core modules...")
        self.app_manager.initialize()
        # Background check of Ollama availability
        threading.Thread(target=self._check_ollama, daemon=True).start()
        # Start background indexing of high-priority locations
        threading.Thread(target=self._background_index, daemon=True).start()
        # Start Phase 4 reminder and task scheduler monitors
        self.reminder_manager.start_background_checker()
        self.scheduler.start()
        self._initialized = True
        logger.info("Nova Assistant online and ready.")

    def shutdown(self) -> None:
        """Stops background threads and releases resources."""
        try:
            self.reminder_manager.stop_background_checker()
            self.scheduler.stop()
        except Exception as e:
            logger.debug(f"Shutdown notice: {e}")

    def _check_ollama(self) -> None:
        """Proactively checks local Ollama availability."""
        try:
            available = self.ollama.is_available(force_check=True)
            if available:
                logger.info(f"Ollama local LLM active (Model: {self.ollama.model_name})")
            else:
                logger.info("Ollama not currently detected on localhost:11434. Local rule engines active.")
        except Exception as e:
            logger.debug(f"Ollama check notice: {e}")

    def _background_index(self) -> None:
        """Background thread indexing priority roots and drives for sub-millisecond search."""
        try:
            from nova.config import PRIORITY_SEARCH_ROOTS
            for root in PRIORITY_SEARCH_ROOTS:
                if root.exists():
                    is_drive_root = (root.parent == root or len(str(root).rstrip("\\/")) <= 2)
                    if is_drive_root:
                        continue
                    self.indexer.index_directory(root, max_depth=3, max_files=1000)
        except Exception as e:
            logger.debug(f"Background indexing notice: {e}")

    def prepare_deletion(self, name: str, is_dir: Optional[bool] = None) -> Dict[str, Any]:
        """
        Finds all files or folders matching the exact name to check for duplicates
        and allow user selection before confirmation.
        """
        candidates = self.file_manager.find_all_candidates(name, is_dir=is_dir)
        if not candidates:
            single = self.file_manager.resolve_target(name, is_dir=is_dir)
            if single and single.exists():
                candidates = [single]

        if not candidates:
            return {
                "status": "not_found",
                "name": name,
                "candidates": [],
                "message": f"No file or folder named '{name}' was found to delete.",
            }
        elif len(candidates) == 1:
            return {
                "status": "single",
                "name": name,
                "candidates": candidates,
                "target": candidates[0],
                "message": f"Found 1 item matching '{name}' at {candidates[0]}.",
            }
        else:
            return {
                "status": "multiple",
                "name": name,
                "candidates": candidates,
                "message": f"Found {len(candidates)} items with the name '{name}'.",
            }

    def execute_deletion(self, target_path: Any, permanent: bool = False) -> Dict[str, Any]:
        """Executes deletion of a confirmed specific path with safety validation."""
        p = Path(target_path) if isinstance(target_path, str) else target_path
        is_prot, reason = self.policy.is_protected_path(p)
        if is_prot:
            return ToolResult.fail(
                error=f"Cannot delete protected path: {reason}",
                message=f"Policy Block: Cannot delete protected path: {reason}",
                data={"path": str(p)},
            )
        return self.file_manager.delete_path(p, permanent=permanent)

    def prepare_open(
        self,
        name: str,
        is_dir: Optional[bool] = None,
        kind: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Finds all files, folders, and applications matching target name to allow
        user disambiguation and confirmation before opening.
        """
        clean_name = name.strip()
        lower_name = clean_name.lower()
        candidates: List[OpenCandidate] = []
        seen_keys = set()

        if kind:
            if kind in ("folder", "directory"):
                is_dir = True
            elif kind == "file":
                is_dir = False

        # 1. Search Files & Folders
        if kind not in ("app", "application"):
            file_candidates = self.file_manager.find_open_candidates(clean_name, is_dir=is_dir)
            for p in file_candidates:
                str_p = str(p.resolve()).lower()
                if str_p not in seen_keys:
                    # Skip system/OS program binaries from generic file candidates
                    if p.suffix.lower() == ".exe" and any(sys_dir in str_p for sys_dir in ["c:\\windows", "program files"]):
                        continue
                    seen_keys.add(str_p)
                    c_kind = "folder" if p.is_dir() else "file"
                    candidates.append(
                        OpenCandidate(
                            kind=c_kind,
                            name=p.name,
                            path=p,
                            details={"parent": str(p.parent), "size": p.stat().st_size if p.is_file() else 0},
                        )
                    )

        # 2. Search Applications (if not restricted to folder/file)
        if is_dir is not True and kind not in ("folder", "directory", "file"):
            app_matches = self.app_manager.find_applications(clean_name, limit=3)
            for app, score in app_matches:
                if score >= 0.85 or app.name.lower() == lower_name or app.name.lower().startswith(lower_name):
                    app_key = f"app:{app.name.lower()}"
                    if app_key not in seen_keys:
                        seen_keys.add(app_key)
                        candidates.append(
                            OpenCandidate(
                                kind="application",
                                name=app.name,
                                path=app.path or app.app_id or app.name,
                                details={"source": app.source, "confidence": score},
                            )
                        )

        # 3. Fallback resolution if nothing found yet
        if not candidates:
            resolved_path = self.file_manager.resolve_target(clean_name, is_dir=is_dir)
            if resolved_path and resolved_path.exists():
                c_kind = "folder" if resolved_path.is_dir() else "file"
                candidates.append(
                    OpenCandidate(
                        kind=c_kind,
                        name=resolved_path.name,
                        path=resolved_path,
                        details={"parent": str(resolved_path.parent)},
                    )
                )
            else:
                app_matches = self.app_manager.find_applications(clean_name, limit=1)
                if app_matches and app_matches[0][1] >= 0.65:
                    app = app_matches[0][0]
                    candidates.append(
                        OpenCandidate(
                            kind="application",
                            name=app.name,
                            path=app.path or app.app_id or app.name,
                            details={"source": app.source, "confidence": app_matches[0][1]},
                        )
                    )

        if not candidates:
            return {
                "status": "not_found",
                "name": clean_name,
                "candidates": [],
                "message": f"Could not find any file, folder, or application matching '{clean_name}'.",
            }
        elif len(candidates) == 1:
            return {
                "status": "single",
                "name": clean_name,
                "candidates": candidates,
                "target": candidates[0],
                "message": f"Found 1 item matching '{clean_name}' ({candidates[0].kind}: {candidates[0].name}).",
            }
        else:
            return {
                "status": "multiple",
                "name": clean_name,
                "candidates": candidates,
                "message": f"Found {len(candidates)} items with the name '{clean_name}'.",
            }

    def execute_open(self, target: Any) -> Dict[str, Any]:
        """Executes opening of a confirmed candidate (file, folder, or application)."""
        if isinstance(target, OpenCandidate):
            if target.kind == "application":
                return self.app_manager.open_application(target.name)
            else:
                return self.file_manager.open_path(Path(target.path))

        if isinstance(target, Path):
            return self.file_manager.open_path(target)

        if isinstance(target, dict):
            kind = target.get("kind", target.get("type", ""))
            if kind == "application":
                return self.app_manager.open_application(target.get("name", ""))
            target_path = target.get("path", target.get("target"))
            if target_path:
                return self.file_manager.open_path(Path(target_path))

        if isinstance(target, str):
            p = Path(target)
            if p.exists():
                return self.file_manager.open_path(p)
            return self.app_manager.open_application(target)

        return {"success": False, "error": f"Invalid candidate to open: {target}"}

    def summarize_content(
        self,
        target_type: str = "text",
        target: Optional[str] = None,
        text: Optional[str] = None,
        parent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Summarizes any file, context/conversation history, or raw text using local Ollama.
        """
        # 1. Summarize File
        if target_type == "file" and target:
            clean_file = target.strip().strip("'\" ")
            read_res = self.file_manager.read_file(clean_file, parent_name=parent)
            if not read_res["success"]:
                # Try finding via fuzzy search
                matches = self.file_manager.find_items(clean_file, kind="file", limit=1)
                if matches:
                    read_res = self.file_manager.read_file(matches[0]["name"])

            if not read_res["success"]:
                return {
                    "intent": NovaIntent.SUMMARIZE,
                    "success": False,
                    "response": f"Could not find or read file '{clean_file}' to summarize.",
                    "details": read_res,
                }

            content = read_res["content"]
            summary = self.ollama.summarize(content, context=f"File: {read_res['file_name']}")
            return {
                "intent": NovaIntent.SUMMARIZE,
                "success": True,
                "target_type": "file",
                "file_name": read_res["file_name"],
                "path": read_res["path"],
                "response": f"Summary of '{read_res['file_name']}':\n{summary}",
                "summary": summary,
            }

        # 2. Summarize Context / History
        elif target_type == "context" or (target and any(w in str(target).lower() for w in ["context", "history", "conversation", "session"])):
            if not self.history:
                return {
                    "intent": NovaIntent.SUMMARIZE,
                    "success": True,
                    "target_type": "context",
                    "response": "No previous conversation or actions in context yet to summarize.",
                }
            history_lines = []
            for item in self.history[-6:]:
                user_msg = item.get("user", "").strip()
                resp_msg = item.get("response", "").strip()
                if len(resp_msg) > 160:
                    resp_msg = resp_msg[:160].rsplit(" ", 1)[0] + "..."
                history_lines.append(f"User: {user_msg}\nNova: {resp_msg}")
            context_text = "\n\n".join(history_lines)
            summary = self.ollama.summarize(context_text, context="Summary of recent conversation history and assistant actions")
            return {
                "intent": NovaIntent.SUMMARIZE,
                "success": True,
                "target_type": "context",
                "response": f"Session Context Summary:\n{summary}",
                "summary": summary,
            }

        # 3. Summarize Raw Text
        else:
            raw_text = text or target or ""
            if not raw_text.strip():
                return {
                    "intent": NovaIntent.SUMMARIZE,
                    "success": False,
                    "response": "No text provided to summarize.",
                }
            summary = self.ollama.summarize(raw_text)
            return {
                "intent": NovaIntent.SUMMARIZE,
                "success": True,
                "target_type": "text",
                "response": f"Summary:\n{summary}",
                "summary": summary,
            }

    def execute_step(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Executes a single structured action step using the unified Planner and Executor."""
        intent = step.get("intent", "").upper()
        step_obj, err = self.planner._create_step(1, intent, step, str(step))
        if err or not step_obj:
            return ToolResult.fail(error=err or "Invalid step", message=f"Unsupported action: {intent}")
        plan = ExecutionPlan(raw_utterance=str(step), intent=intent, steps=[step_obj])
        res = self.executor.execute_plan(plan, context=context)
        if res.success:
            if intent in ("CREATE_FOLDER", "NEW_FOLDER"):
                context["last_folder"] = res.get("path", step.get("name"))
            elif intent in ("CREATE_FILE", "NEW_FILE", "WRITE_FILE"):
                context["last_file"] = step.get("name")
        return res

    def process_complex_command(
        self,
        utterance: str,
        sub_commands: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Processes a complex, multi-step, or compound command using Planner and Executor.
        Uses Ollama decomposition if available, with robust deterministic compound engine fallback.
        """
        # 1. Deterministic Planner decomposition if sub_commands parse into valid intents
        split_subs = sub_commands or self.intent_parser.split_compound(utterance)
        if len(split_subs) > 1:
            parsed_subs = [self.intent_parser.parse_single(s) for s in split_subs]
            if all(p.get("intent") not in (NovaIntent.UNKNOWN, None) for p in parsed_subs):
                parsed = {
                    "intent": NovaIntent.COMPLEX_COMMAND,
                    "raw": utterance,
                    "sub_commands": split_subs,
                }
                plan = self.planner.build_plan(utterance, parsed_intent=parsed, context=self._last_context)
                if plan.is_valid:
                    exec_ctx = dict(self._last_context)
                    exec_ctx["history"] = self.history
                    res = self.executor.execute_plan(plan, context=exec_ctx)
                    self._last_context.update(exec_ctx)
                    self._record_history(utterance, res)
                    return res

        # 2. Try Ollama decomposition for conversational or fuzzy compound commands
        if self.ollama.is_available():
            llm_steps = self.ollama.parse_complex_command(utterance, context=self._last_context)
            if llm_steps and len(llm_steps) > 0:
                logger.info(f"Ollama decomposed command into {len(llm_steps)} step(s).")
                step_objs = []
                for idx, s in enumerate(llm_steps, 1):
                    s_intent = s.get("intent", "").upper()
                    st, err = self.planner._create_step(idx, s_intent, s, str(s))
                    if st:
                        step_objs.append(st)
                if step_objs:
                    plan = ExecutionPlan(
                        raw_utterance=utterance,
                        intent=NovaIntent.COMPLEX_COMMAND,
                        steps=step_objs,
                        metadata={"source": "ollama"},
                    )
                    exec_ctx = dict(self._last_context)
                    exec_ctx["history"] = self.history
                    res = self.executor.execute_plan(plan, context=exec_ctx)
                    self._last_context.update(exec_ctx)
                    self._record_history(utterance, res)
                    return res

        # 3. Deterministic Planner & Executor fallback
        parsed = {
            "intent": NovaIntent.COMPLEX_COMMAND,
            "raw": utterance,
            "sub_commands": split_subs,
        }
        plan = self.planner.build_plan(utterance, parsed_intent=parsed, context=self._last_context)
        exec_ctx = dict(self._last_context)
        exec_ctx["history"] = self.history
        res = self.executor.execute_plan(plan, context=exec_ctx)
        self._last_context.update(exec_ctx)
        self._record_history(utterance, res)
        return res

    def _get_help_text(self, topic: Optional[str] = None) -> str:
        """Returns full or topic-filtered Nova command manual."""
        sections = {
            "apps": (
                "[APPLICATION MANAGEMENT]\n"
                " • open <app>                   Launch any installed app (e.g. 'open chrome', 'start notepad')\n"
                " • launch / run <app>           Synonyms for launch (e.g. 'launch calculator', 'run terminal')\n"
                " • open app <name>              Explicit app targeting (e.g. 'open app spotify')\n"
                " • open <name>                  Discovers and opens matching app, file, or folder with disambiguation"
            ),
            "files": (
                "[ZERO-PATH FILE & FOLDER INTELLIGENCE]\n"
                " • create folder <name>         Create in D: drive default (e.g. 'create folder Projects')\n"
                " • create folder <name> in <p>  Create in specific folder (e.g. 'create folder Notes inside Projects')\n"
                " • create file <name>           Create empty file in D: (e.g. 'create file todo.txt')\n"
                " • create file <name> with...   Create with text (e.g. 'create file notes.txt with content 'Hi'')\n"
                " • create file ... inside <p>   Create in specific folder (e.g. 'create file log.txt inside Logs')\n"
                " • rename file/folder <a> to <b> Rename anywhere on PC (e.g. 'rename file draft.txt to final.txt')\n"
                " • copy file/folder <a> to <dest> Auto-resolves destination (e.g. 'copy file report.pdf to Backup')\n"
                " • move file/folder <a> to <dest> Auto-resolves destination (e.g. 'move file data.csv to Archive')\n"
                " • delete file/folder <name>    Safe delete to Recycle Bin with duplicate disambiguation\n"
                " • delete ... permanently       Permanent deletion (e.g. 'delete folder Cache permanently')"
            ),
            "search": (
                "[UNIVERSAL SEARCH & DISCOVERY]\n"
                " • find app <name>              Search installed applications (e.g. 'find app spotify')\n"
                " • find file <name>             Search files across all drives (e.g. 'find file budget.xlsx')\n"
                " • find folder <name>           Search directories across drives (e.g. 'find folder Documents')\n"
                " • find / search <query>        Search everything across all logical drives"
            ),
            "compound": (
                "[COMPLEX & COMPOUND COMMANDS]\n"
                " • Multi-step chaining          Connect actions with 'and', 'then', 'and then', or ';'\n"
                "   Examples:\n"
                "   - 'Make a folder Demo in Project folder and create a file xyz.txt'\n"
                "   - 'Create folder TestSuite in D: drive and create file results.txt with content 'Passed' inside TestSuite'\n"
                "   - 'create folder Vault then create file keys.txt inside Vault'"
            ),
            "memory": (
                "[PERSISTENT MEMORY & USER PREFERENCES]\n"
                " • remember that my NOVA project is in <path>  Store persistent project location\n"
                " • remember that alias <name> is <app>         Store custom app alias\n"
                " • remember that <key> is <value>              Store persistent user preference\n"
                " • what do you remember / recall <key>         Inspect saved memories\n"
                " • forget my <name> project / forget <key>     Remove specific saved memory\n"
                " • clear memories / forget everything          Wipe all stored preferences"
            ),
            "history": (
                "[ACTION HISTORY & AUDIT LOGS]\n"
                " • what did you do today / what files did you move today  Audit log of past actions\n"
                " • show action history                         Inspect recent executed operations\n\n"
                "[UNDO & RECOVERY]\n"
                " • undo / undo the last action / undo last move Safely restores previous reversible state\n"
                " * Pre-flight safety: Validates source existence and destination non-collision before rollback."
            ),
            "notes": (
                "[QUICK NOTES & SCRATCHPAD]\n"
                " • save note <content>          Save quick note across restarts (e.g. 'save note revise OS')\n"
                " • list notes                   Display all saved scratchpad notes\n"
                " • search notes for <query>     Keyword search across notes\n"
                " • read / get note <id>         View full contents of a note\n"
                " • update note <id> with <text> Edit or append to note\n"
                " • delete note <id>             Delete note (reversible via undo)"
            ),
            "reminders": (
                "[REMINDERS & TASK TRACKING]\n"
                " • remind me at <time> to <act> Set time-based reminder (e.g. 'remind me at 8 PM to revise OS')\n"
                " • remind me in <duration> to.. Relative reminder (e.g. 'remind me in 15 minutes to take break')\n"
                " • list reminders               Show pending reminders\n"
                " • complete reminder <id>       Mark reminder finished\n"
                " • dismiss reminder <id>        Dismiss active alert\n"
                " • clear completed reminders    Prune finished reminders"
            ),
            "clipboard": (
                "[CLIPBOARD UTILITIES]\n"
                " • read clipboard               Inspect current clipboard with privacy checks & masking\n"
                " • copy <text> to clipboard     Set system clipboard content\n"
                " • clear clipboard              Securely wipe sensitive clipboard data\n"
                " • save clipboard as note       Convert current clipboard text into a persistent note"
            ),
            "diagnostics": (
                "[SYSTEM DIAGNOSTICS & HEALTH]\n"
                " • check why PC is running slow Intelligent bottleneck diagnostics without killing processes\n"
                " • system diagnostics           Complete CPU, RAM, disk, and top process overview"
            ),
            "scheduler": (
                "[SCHEDULED TASKS & AUTOMATION]\n"
                " • every day at <time>, <action> Schedule approved action (e.g. 'Every day at 9 AM, open my college project')\n"
                " • list scheduled tasks         Display recurring persistent task schedules\n"
                " • cancel schedule <id>         Remove scheduled automation"
            ),
            "power": (
                "[SYSTEM POWER & SESSION CONTROL]\n"
                " • lock laptop                  Lock Windows workstation screen\n"
                " • sleep laptop                 Put system into standby / sleep\n"
                " • restart laptop [in X sec]    Restart system with optional countdown timer\n"
                " • shutdown laptop [in X sec]   Power off system with optional countdown timer\n"
                " • cancel shutdown              Abort scheduled shutdown or restart\n"
                " • battery status               Display battery percentage, status, and remaining time"
            ),
        }

        if topic:
            t = topic.lower().strip()
            for key, content in sections.items():
                if t in key or key in t:
                    header = "==========================================================================\n"
                    header += f"               NOVA HELP MANUAL: {key.upper()}\n"
                    header += "==========================================================================\n\n"
                    return header + content

        # Full command manual
        full = [
            "==========================================================================",
            "               NOVA VIRTUAL ASSISTANT - COMMAND REFERENCE",
            "==========================================================================\n",
        ]
        for sec in sections.values():
            full.append(sec + "\n")

        full.append("[SUMMARIZATION (100% Local & Offline - Zero API Keys)]")
        full.append(" • summarize this text: <text>  Summarize direct text via local Ollama or offline fallback")
        full.append(" • summarize file <filename>    Extract & summarize contents of any document or file")
        full.append(" • summarize context            Summarize conversational and session action history\n")

        full.append("[ARCHITECTURE & TECH STACK]")
        full.append(" • show language chart          Display 24-component JARVIS language architecture chart\n")

        full.append("[SESSION CONTROL]")
        full.append(" • help [topic]                 Display full reference or topic-specific help")
        full.append(" • exit / quit                  Shut down Nova session cleanly")

        return "\n".join(full)

    def _record_history(self, utterance: str, result: Dict[str, Any]) -> None:
        """Records processed interaction in session history."""
        self.history.append({
            "user": utterance,
            "response": result.get("response", ""),
            "intent": result.get("intent", ""),
            "success": result.get("success", False),
        })

    def process(self, utterance: str) -> Dict[str, Any]:
        """
        Processes a natural language command or user input through the Planner,
        Policy, and Executor pipeline.
        """
        if not self._initialized:
            self.initialize()

        raw_clean = utterance.strip()
        parsed = self.intent_parser.parse(raw_clean)
        intent = parsed.get("intent", NovaIntent.UNKNOWN)

        # 0. Complex / Compound Command
        if intent == NovaIntent.COMPLEX_COMMAND:
            return self.process_complex_command(utterance, sub_commands=parsed.get("sub_commands"))

        # 1. Help
        if intent == NovaIntent.HELP or raw_clean.lower() == "help":
            topic = parsed.get("topic")
            help_text = self._get_help_text(topic=topic)
            result = {
                "intent": NovaIntent.HELP,
                "success": True,
                "response": help_text,
                "topic": topic,
            }
            self._record_history(utterance, result)
            return result

        # 2. Open Item disambiguation (if multiple matches exist across filesystem)
        if intent == NovaIntent.OPEN_ITEM and not parsed.get("app"):
            item_name = parsed["name"]
            kind = parsed.get("kind")
            prep = self.prepare_open(item_name, kind=kind)
            if prep["status"] == "multiple":
                result = {
                    "intent": NovaIntent.OPEN_ITEM,
                    "success": False,
                    "status": "multiple",
                    "candidates": prep["candidates"],
                    "response": f"Multiple items found matching '{item_name}'. Please specify which one to open.",
                    "details": prep,
                }
                self._record_history(utterance, result)
                return result
            elif prep["status"] == "single":
                res = self.execute_open(prep["target"])
                result = {
                    "intent": NovaIntent.OPEN_ITEM if not prep["target"].is_app() else NovaIntent.OPEN_APP,
                    "success": res.get("success", False),
                    "response": res.get("message", f"Opened {prep['target'].kind} '{prep['target'].name}'."),
                    "details": res,
                }
                self._record_history(utterance, result)
                return result

        # 3. Unknown intent
        if intent == NovaIntent.UNKNOWN:
            result = {
                "intent": NovaIntent.UNKNOWN,
                "success": False,
                "response": "I didn't quite catch that. Try saying 'open <app>', 'create folder <name>', 'summarize <text/file>', or 'help'.",
                "raw": utterance,
            }
            self._record_history(utterance, result)
            return result

        # 4. Standard Plan & Execute Pipeline
        plan = self.planner.build_plan(utterance, parsed_intent=parsed, context=self._last_context)
        exec_ctx = dict(self._last_context)
        exec_ctx["history"] = self.history
        result = self.executor.execute_plan(plan, context=exec_ctx)

        # Context updates
        if result.success:
            if intent == NovaIntent.CREATE_FOLDER:
                self._last_context["last_folder"] = result.get("path")
            elif intent == NovaIntent.CREATE_FILE:
                self._last_context["last_file"] = parsed.get("name")
            elif intent == NovaIntent.OPEN_APP:
                self._last_context["last_app"] = parsed.get("name")
            elif intent == NovaIntent.OPEN_PROJECT:
                self._last_context["last_project"] = result.get("project")
                self._last_context["last_folder"] = result.get("path")
            elif intent == NovaIntent.REMEMBER:
                if parsed.get("type") == "project_location" or "project" in str(parsed.get("key", "")).lower():
                    self._last_context["last_project"] = parsed.get("key")
                    self._last_context["last_folder"] = parsed.get("value")

        self._record_history(utterance, result)
        return result

    def find_anything(self, query: str, kind: str = "any") -> List[Dict[str, Any]]:
        """
        Unified finder across applications, files, and directories on the laptop.
        kind: 'any', 'app', 'file', 'folder'
        """
        results: List[Dict[str, Any]] = []

        # 1. Search Applications if kind is 'any' or 'app'
        if kind in ("any", "app"):
            app_matches = self.app_manager.find_applications(query, limit=5)
            for app, score in app_matches:
                results.append({
                    "name": app.name,
                    "kind": "application",
                    "source": app.source,
                    "target": app.app_id or app.path or app.name,
                    "confidence": round(score, 2),
                })

        # 2. Search Files and Folders if kind is 'any', 'file', or 'folder'
        if kind in ("any", "file", "folder"):
            f_kind = "any" if kind == "any" else kind
            file_matches = self.file_manager.find_items(query, kind=f_kind, limit=10)
            for item in file_matches:
                results.append({
                    "name": item["name"],
                    "kind": item["type"],
                    "path": item["path"],
                    "size": item.get("size", 0),
                    "parent": item.get("parent_name", ""),
                })

        return results
