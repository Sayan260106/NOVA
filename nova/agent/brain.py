"""
Nova Brain
Central orchestrator for Nova Virtual Assistant.
Integrates AppManager, FileManager, PowerManager, Indexer, and IntentParser.
"""

from pathlib import Path
import logging
from typing import Dict, List, Optional, Any

from nova.config import LANGUAGE_CHART, DEFAULT_WORKSPACE
from nova.core.indexer import Indexer
from nova.system.app_manager import AppManager
from nova.system.file_manager import FileManager
from nova.system.power_manager import PowerManager
from nova.agent.intent_parser import IntentParser, NovaIntent

import threading

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
        self._initialized = False

    def initialize(self) -> None:
        """Initialize all sub-modules, index applications, and check resources."""
        if self._initialized:
            return
        logger.info("Initializing Nova Assistant core modules...")
        self.app_manager.initialize()
        # Start background indexing of high-priority locations
        threading.Thread(target=self._background_index, daemon=True).start()
        self._initialized = True
        logger.info("Nova Assistant online and ready.")

    def _background_index(self) -> None:
        """Background thread indexing priority roots and drives for sub-millisecond search."""
        try:
            from nova.config import PRIORITY_SEARCH_ROOTS
            for root in PRIORITY_SEARCH_ROOTS:
                if root.exists():
                    self.indexer.index_directory(root, max_depth=3, max_files=5000)
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

    def process(self, utterance: str) -> Dict[str, Any]:
        """
        Processes a natural language command or user input and executes the appropriate action.
        """
        if not self._initialized:
            self.initialize()

        parsed = self.intent_parser.parse(utterance)
        intent = parsed.get("intent", NovaIntent.UNKNOWN)

        # 1. Open Application
        if intent == NovaIntent.OPEN_APP:
            app_name = parsed["name"]
            res = self.app_manager.open_application(app_name)
            if not res["success"]:
                # Fallback: check if it's a file or folder the user wanted to open
                file_res = self.file_manager.open_item(app_name)
                if file_res["success"]:
                    return {
                        "intent": NovaIntent.OPEN_ITEM,
                        "success": True,
                        "response": f"Opened {file_res['type']} '{file_res['name']}'.",
                        "details": file_res,
                    }
                return {
                    "intent": NovaIntent.OPEN_APP,
                    "success": False,
                    "response": f"Could not find or launch application '{app_name}'.",
                    "details": res,
                }
            return {
                "intent": NovaIntent.OPEN_APP,
                "success": True,
                "response": f"Opening {res.get('app_name', app_name)} now.",
                "details": res,
            }

        # 2. Create Folder
        elif intent == NovaIntent.CREATE_FOLDER:
            res = self.file_manager.create_folder(
                folder_name=parsed["name"],
                parent_name=parsed.get("parent"),
            )
            if res["success"]:
                return {
                    "intent": NovaIntent.CREATE_FOLDER,
                    "success": True,
                    "response": res["message"],
                    "details": res,
                }
            return {
                "intent": NovaIntent.CREATE_FOLDER,
                "success": False,
                "response": f"Error: {res.get('error')}",
                "details": res,
            }

        # 3. Create File
        elif intent == NovaIntent.CREATE_FILE:
            res = self.file_manager.create_file(
                file_name=parsed["name"],
                content=parsed.get("content", ""),
                parent_name=parsed.get("parent"),
            )
            if res["success"]:
                return {
                    "intent": NovaIntent.CREATE_FILE,
                    "success": True,
                    "response": res["message"],
                    "details": res,
                }
            return {
                "intent": NovaIntent.CREATE_FILE,
                "success": False,
                "response": f"Error: {res.get('error')}",
                "details": res,
            }

        # 4. Rename Item
        elif intent == NovaIntent.RENAME_ITEM:
            res = self.file_manager.rename_item(
                old_name=parsed["old_name"],
                new_name=parsed["new_name"],
                is_dir=parsed.get("is_dir"),
            )
            if res["success"]:
                return {
                    "intent": NovaIntent.RENAME_ITEM,
                    "success": True,
                    "response": res["message"],
                    "details": res,
                }
            return {
                "intent": NovaIntent.RENAME_ITEM,
                "success": False,
                "response": f"Error: {res.get('error')}",
                "details": res,
            }

        # 5. Copy Item
        elif intent == NovaIntent.COPY_ITEM:
            res = self.file_manager.copy_item(
                source_name=parsed["source"],
                destination_folder_name=parsed["destination"],
            )
            if res["success"]:
                return {
                    "intent": NovaIntent.COPY_ITEM,
                    "success": True,
                    "response": res["message"],
                    "details": res,
                }
            return {
                "intent": NovaIntent.COPY_ITEM,
                "success": False,
                "response": f"Error: {res.get('error')}",
                "details": res,
            }

        # 5. Move Item
        elif intent == NovaIntent.MOVE_ITEM:
            res = self.file_manager.move_item(
                source_name=parsed["source"],
                destination_folder_name=parsed["destination"],
            )
            if res["success"]:
                return {
                    "intent": NovaIntent.MOVE_ITEM,
                    "success": True,
                    "response": res["message"],
                    "details": res,
                }
            return {
                "intent": NovaIntent.MOVE_ITEM,
                "success": False,
                "response": f"Error: {res.get('error')}",
                "details": res,
            }

        # 6. Delete Item
        elif intent == NovaIntent.DELETE_ITEM:
            res = self.file_manager.delete_item(
                name=parsed["name"],
                is_dir=parsed.get("is_dir"),
                permanent=parsed.get("permanent", False),
            )
            if res["success"]:
                return {
                    "intent": NovaIntent.DELETE_ITEM,
                    "success": True,
                    "response": res["message"],
                    "details": res,
                }
            return {
                "intent": NovaIntent.DELETE_ITEM,
                "success": False,
                "response": f"Error: {res.get('error')}",
                "details": res,
            }

        # 7. Open File or Folder
        elif intent == NovaIntent.OPEN_ITEM:
            item_name = parsed["name"]
            kind = parsed.get("kind")
            prep = self.prepare_open(item_name, kind=kind)
            if prep["status"] == "multiple":
                return {
                    "intent": NovaIntent.OPEN_ITEM,
                    "success": False,
                    "status": "multiple",
                    "candidates": prep["candidates"],
                    "response": f"Multiple items found matching '{item_name}'. Please specify which one to open.",
                    "details": prep,
                }
            elif prep["status"] == "single":
                res = self.execute_open(prep["target"])
                return {
                    "intent": NovaIntent.OPEN_ITEM if not prep["target"].is_app() else NovaIntent.OPEN_APP,
                    "success": res.get("success", False),
                    "response": res.get("message", f"Opened {prep['target'].kind} '{prep['target'].name}'."),
                    "details": res,
                }

            # Fallback direct resolution
            res = self.file_manager.open_item(item_name)
            if res["success"]:
                return {
                    "intent": NovaIntent.OPEN_ITEM,
                    "success": True,
                    "response": res["message"],
                    "details": res,
                }
            # Fallback to check app
            app_res = self.app_manager.open_application(item_name)
            if app_res["success"]:
                return {
                    "intent": NovaIntent.OPEN_APP,
                    "success": True,
                    "response": f"Opening application '{app_res.get('app_name', item_name)}'.",
                    "details": app_res,
                }
            return {
                "intent": NovaIntent.OPEN_ITEM,
                "success": False,
                "response": f"Error: {res.get('error')}",
                "details": res,
            }

        # 8. Find Item (Application, File, or Folder)
        elif intent == NovaIntent.FIND_ITEM:
            query = parsed["query"]
            kind = parsed.get("kind", "any")

            results = self.find_anything(query, kind=kind)
            count = len(results)
            if count == 0:
                return {
                    "intent": NovaIntent.FIND_ITEM,
                    "success": True,
                    "response": f"No matches found for '{query}'.",
                    "results": [],
                }
            return {
                "intent": NovaIntent.FIND_ITEM,
                "success": True,
                "response": f"Found {count} matching item(s) for '{query}':",
                "results": results,
            }

        # 9. Power Controls
        elif intent == NovaIntent.LOCK_SYSTEM:
            res = self.power_manager.lock(dry_run=self.dry_run_power)
            return {
                "intent": NovaIntent.LOCK_SYSTEM,
                "success": res["success"],
                "response": res["message"] if res["success"] else res.get("error"),
                "details": res,
            }

        elif intent == NovaIntent.SLEEP_SYSTEM:
            res = self.power_manager.sleep(dry_run=self.dry_run_power)
            return {
                "intent": NovaIntent.SLEEP_SYSTEM,
                "success": res["success"],
                "response": res["message"] if res["success"] else res.get("error"),
                "details": res,
            }

        elif intent == NovaIntent.RESTART_SYSTEM:
            delay = parsed.get("delay", 0)
            res = self.power_manager.restart(delay_seconds=delay, dry_run=self.dry_run_power)
            return {
                "intent": NovaIntent.RESTART_SYSTEM,
                "success": res["success"],
                "response": res["message"] if res["success"] else res.get("error"),
                "details": res,
            }

        elif intent == NovaIntent.SHUTDOWN_SYSTEM:
            delay = parsed.get("delay", 0)
            res = self.power_manager.shutdown(delay_seconds=delay, dry_run=self.dry_run_power)
            return {
                "intent": NovaIntent.SHUTDOWN_SYSTEM,
                "success": res["success"],
                "response": res["message"] if res["success"] else res.get("error"),
                "details": res,
            }

        elif intent == NovaIntent.ABORT_POWER:
            res = self.power_manager.abort_shutdown(dry_run=self.dry_run_power)
            return {
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
            return {
                "intent": NovaIntent.BATTERY_STATUS,
                "success": True,
                "response": msg,
                "details": res,
            }

        elif intent == NovaIntent.LANGUAGE_CHART:
            lines = ["JARVIS Component Architecture & Recommended Languages:"]
            for comp, lang in LANGUAGE_CHART.items():
                lines.append(f" • {comp:<32}: {lang}")
            return {
                "intent": NovaIntent.LANGUAGE_CHART,
                "success": True,
                "response": "\n".join(lines),
                "chart": LANGUAGE_CHART,
            }

        elif intent == NovaIntent.HELP:
            help_text = (
                "Nova Commands:\n"
                " • Open applications: 'open chrome', 'launch calculator', 'start notepad'\n"
                " • Zero-path Files: 'create file todo.txt with content 'My note'', 'copy todo.txt to Backup'\n"
                " • Zero-path Folders: 'create folder Projects', 'create folder Notes inside Projects'\n"
                " • Rename: 'rename file old.txt to new.txt', 'rename folder OldProject to NewProject'\n"
                " • Power: 'lock laptop', 'sleep laptop', 'restart laptop', 'shutdown laptop'\n"
                " • Universal Search: 'find app spotify', 'find file report.pdf', 'find folder Documents'\n"
                " • Architecture Chart: 'show language chart'\n"
            )
            return {
                "intent": NovaIntent.HELP,
                "success": True,
                "response": help_text,
            }

        else:
            return {
                "intent": NovaIntent.UNKNOWN,
                "success": False,
                "response": f"I didn't quite catch that. Try saying 'open <app>', 'create folder <name>', 'find <query>', or 'help'.",
                "raw": utterance,
            }

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
