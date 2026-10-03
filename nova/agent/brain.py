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
from nova.system.app_manager import AppManager
from nova.system.file_manager import FileManager
from nova.system.power_manager import PowerManager
from nova.agent.intent_parser import IntentParser, NovaIntent

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
        self.indexer = Indexer()
        self.app_manager = AppManager()
        self.file_manager = FileManager(indexer=self.indexer)
        self.power_manager = PowerManager()
        self.intent_parser = IntentParser()
        self.ollama = OllamaClient()
        self.history: List[Dict[str, Any]] = []
        self._last_context: Dict[str, Any] = {}
        self._initialized = False

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
        self._initialized = True
        logger.info("Nova Assistant online and ready.")

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
        """Executes deletion of a confirmed specific path."""
        p = Path(target_path) if isinstance(target_path, str) else target_path
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
        """Executes a single structured action step and updates local execution context."""
        intent = step.get("intent", "").upper()

        if intent in ("CREATE_FOLDER", "NEW_FOLDER"):
            name = step.get("name", "").strip().strip("'\" ")
            parent = step.get("parent")
            if context.get("last_folder"):
                last_p = Path(context["last_folder"])
                if parent and parent.strip().strip("'\" ").lower() == last_p.name.lower():
                    parent = str(last_p)
                elif parent:
                    parent = parent.strip().strip("'\" ")
            elif parent:
                parent = parent.strip().strip("'\" ")
            res = self.file_manager.create_folder(folder_name=name, parent_name=parent)
            if res.get("success"):
                context["last_folder"] = res.get("path", name)
            return {
                "intent": NovaIntent.CREATE_FOLDER,
                "success": res.get("success", False),
                "response": res.get("message", res.get("error", "Folder operation completed.")),
                "details": res,
            }

        elif intent in ("CREATE_FILE", "NEW_FILE", "WRITE_FILE"):
            name = step.get("name", "").strip().strip("'\" ")
            content = step.get("content", "")
            parent = step.get("parent")
            # If parent is not explicitly provided, or matches the last created folder's name, use the exact path
            if context.get("last_folder"):
                last_p = Path(context["last_folder"])
                if not parent:
                    parent = str(last_p)
                elif parent and parent.strip().strip("'\" ").lower() == last_p.name.lower():
                    parent = str(last_p)
                else:
                    parent = parent.strip().strip("'\" ")
            elif parent:
                parent = parent.strip().strip("'\" ")

            res = self.file_manager.create_file(file_name=name, content=content, parent_name=parent)
            if res.get("success"):
                context["last_file"] = name
            return {
                "intent": NovaIntent.CREATE_FILE,
                "success": res.get("success", False),
                "response": res.get("message", res.get("error", "File operation completed.")),
                "details": res,
            }

        elif intent == "RENAME_ITEM":
            old_name = step.get("old_name", step.get("old", ""))
            new_name = step.get("new_name", step.get("new", ""))
            is_dir = step.get("is_dir")
            res = self.file_manager.rename_item(old_name=old_name, new_name=new_name, is_dir=is_dir)
            return {
                "intent": NovaIntent.RENAME_ITEM,
                "success": res.get("success", False),
                "response": res.get("message", res.get("error", "Rename operation completed.")),
                "details": res,
            }

        elif intent == "DELETE_ITEM":
            name = step.get("name", "")
            is_dir = step.get("is_dir")
            permanent = step.get("permanent", False)
            res = self.file_manager.delete_item(name=name, is_dir=is_dir, permanent=permanent)
            return {
                "intent": NovaIntent.DELETE_ITEM,
                "success": res.get("success", False),
                "response": res.get("message", res.get("error", "Delete operation completed.")),
                "details": res,
            }

        elif intent == "COPY_ITEM":
            source = step.get("source", "")
            dest = step.get("destination", "")
            res = self.file_manager.copy_item(source_name=source, destination_folder_name=dest)
            return {
                "intent": NovaIntent.COPY_ITEM,
                "success": res.get("success", False),
                "response": res.get("message", res.get("error", "Copy operation completed.")),
                "details": res,
            }

        elif intent == "MOVE_ITEM":
            source = step.get("source", "")
            dest = step.get("destination", "")
            res = self.file_manager.move_item(source_name=source, destination_folder_name=dest)
            return {
                "intent": NovaIntent.MOVE_ITEM,
                "success": res.get("success", False),
                "response": res.get("message", res.get("error", "Move operation completed.")),
                "details": res,
            }

        elif intent == "OPEN_APP":
            app_name = step.get("name", "")
            res = self.app_manager.open_application(app_name)
            return {
                "intent": NovaIntent.OPEN_APP,
                "success": res.get("success", False),
                "response": f"Opening {res.get('app_name', app_name)} now." if res.get("success") else f"Could not launch application '{app_name}'.",
                "details": res,
            }

        elif intent == "OPEN_ITEM":
            item_name = step.get("name", "")
            res = self.file_manager.open_item(item_name)
            return {
                "intent": NovaIntent.OPEN_ITEM,
                "success": res.get("success", False),
                "response": res.get("message", f"Opened item '{item_name}'."),
                "details": res,
            }

        elif intent == "FIND_ITEM":
            query = step.get("query", "")
            kind = step.get("kind", "any")
            results = self.find_anything(query, kind=kind)
            return {
                "intent": NovaIntent.FIND_ITEM,
                "success": True,
                "response": f"Found {len(results)} matching item(s) for '{query}':",
                "results": results,
            }

        elif intent == "SUMMARIZE":
            target_type = step.get("target_type", "text")
            target = step.get("target")
            text = step.get("text")
            parent = step.get("parent")
            return self.summarize_content(target_type=target_type, target=target, text=text, parent=parent)

        elif intent == "LOCK_SYSTEM":
            res = self.power_manager.lock(dry_run=self.dry_run_power)
            return {"intent": NovaIntent.LOCK_SYSTEM, "success": res["success"], "response": res.get("message", res.get("error"))}

        elif intent == "SLEEP_SYSTEM":
            res = self.power_manager.sleep(dry_run=self.dry_run_power)
            return {"intent": NovaIntent.SLEEP_SYSTEM, "success": res["success"], "response": res.get("message", res.get("error"))}

        elif intent == "RESTART_SYSTEM":
            delay = step.get("delay", 0)
            res = self.power_manager.restart(delay_seconds=delay, dry_run=self.dry_run_power)
            return {"intent": NovaIntent.RESTART_SYSTEM, "success": res["success"], "response": res.get("message", res.get("error"))}

        elif intent == "SHUTDOWN_SYSTEM":
            delay = step.get("delay", 0)
            res = self.power_manager.shutdown(delay_seconds=delay, dry_run=self.dry_run_power)
            return {"intent": NovaIntent.SHUTDOWN_SYSTEM, "success": res["success"], "response": res.get("message", res.get("error"))}

        elif intent == "ABORT_POWER":
            res = self.power_manager.abort_shutdown(dry_run=self.dry_run_power)
            return {"intent": NovaIntent.ABORT_POWER, "success": res["success"], "response": res.get("message", res.get("error"))}

        elif intent == "BATTERY_STATUS":
            res = self.power_manager.get_battery_status()
            msg = f"Battery is at {res.get('percent', 0)}% ({res.get('status', 'Unknown')})."
            return {"intent": NovaIntent.BATTERY_STATUS, "success": True, "response": msg, "details": res}

        elif intent == "LANGUAGE_CHART":
            lines = ["JARVIS Component Architecture & Recommended Languages:"]
            for comp, lang in LANGUAGE_CHART.items():
                lines.append(f" • {comp:<32}: {lang}")
            return {"intent": NovaIntent.LANGUAGE_CHART, "success": True, "response": "\n".join(lines), "chart": LANGUAGE_CHART}

        return {"intent": NovaIntent.UNKNOWN, "success": False, "response": f"Unsupported action: {intent}"}

    def process_complex_command(
        self,
        utterance: str,
        sub_commands: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Processes a complex, multi-step, or compound command.
        Uses Ollama decomposition if available, with robust deterministic compound engine fallback.
        """
        # Try Ollama decomposition first if available
        if self.ollama.is_available():
            llm_steps = self.ollama.parse_complex_command(utterance, context=self._last_context)
            if llm_steps and len(llm_steps) > 0:
                logger.info(f"Ollama decomposed command into {len(llm_steps)} step(s).")
                step_results = []
                all_success = True
                step_context = dict(self._last_context)

                for step in llm_steps:
                    res = self.execute_step(step, step_context)
                    step_results.append(res)
                    if not res.get("success", False):
                        all_success = False

                self._last_context.update(step_context)
                responses = [r.get("response", "Done.") for r in step_results]
                return {
                    "intent": NovaIntent.COMPLEX_COMMAND,
                    "success": all_success,
                    "response": "\n".join(responses),
                    "steps": step_results,
                    "source": "ollama",
                }

        # Fallback to rule-based compound engine
        commands = sub_commands or self.intent_parser.split_compound(utterance)
        step_results = []
        all_success = True
        step_context = dict(self._last_context)

        for cmd in commands:
            parsed = self.intent_parser.parse_single(cmd)
            # Context propagation: if CREATE_FILE has no parent and a folder was just created, inherit it
            if parsed.get("intent") == NovaIntent.CREATE_FILE and not parsed.get("parent") and step_context.get("last_folder"):
                parsed["parent"] = step_context["last_folder"]

            res = self.execute_step(parsed, step_context)
            step_results.append(res)
            if not res.get("success", False):
                all_success = False

        self._last_context.update(step_context)
        responses = [r.get("response", "Done.") for r in step_results]
        return {
            "intent": NovaIntent.COMPLEX_COMMAND,
            "success": all_success,
            "response": "\n".join(responses),
            "steps": step_results,
            "source": "compound_engine",
        }

    def process(self, utterance: str) -> Dict[str, Any]:
        """
        Processes a natural language command or user input and executes the appropriate action.
        """
        if not self._initialized:
            self.initialize()

        parsed = self.intent_parser.parse(utterance)
        intent = parsed.get("intent", NovaIntent.UNKNOWN)
        result: Dict[str, Any] = {}

        # 0. Complex / Compound Command
        if intent == NovaIntent.COMPLEX_COMMAND:
            result = self.process_complex_command(utterance, sub_commands=parsed.get("sub_commands"))

        # 1. Summarization
        elif intent == NovaIntent.SUMMARIZE:
            result = self.summarize_content(
                target_type=parsed.get("target_type", "text"),
                target=parsed.get("target"),
                text=parsed.get("text"),
                parent=parsed.get("parent"),
            )

        # 2. Open Application
        elif intent == NovaIntent.OPEN_APP:
            app_name = parsed["name"]
            res = self.app_manager.open_application(app_name)
            if not res["success"]:
                # Fallback: check if it's a file or folder the user wanted to open
                file_res = self.file_manager.open_item(app_name)
                if file_res["success"]:
                    result = {
                        "intent": NovaIntent.OPEN_ITEM,
                        "success": True,
                        "response": f"Opened {file_res['type']} '{file_res['name']}'.",
                        "details": file_res,
                    }
                else:
                    result = {
                        "intent": NovaIntent.OPEN_APP,
                        "success": False,
                        "response": f"Could not find or launch application '{app_name}'.",
                        "details": res,
                    }
            else:
                self._last_context["last_app"] = app_name
                result = {
                    "intent": NovaIntent.OPEN_APP,
                    "success": True,
                    "response": f"Opening {res.get('app_name', app_name)} now.",
                    "details": res,
                }

        # 3. Create Folder
        elif intent == NovaIntent.CREATE_FOLDER:
            res = self.file_manager.create_folder(
                folder_name=parsed["name"],
                parent_name=parsed.get("parent"),
            )
            if res["success"]:
                self._last_context["last_folder"] = res.get("path", parsed["name"])
                result = {
                    "intent": NovaIntent.CREATE_FOLDER,
                    "success": True,
                    "response": res["message"],
                    "details": res,
                }
            else:
                result = {
                    "intent": NovaIntent.CREATE_FOLDER,
                    "success": False,
                    "response": f"Error: {res.get('error')}",
                    "details": res,
                }

        # 4. Create File
        elif intent == NovaIntent.CREATE_FILE:
            parent = parsed.get("parent")
            if not parent and self._last_context.get("last_folder"):
                # If creating file right after creating or referencing a folder without explicit parent
                pass
            res = self.file_manager.create_file(
                file_name=parsed["name"],
                content=parsed.get("content", ""),
                parent_name=parent,
            )
            if res["success"]:
                self._last_context["last_file"] = parsed["name"]
                result = {
                    "intent": NovaIntent.CREATE_FILE,
                    "success": True,
                    "response": res["message"],
                    "details": res,
                }
            else:
                result = {
                    "intent": NovaIntent.CREATE_FILE,
                    "success": False,
                    "response": f"Error: {res.get('error')}",
                    "details": res,
                }

        # 5. Rename Item
        elif intent == NovaIntent.RENAME_ITEM:
            res = self.file_manager.rename_item(
                old_name=parsed["old_name"],
                new_name=parsed["new_name"],
                is_dir=parsed.get("is_dir"),
            )
            if res["success"]:
                result = {
                    "intent": NovaIntent.RENAME_ITEM,
                    "success": True,
                    "response": res["message"],
                    "details": res,
                }
            else:
                result = {
                    "intent": NovaIntent.RENAME_ITEM,
                    "success": False,
                    "response": f"Error: {res.get('error')}",
                    "details": res,
                }

        # 6. Copy Item
        elif intent == NovaIntent.COPY_ITEM:
            res = self.file_manager.copy_item(
                source_name=parsed["source"],
                destination_folder_name=parsed["destination"],
            )
            if res["success"]:
                result = {
                    "intent": NovaIntent.COPY_ITEM,
                    "success": True,
                    "response": res["message"],
                    "details": res,
                }
            else:
                result = {
                    "intent": NovaIntent.COPY_ITEM,
                    "success": False,
                    "response": f"Error: {res.get('error')}",
                    "details": res,
                }

        # 7. Move Item
        elif intent == NovaIntent.MOVE_ITEM:
            res = self.file_manager.move_item(
                source_name=parsed["source"],
                destination_folder_name=parsed["destination"],
            )
            if res["success"]:
                result = {
                    "intent": NovaIntent.MOVE_ITEM,
                    "success": True,
                    "response": res["message"],
                    "details": res,
                }
            else:
                result = {
                    "intent": NovaIntent.MOVE_ITEM,
                    "success": False,
                    "response": f"Error: {res.get('error')}",
                    "details": res,
                }

        # 8. Delete Item
        elif intent == NovaIntent.DELETE_ITEM:
            res = self.file_manager.delete_item(
                name=parsed["name"],
                is_dir=parsed.get("is_dir"),
                permanent=parsed.get("permanent", False),
            )
            if res["success"]:
                result = {
                    "intent": NovaIntent.DELETE_ITEM,
                    "success": True,
                    "response": res["message"],
                    "details": res,
                }
            else:
                result = {
                    "intent": NovaIntent.DELETE_ITEM,
                    "success": False,
                    "response": f"Error: {res.get('error')}",
                    "details": res,
                }

        # 9. Open File or Folder
        elif intent == NovaIntent.OPEN_ITEM:
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
            elif prep["status"] == "single":
                res = self.execute_open(prep["target"])
                result = {
                    "intent": NovaIntent.OPEN_ITEM if not prep["target"].is_app() else NovaIntent.OPEN_APP,
                    "success": res.get("success", False),
                    "response": res.get("message", f"Opened {prep['target'].kind} '{prep['target'].name}'."),
                    "details": res,
                }
            else:
                # Fallback direct resolution
                res = self.file_manager.open_item(item_name)
                if res["success"]:
                    result = {
                        "intent": NovaIntent.OPEN_ITEM,
                        "success": True,
                        "response": res["message"],
                        "details": res,
                    }
                else:
                    app_res = self.app_manager.open_application(item_name)
                    if app_res["success"]:
                        result = {
                            "intent": NovaIntent.OPEN_APP,
                            "success": True,
                            "response": f"Opening application '{app_res.get('app_name', item_name)}'.",
                            "details": app_res,
                        }
                    else:
                        result = {
                            "intent": NovaIntent.OPEN_ITEM,
                            "success": False,
                            "response": f"Error: {res.get('error')}",
                            "details": res,
                        }

        # 10. Find Item
        elif intent == NovaIntent.FIND_ITEM:
            query = parsed["query"]
            kind = parsed.get("kind", "any")
            results = self.find_anything(query, kind=kind)
            count = len(results)
            if count == 0:
                result = {
                    "intent": NovaIntent.FIND_ITEM,
                    "success": True,
                    "response": f"No matches found for '{query}'.",
                    "results": [],
                }
            else:
                result = {
                    "intent": NovaIntent.FIND_ITEM,
                    "success": True,
                    "response": f"Found {count} matching item(s) for '{query}':",
                    "results": results,
                }

        # 11. Power Controls
        elif intent == NovaIntent.LOCK_SYSTEM:
            res = self.power_manager.lock(dry_run=self.dry_run_power)
            result = {
                "intent": NovaIntent.LOCK_SYSTEM,
                "success": res["success"],
                "response": res["message"] if res["success"] else res.get("error"),
                "details": res,
            }

        elif intent == NovaIntent.SLEEP_SYSTEM:
            res = self.power_manager.sleep(dry_run=self.dry_run_power)
            result = {
                "intent": NovaIntent.SLEEP_SYSTEM,
                "success": res["success"],
                "response": res["message"] if res["success"] else res.get("error"),
                "details": res,
            }

        elif intent == NovaIntent.RESTART_SYSTEM:
            delay = parsed.get("delay", 0)
            res = self.power_manager.restart(delay_seconds=delay, dry_run=self.dry_run_power)
            result = {
                "intent": NovaIntent.RESTART_SYSTEM,
                "success": res["success"],
                "response": res["message"] if res["success"] else res.get("error"),
                "details": res,
            }

        elif intent == NovaIntent.SHUTDOWN_SYSTEM:
            delay = parsed.get("delay", 0)
            res = self.power_manager.shutdown(delay_seconds=delay, dry_run=self.dry_run_power)
            result = {
                "intent": NovaIntent.SHUTDOWN_SYSTEM,
                "success": res["success"],
                "response": res["message"] if res["success"] else res.get("error"),
                "details": res,
            }

        elif intent == NovaIntent.ABORT_POWER:
            res = self.power_manager.abort_shutdown(dry_run=self.dry_run_power)
            result = {
                "intent": NovaIntent.ABORT_POWER,
                "success": res["success"],
                "response": res["message"],
                "details": res,
            }

        elif intent == NovaIntent.BATTERY_STATUS:
            res = self.power_manager.get_battery_status()
            if res.get("has_battery"):
                msg = f"Battery is at {res['percent']}% ({res['status']}). Remaining time: {res['time_remaining']}."
            else:
                msg = res.get("message", "Battery details unavailable.")
            result = {
                "intent": NovaIntent.BATTERY_STATUS,
                "success": True,
                "response": msg,
                "details": res,
            }

        # 12. Language Chart
        elif intent == NovaIntent.LANGUAGE_CHART:
            lines = ["JARVIS Component Architecture & Recommended Languages:"]
            for comp, lang in LANGUAGE_CHART.items():
                lines.append(f" • {comp:<32}: {lang}")
            result = {
                "intent": NovaIntent.LANGUAGE_CHART,
                "success": True,
                "response": "\n".join(lines),
                "chart": LANGUAGE_CHART,
            }

        # 13. Help
        elif intent == NovaIntent.HELP:
            help_text = (
                "==========================================================================\n"
                "               NOVA VIRTUAL ASSISTANT - COMMAND REFERENCE\n"
                "==========================================================================\n\n"
                "[APPLICATION MANAGEMENT]\n"
                " • open <app>                   Launch any installed app (e.g. 'open chrome', 'start notepad')\n"
                " • launch / run <app>           Synonyms for launch (e.g. 'launch calculator', 'run terminal')\n"
                " • open app <name>              Explicit app targeting (e.g. 'open app spotify')\n\n"
                "[ZERO-PATH FILE & FOLDER INTELLIGENCE]\n"
                " • create folder <name>         Create in D: drive default (e.g. 'create folder Projects')\n"
                " • create folder <name> in <p>  Create in specific folder (e.g. 'create folder Notes inside Projects')\n"
                " • create file <name>           Create empty file in D: (e.g. 'create file todo.txt')\n"
                " • create file <name> with...   Create with text (e.g. 'create file notes.txt with content 'Hi'')\n"
                " • create file ... inside <p>   Create in specific folder (e.g. 'create file log.txt inside Logs')\n"
                " • rename file/folder <a> to <b> Rename anywhere on PC (e.g. 'rename file draft.txt to final.txt')\n"
                " • copy file/folder <a> to <dest> Auto-resolves destination (e.g. 'copy file report.pdf to Backup')\n"
                " • move file/folder <a> to <dest> Auto-resolves destination (e.g. 'move file data.csv to Archive')\n"
                " • delete file/folder <name>    Safe delete to Recycle Bin (e.g. 'delete file temp.log')\n"
                " • delete ... permanently       Permanent deletion (e.g. 'delete folder Cache permanently')\n"
                " * Disambiguation & Confirmation: If duplicate names exist across drives, Nova asks you\n"
                "   to select the exact path [1-N] and confirms before deleting.\n\n"
                "[UNIVERSAL OPEN (APPS, FILES & FOLDERS)]\n"
                " • open <name>                  Discovers and opens matching app, file, or folder\n"
                " • open file / open folder <n>  Explicit type filtering (e.g. 'open file budget.xlsx')\n"
                " * Disambiguation: If multiple items match, Nova displays choices and confirms before opening.\n\n"
                "[UNIVERSAL SEARCH & DISCOVERY]\n"
                " • find app <name>              Search installed applications (e.g. 'find app spotify')\n"
                " • find file <name>             Search files across all drives (e.g. 'find file budget.xlsx')\n"
                " • find folder <name>           Search directories across drives (e.g. 'find folder Documents')\n"
                " • find / search <query>        Search everything across all logical drives\n\n"
                "[COMPLEX & COMPOUND COMMANDS]\n"
                " • Multi-step chaining          Connect actions with 'and', 'then', 'and then', or ';'\n"
                "   Examples:\n"
                "   - 'Make a folder Demo in Project folder and create a file xyz.txt'\n"
                "   - 'Create folder TestSuite in D: drive and create file results.txt with content 'Passed' inside TestSuite'\n"
                "   - 'create folder Vault then create file keys.txt inside Vault'\n\n"
                "[SUMMARIZATION (100% Local & Offline - Zero API Keys)]\n"
                " • summarize this text: <text>  Summarize direct text via local Ollama or offline fallback\n"
                " • summarize file <filename>    Extract & summarize contents of any document or file\n"
                " • summarize context            Summarize conversational and session action history\n\n"
                "[SYSTEM POWER & SESSION CONTROL]\n"
                " • lock laptop                  Lock Windows workstation screen\n"
                " • sleep laptop                 Put system into standby / sleep\n"
                " • restart laptop [in X sec]    Restart system with optional countdown timer\n"
                " • shutdown laptop [in X sec]   Power off system with optional countdown timer\n"
                " • cancel shutdown              Abort scheduled shutdown or restart\n"
                " • battery status               Display battery percentage, status, and remaining time\n\n"
                "[ARCHITECTURE & TECH STACK]\n"
                " • show language chart          Display 24-component JARVIS language architecture chart\n\n"
                "[SESSION CONTROL]\n"
                " • help                         Display this command reference manual\n"
                " • exit / quit                  Shut down Nova session"
            )
            result = {
                "intent": NovaIntent.HELP,
                "success": True,
                "response": help_text,
            }

        # 14. Unknown -> Try Ollama Complex Decomposition before giving up
        else:
            if self.ollama.is_available():
                complex_res = self.process_complex_command(utterance)
                if complex_res.get("steps") and len(complex_res["steps"]) > 0:
                    result = complex_res
                else:
                    result = {
                        "intent": NovaIntent.UNKNOWN,
                        "success": False,
                        "response": f"I didn't quite catch that. Try saying 'open <app>', 'create folder <name>', 'summarize <text/file>', or 'help'.",
                        "raw": utterance,
                    }
            else:
                result = {
                    "intent": NovaIntent.UNKNOWN,
                    "success": False,
                    "response": f"I didn't quite catch that. Try saying 'open <app>', 'create folder <name>', 'summarize <text/file>', or 'help'.",
                    "raw": utterance,
                }

        # Store in rolling history buffer
        self.history.append({
            "user": utterance,
            "response": result.get("response", ""),
            "intent": result.get("intent", intent),
            "success": result.get("success", False),
        })

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
