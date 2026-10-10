"""
Nova Action History and Audit Log Module
Persistently records executed actions, affected paths, outcomes, and reversible undo metadata.
Provides rollback validation and safe restoration.
"""

import os
import time
import json
import uuid
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Tuple
from contextlib import contextmanager

from nova.config import ACTION_HISTORY_DB_PATH
from nova.core.results import ToolResult

logger = logging.getLogger("nova.action_history")


class ActionHistory:
    """
    Manages audit logging of all executed assistant actions, queryable history,
    and safe, validated rollback capabilities.
    """

    UNDOABLE_ACTIONS = {
        "move_item", "MOVE_ITEM",
        "rename_item", "RENAME_ITEM",
        "create_file", "CREATE_FILE",
        "create_folder", "CREATE_FOLDER",
        "copy_item", "COPY_ITEM",
    }

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        self.db_path = Path(db_path) if db_path else ACTION_HISTORY_DB_PATH
        self._cache: List[Dict[str, Any]] = []
        self._db_ok = True
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """Yields SQLite connection with WAL journal mode, closing upon exit."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Initializes schema and indices."""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS action_history (
                        action_id TEXT PRIMARY KEY,
                        timestamp REAL NOT NULL,
                        iso_time TEXT NOT NULL,
                        user_command TEXT,
                        intent TEXT NOT NULL,
                        action TEXT NOT NULL,
                        parameters TEXT NOT NULL,
                        affected_paths TEXT NOT NULL,
                        success INTEGER NOT NULL,
                        result_message TEXT,
                        error TEXT,
                        undo_info TEXT,
                        is_undone INTEGER DEFAULT 0
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_action_timestamp ON action_history(timestamp);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_action_intent ON action_history(intent);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_action_undone ON action_history(is_undone);")
                conn.commit()
            self._db_ok = True
        except Exception as e:
            logger.warning(f"Could not initialize ActionHistory SQLite database at {self.db_path}: {e}. Falling back to in-memory mode.")
            self._db_ok = False

    def record_action(
        self,
        intent: str,
        action: Optional[str] = None,
        user_command: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        affected_paths: Optional[List[Union[str, Path]]] = None,
        success: bool = True,
        result_message: str = "",
        error: Optional[str] = None,
        undo_info: Optional[Dict[str, Any]] = None,
        command: Optional[str] = None,
        planned_operations: Optional[Any] = None,
        error_message: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Records an executed action and its outcome in audit history.
        Returns the unique action_id.
        """
        action_id = str(uuid.uuid4())
        now = time.time()
        iso_str = datetime.fromtimestamp(now).isoformat()

        cmd = user_command or command or ""
        act = action or (planned_operations[0].get("action") if (planned_operations and isinstance(planned_operations, list)) else str(intent))
        params = parameters or ({"planned_operations": planned_operations} if planned_operations else {})
        err = error or error_message

        norm_paths = [str(Path(p).resolve()) for p in (affected_paths or []) if p]
        params_json = json.dumps(params)
        paths_json = json.dumps(norm_paths)
        undo_json = json.dumps(undo_info) if undo_info else None

        record = {
            "id": action_id,
            "action_id": action_id,
            "timestamp": now,
            "iso_time": iso_str,
            "command": cmd,
            "user_command": cmd,
            "intent": str(intent),
            "action": str(act),
            "parameters": params,
            "affected_paths": norm_paths,
            "success": success,
            "result_message": result_message,
            "error": err,
            "undo_info": undo_info,
            "undone": False,
            "is_undone": False,
        }
        self._cache.append(record)

        if not self._db_ok:
            return action_id

        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO action_history (
                        action_id, timestamp, iso_time, user_command, intent, action,
                        parameters, affected_paths, success, result_message, error,
                        undo_info, is_undone
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """, (
                    action_id, now, iso_str, cmd, str(intent), str(act),
                    params_json, paths_json, 1 if success else 0, result_message, err,
                    undo_json,
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to record action in database: {e}")

        return action_id

    def _parse_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Parses a database row into a structured record."""
        return {
            "id": row["action_id"],
            "action_id": row["action_id"],
            "timestamp": row["timestamp"],
            "iso_time": row["iso_time"],
            "command": row["user_command"],
            "user_command": row["user_command"],
            "intent": row["intent"],
            "action": row["action"],
            "parameters": json.loads(row["parameters"]) if row["parameters"] else {},
            "affected_paths": json.loads(row["affected_paths"]) if row["affected_paths"] else [],
            "success": bool(row["success"]),
            "result_message": row["result_message"],
            "error": row["error"],
            "undo_info": json.loads(row["undo_info"]) if row["undo_info"] else None,
            "undone": bool(row["is_undone"]),
            "is_undone": bool(row["is_undone"]),
        }

    def get_recent_actions(
        self,
        limit: int = 20,
        intent: Optional[str] = None,
        success_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """Queries recent actions from history."""
        if not self._db_ok:
            actions = list(reversed(self._cache))
            if intent:
                actions = [a for a in actions if a["intent"] == intent]
            if success_only:
                actions = [a for a in actions if a["success"]]
            return actions[:limit]

        try:
            with self._get_connection() as conn:
                query = "SELECT * FROM action_history WHERE 1=1"
                params = []
                if intent:
                    query += " AND intent = ?"
                    params.append(intent)
                if success_only:
                    query += " AND success = 1"
                query += " ORDER BY timestamp DESC LIMIT ?"
                params.append(limit)

                rows = conn.execute(query, tuple(params)).fetchall()
                return [self._parse_row(r) for r in rows]
        except Exception as e:
            logger.error(f"Failed to fetch recent actions: {e}")
            return list(reversed(self._cache))[:limit]

    def get_actions_today(
        self,
        intent: Optional[str] = None,
        action: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves all actions performed since midnight today (local time).
        Example: 'What files did you move today?'
        """
        now = datetime.now()
        midnight_today = datetime(now.year, now.month, now.day).timestamp()

        if not self._db_ok:
            actions = [a for a in self._cache if a["timestamp"] >= midnight_today and a["success"]]
            if intent:
                actions = [a for a in actions if a["intent"] == intent]
            if action:
                actions = [a for a in actions if a["action"] == action]
            return sorted(actions, key=lambda x: x["timestamp"], reverse=True)

        try:
            with self._get_connection() as conn:
                query = "SELECT * FROM action_history WHERE timestamp >= ? AND success = 1"
                params = [midnight_today]
                if intent:
                    query += " AND intent = ?"
                    params.append(intent)
                if action:
                    query += " AND action = ?"
                    params.append(action)
                query += " ORDER BY timestamp DESC"

                rows = conn.execute(query, tuple(params)).fetchall()
                return [self._parse_row(r) for r in rows]
        except Exception as e:
            logger.error(f"Failed to query actions today: {e}")
            return []

    def get_last_undoable_action(
        self,
        intent_filter: Optional[str] = None,
        intent: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Finds the most recent successful operation that has valid undo_info
        and has not yet been rolled back.
        """
        filt = intent_filter or intent
        if not self._db_ok:
            for item in reversed(self._cache):
                if item["success"] and not item["is_undone"] and item.get("undo_info"):
                    if not filt or item["intent"] == filt:
                        return item
            return None

        try:
            with self._get_connection() as conn:
                query = """
                    SELECT * FROM action_history
                    WHERE success = 1
                      AND is_undone = 0
                      AND undo_info IS NOT NULL
                """
                params = []
                if filt:
                    query += " AND intent = ?"
                    params.append(filt)
                query += " ORDER BY timestamp DESC LIMIT 1"

                row = conn.execute(query, tuple(params)).fetchone()
                return self._parse_row(row) if row else None
        except Exception as e:
            logger.error(f"Failed to fetch last undoable action: {e}")
            return None

    def mark_as_undone(self, action_id: str) -> bool:
        """Marks an action as rolled back so it cannot be undone twice."""
        for item in self._cache:
            if item["action_id"] == action_id:
                item["is_undone"] = True

        if not self._db_ok:
            return True

        try:
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE action_history SET is_undone = 1 WHERE action_id = ?",
                    (action_id,),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to mark action '{action_id}' as undone: {e}")
            return False

    def clear_history(self) -> int:
        """Clears audit logs."""
        self._cache.clear()
        if not self._db_ok:
            return 0
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("DELETE FROM action_history")
                conn.commit()
                return cursor.rowcount
        except Exception as e:
            logger.error(f"Failed to clear history: {e}")
            return 0

    # --- Pre-flight Rollback Validation & Execution ---

    def validate_rollback(
        self,
        undo_info: Dict[str, Any],
        policy: Optional[Any] = None,
    ) -> Tuple[bool, str]:
        """
        Validates whether an operation can be safely restored without data corruption,
        conflict, or policy violation.
        Returns (is_safe: bool, reason: str).
        """
        if not undo_info or not isinstance(undo_info, dict):
            return False, "No valid rollback instructions found for this operation."

        action = undo_info.get("action", "")

        # 1. Unreversible operations guard
        if action in ("delete_permanent", "shutdown", "restart", "sleep", "lock"):
            return False, f"Operation '{action}' is irreversible and cannot be undone safely."

        # 2. MOVE rollback validation
        if action == "move":
            cur = undo_info.get("current_path") or undo_info.get("source")
            dest = undo_info.get("original_source") or undo_info.get("destination")
            if not cur or not Path(cur).exists():
                return False, f"Target file to restore does not exist at '{cur}'."
            target_dest = Path(dest)
            if target_dest.is_dir():
                target_dest = target_dest / Path(cur).name
            if target_dest.exists():
                return False, f"Original location '{target_dest}' already exists. Rollback aborted to prevent overwrite."
            if policy:
                is_prot, reason = policy.is_protected_path(target_dest)
                if is_prot:
                    return False, f"Cannot restore to protected location: {reason}"
            return True, None

        # 3. RENAME rollback validation
        elif action == "rename":
            cur = undo_info.get("current_path") or undo_info.get("new_path")
            old = undo_info.get("old_path")
            if not cur or not Path(cur).exists():
                return False, f"Item to rename does not exist at '{cur}'."
            old_path = Path(old)
            if old_path.exists():
                return False, f"Original name '{old_path.name}' already exists in the directory."
            return True, None

        # 4. CREATE rollback validation (deletes the newly created empty file/folder)
        elif action in ("delete", "delete_created"):
            target_p = undo_info.get("path")
            if not target_p or not Path(target_p).exists():
                return False, f"Created item does not exist at '{target_p}'."
            p = Path(target_p)
            if policy:
                is_prot, reason = policy.is_protected_path(p)
                if is_prot:
                    return False, f"Cannot rollback protected path: {reason}"
            # If folder, ensure it does not contain unexpected user data created later
            if p.is_dir():
                sub_count = len(list(p.iterdir()))
                if sub_count > 0:
                    return False, f"Folder '{p.name}' is no longer empty ({sub_count} items inside). Manual deletion required."
            return True, None

        # 5. COPY rollback validation (removes destination replica)
        elif action == "remove_copy":
            dest_replica = undo_info.get("destination_path") or undo_info.get("path")
            if not dest_replica or not Path(dest_replica).exists():
                return False, f"Copied item does not exist at '{dest_replica}'."
            return True, None

        return False, f"Unknown rollback action '{action}'."

    def execute_rollback(
        self,
        action_record: Dict[str, Any],
        file_manager: Any,
        policy: Optional[Any] = None,
    ) -> ToolResult:
        """
        Executes a validated rollback and marks the action record as undone.
        """
        undo_info = action_record.get("undo_info")
        if not undo_info:
            return ToolResult.fail(
                error=f"No undo information available for action {action_record.get('action_id') or action_record.get('id')}.",
            )

        is_safe, reason = self.validate_rollback(undo_info, policy=policy)
        if not is_safe:
            return ToolResult.fail(
                error=f"Rollback rejected: {reason}",
                message=f"Cannot undo operation: {reason}",
                data={"action_id": action_record.get("action_id") or action_record.get("id"), "reason": reason},
            )

        action = undo_info.get("action")
        act_id = action_record.get("action_id") or action_record.get("id")
        try:
            if action == "move":
                cur_str = undo_info.get("current_path") or undo_info.get("source")
                orig_str = undo_info.get("original_source") or undo_info.get("destination")
                cur_path = Path(cur_str)
                orig_source = Path(orig_str)
                if orig_source.is_dir():
                    orig_source = orig_source / cur_path.name
                import shutil
                shutil.move(str(cur_path), str(orig_source))
                if hasattr(file_manager, "indexer") and file_manager.indexer:
                    try:
                        file_manager.indexer.update_path(cur_path, orig_source)
                    except Exception:
                        pass
                self.mark_as_undone(act_id)
                return ToolResult.ok(
                    message=f"Successfully restored '{cur_path.name}' back to '{orig_source.parent.name}'.",
                    data={"restored_path": str(orig_source), "action_id": act_id},
                )

            elif action == "rename":
                cur_str = undo_info.get("current_path") or undo_info.get("new_path")
                old_str = undo_info.get("old_path")
                cur_path = Path(cur_str)
                old_path = Path(old_str)
                cur_path.rename(old_path)
                if hasattr(file_manager, "indexer") and file_manager.indexer:
                    try:
                        file_manager.indexer.update_path(cur_path, old_path)
                    except Exception:
                        pass
                self.mark_as_undone(act_id)
                return ToolResult.ok(
                    message=f"Successfully restored name to '{old_path.name}'.",
                    data={"restored_path": str(old_path), "action_id": act_id},
                )

            elif action in ("delete", "delete_created", "remove_copy"):
                target = Path(undo_info.get("path") or undo_info.get("destination_path") or undo_info.get("source"))
                import shutil
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                elif target.is_file():
                    target.unlink(missing_ok=True)
                if hasattr(file_manager, "indexer") and file_manager.indexer:
                    try:
                        file_manager.indexer.remove_item(target)
                    except Exception:
                        pass
                self.mark_as_undone(act_id)
                return ToolResult.ok(
                    message=f"Successfully rolled back creation of '{target.name}'.",
                    data={"removed_path": str(target), "action_id": action_record["action_id"]},
                )

            return ToolResult.fail(error=f"Unsupported rollback action '{action}'.")

        except Exception as e:
            return ToolResult.fail(
                error=f"Rollback execution failed: {str(e)}",
                data={"action_id": action_record.get("action_id")},
            )
