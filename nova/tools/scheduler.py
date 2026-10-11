"""
Nova Task Scheduler & Automation
Executes approved, validated NOVA actions on scheduled intervals or specified times.
Provides persistent SQLite storage, crash/restart recovery, and strict policy gating
preventing arbitrary command execution.
"""

import time
import json
import sqlite3
import logging
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union, Callable
from contextlib import contextmanager

from nova.config import SCHEDULES_DB_PATH
from nova.core.results import ToolResult
from nova.agent.intent_parser import NovaIntent

logger = logging.getLogger("nova.tools.scheduler")


class TaskScheduler:
    """
    Schedules registered, policy-validated Nova actions.
    Ensures safe persistence across restarts and non-blocking background dispatch.
    """

    # Strict whitelist of intents allowed for scheduled automation
    ALLOWED_SCHEDULE_INTENTS = {
        NovaIntent.OPEN_PROJECT,
        NovaIntent.OPEN_APP,
        NovaIntent.OPEN_ITEM,
        NovaIntent.SUMMARIZE,
        NovaIntent.BATTERY_STATUS,
        NovaIntent.CREATE_FILE,
        NovaIntent.CREATE_FOLDER,
        "SYSTEM_DIAGNOSTICS",
    }

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        executor: Optional[Any] = None,
        action_history: Optional[Any] = None,
        auto_start: bool = False,
    ):
        self.db_path = Path(db_path) if db_path else SCHEDULES_DB_PATH
        self.executor = executor
        self.action_history = action_history
        self._loop_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._init_db()

        if auto_start:
            self.start()

    @contextmanager
    def _get_connection(self):
        """Yields an SQLite connection with WAL mode and row factory."""
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
        """Initializes tables for persistent task schedules."""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS schedules (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        action_intent TEXT NOT NULL,
                        action_params TEXT NOT NULL,
                        schedule_type TEXT NOT NULL,
                        time_of_day TEXT,
                        interval_seconds REAL,
                        target_time REAL NOT NULL,
                        target_time_iso TEXT NOT NULL,
                        is_active INTEGER NOT NULL DEFAULT 1,
                        last_run REAL,
                        last_status TEXT,
                        created_at REAL NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sched_active ON schedules(is_active, target_time);")
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to initialize scheduler database at {self.db_path}: {e}")

    # --- Time & Target Calculation ---

    def calculate_next_run(
        self,
        schedule_type: str,
        time_of_day: Optional[str] = None,
        interval_seconds: Optional[float] = None,
        target_time: Optional[float] = None,
        now: Optional[datetime] = None,
    # pyrefly: ignore [unknown-name]
    ) -> Tuple_float_iso:
        """
        Calculates the next execution timestamp and its ISO string.
        """
        ref_now = now or datetime.now()

        if schedule_type == "once":
            if target_time:
                dt = datetime.fromtimestamp(target_time)
                return target_time, dt.strftime("%Y-%m-%d %H:%M:%S")
            raise ValueError("Target time must be supplied for one-off schedules.")

        elif schedule_type == "interval":
            if not interval_seconds or interval_seconds <= 0:
                raise ValueError("interval_seconds must be greater than zero.")
            next_dt = ref_now + timedelta(seconds=interval_seconds)
            return next_dt.timestamp(), next_dt.strftime("%Y-%m-%d %H:%M:%S")

        elif schedule_type == "daily_at":
            if not time_of_day:
                raise ValueError("time_of_day (HH:MM) is required for daily schedules.")
            parts = time_of_day.split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0

            next_dt = ref_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_dt <= ref_now:
                next_dt += timedelta(days=1)
            return next_dt.timestamp(), next_dt.strftime("%Y-%m-%d %H:%M:%S")

        else:
            raise ValueError(f"Unknown schedule type '{schedule_type}'.")

    # --- Schedule Management ---

    def schedule_task(
        self,
        name: str,
        intent: str,
        parameters: Dict[str, Any],
        schedule_type: str = "daily_at",
        time_of_day: Optional[str] = None,
        interval_seconds: Optional[float] = None,
        target_time: Optional[float] = None,
    ) -> ToolResult:
        """
        Registers a new scheduled task after policy verification.
        """
        clean_name = str(name).strip()
        clean_intent = str(intent).strip().upper()

        # Security check: verify against registered whitelist
        if clean_intent not in self.ALLOWED_SCHEDULE_INTENTS:
            allowed_list = ", ".join(sorted(self.ALLOWED_SCHEDULE_INTENTS))
            return ToolResult.fail(
                error=f"Unapproved intent '{intent}'. Scheduled automation only permits validated actions: {allowed_list}.",
                message=f"Action '{intent}' is not permitted for scheduled execution.",
            )

        try:
            next_ts, next_iso = self.calculate_next_run(
                schedule_type=schedule_type,
                time_of_day=time_of_day,
                interval_seconds=interval_seconds,
                target_time=target_time,
            )
        except Exception as e:
            return ToolResult.fail(
                error=f"Schedule timing error: {e}",
                message=f"Invalid schedule parameters: {e}",
            )

        now = time.time()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO schedules (
                        name, action_intent, action_params, schedule_type,
                        time_of_day, interval_seconds, target_time, target_time_iso,
                        is_active, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        clean_name,
                        clean_intent,
                        json.dumps(parameters or {}),
                        schedule_type,
                        time_of_day,
                        interval_seconds,
                        next_ts,
                        next_iso,
                        now,
                    ),
                )
                sched_id = cursor.lastrowid
                conn.commit()

            sched_data = {
                "id": sched_id,
                "name": clean_name,
                "intent": clean_intent,
                "parameters": parameters,
                "schedule_type": schedule_type,
                "next_run": next_iso,
                "target_time": next_ts,
            }

            return ToolResult.ok(
                message=f"Task #{sched_id} '{clean_name}' scheduled for {next_iso} ({schedule_type}).",
                data=sched_data,
                schedule=sched_data,
            )
        except Exception as e:
            logger.error(f"Failed to create schedule: {e}")
            return ToolResult.fail(error=str(e), message=f"Failed to schedule task: {e}")

    def list_schedules(self, active_only: bool = False) -> ToolResult:
        """Lists persistent schedules."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if active_only:
                    cursor.execute("SELECT * FROM schedules WHERE is_active = 1 ORDER BY target_time ASC")
                else:
                    cursor.execute("SELECT * FROM schedules ORDER BY is_active DESC, target_time ASC")
                rows = cursor.fetchall()

            tasks = []
            for r in rows:
                tasks.append({
                    "id": r["id"],
                    "name": r["name"],
                    "intent": r["action_intent"],
                    "params": json.loads(r["action_params"] or "{}"),
                    "schedule_type": r["schedule_type"],
                    "time_of_day": r["time_of_day"],
                    "interval_seconds": r["interval_seconds"],
                    "next_run": r["target_time_iso"],
                    "target_time": r["target_time"],
                    "is_active": bool(r["is_active"]),
                    "last_run": r["last_run"],
                    "last_status": r["last_status"],
                })

            if not tasks:
                return ToolResult.ok(
                    message="No scheduled tasks found.",
                    data={"schedules": [], "count": 0},
                    schedules=[],
                    count=0,
                )

            lines = [f"Found {len(tasks)} scheduled task(s):"]
            for t in tasks:
                status_icon = "🟢" if t["is_active"] else "⚪"
                last_str = f" [Last: {t['last_status']}]" if t['last_status'] else ""
                lines.append(f" {status_icon} #{t['id']} '{t['name']}' -> {t['intent']} (Next: {t['next_run']}){last_str}")

            return ToolResult.ok(
                message="\n".join(lines),
                data={"schedules": tasks, "count": len(tasks)},
                schedules=tasks,
                count=len(tasks),
            )
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Failed to list schedules: {e}")

    def cancel_schedule(self, schedule_id: Union[int, str]) -> ToolResult:
        """Cancels and deletes a scheduled task."""
        try:
            s_id = int(schedule_id)
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM schedules WHERE id = ?", (s_id,))
                row = cursor.fetchone()
                if not row:
                    return ToolResult.fail(
                        error=f"Schedule #{schedule_id} not found.",
                        message=f"Could not find scheduled task #{schedule_id}.",
                    )
                name = row["name"]
                cursor.execute("DELETE FROM schedules WHERE id = ?", (s_id,))
                conn.commit()

            return ToolResult.ok(
                message=f"Canceled and removed scheduled task #{s_id}: '{name}'.",
                data={"id": s_id, "canceled": True},
            )
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Failed to cancel schedule: {e}")

    def pause_schedule(self, schedule_id: Union[int, str]) -> ToolResult:
        """Pauses an active schedule without deleting it."""
        try:
            s_id = int(schedule_id)
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE schedules SET is_active = 0 WHERE id = ?", (s_id,))
                if cursor.rowcount == 0:
                    return ToolResult.fail(error=f"Schedule #{s_id} not found.")
                conn.commit()
            return ToolResult.ok(message=f"Paused schedule #{s_id}.", data={"id": s_id, "is_active": False})
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Failed to pause schedule: {e}")

    def resume_schedule(self, schedule_id: Union[int, str]) -> ToolResult:
        """Resumes a paused schedule and recalculates its next execution time."""
        try:
            s_id = int(schedule_id)
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM schedules WHERE id = ?", (s_id,))
                row = cursor.fetchone()
                if not row:
                    return ToolResult.fail(error=f"Schedule #{s_id} not found.")

                next_ts, next_iso = self.calculate_next_run(
                    schedule_type=row["schedule_type"],
                    time_of_day=row["time_of_day"],
                    interval_seconds=row["interval_seconds"],
                )
                cursor.execute(
                    "UPDATE schedules SET is_active = 1, target_time = ?, target_time_iso = ? WHERE id = ?",
                    (next_ts, next_iso, s_id),
                )
                conn.commit()

            return ToolResult.ok(
                message=f"Resumed schedule #{s_id}. Next run: {next_iso}.",
                data={"id": s_id, "is_active": True, "next_run": next_iso},
            )
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Failed to resume schedule: {e}")

    # --- Restart Recovery & Execution Loop ---

    def recover_on_startup(self) -> List[Dict[str, Any]]:
        """
        Scans persistent schedules on startup.
        Identifies active tasks whose execution time elapsed while NOVA was offline.
        Recalculates their next occurrence and marks them recovered.
        """
        now = time.time()
        recovered = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM schedules WHERE is_active = 1 AND target_time <= ?", (now,))
                rows = cursor.fetchall()

                for r in rows:
                    s_id = r["id"]
                    s_type = r["schedule_type"]
                    name = r["name"]

                    if s_type == "once":
                        cursor.execute("UPDATE schedules SET is_active = 0, last_status = 'Missed during downtime' WHERE id = ?", (s_id,))
                        recovered.append({"id": s_id, "name": name, "status": "missed_once"})
                    else:
                        next_ts, next_iso = self.calculate_next_run(
                            schedule_type=s_type,
                            time_of_day=r["time_of_day"],
                            interval_seconds=r["interval_seconds"],
                        )
                        cursor.execute(
                            "UPDATE schedules SET target_time = ?, target_time_iso = ?, last_status = 'Recovered on startup' WHERE id = ?",
                            (next_ts, next_iso, s_id),
                        )
                        recovered.append({"id": s_id, "name": name, "status": "rescheduled", "next_run": next_iso})
                conn.commit()
            if recovered:
                logger.info(f"Recovered {len(recovered)} schedule(s) from previous session.")
        except Exception as e:
            logger.error(f"Error during scheduler startup recovery: {e}")
        return recovered

    def check_and_execute_due_tasks(self) -> List[Dict[str, Any]]:
        """
        Checks for tasks whose target_time <= now, executes them safely,
        and reschedules next iteration.
        """
        now = time.time()
        executed_records = []

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM schedules WHERE is_active = 1 AND target_time <= ?", (now,))
                rows = cursor.fetchall()

                for r in rows:
                    s_id = r["id"]
                    name = r["name"]
                    intent = r["action_intent"]
                    params = json.loads(r["action_params"] or "{}")
                    s_type = r["schedule_type"]

                    # Execute the task
                    status_text = self._execute_single_task(name, intent, params)

                    # Update or reschedule
                    if s_type == "once":
                        cursor.execute(
                            "UPDATE schedules SET is_active = 0, last_run = ?, last_status = ? WHERE id = ?",
                            (now, status_text, s_id),
                        )
                    else:
                        next_ts, next_iso = self.calculate_next_run(
                            schedule_type=s_type,
                            time_of_day=r["time_of_day"],
                            interval_seconds=r["interval_seconds"],
                        )
                        cursor.execute(
                            "UPDATE schedules SET target_time = ?, target_time_iso = ?, last_run = ?, last_status = ? WHERE id = ?",
                            (next_ts, next_iso, now, status_text, s_id),
                        )

                    executed_records.append({
                        "id": s_id,
                        "name": name,
                        "intent": intent,
                        "status": status_text,
                    })

                conn.commit()
        except Exception as e:
            logger.error(f"Error executing scheduled tasks: {e}")

        return executed_records

    def _execute_single_task(self, name: str, intent: str, params: Dict[str, Any]) -> str:
        """
        Safely dispatches an approved action through executor or policy without crashing.
        """
        logger.info(f"Executing scheduled task '{name}' (Intent: {intent})")
        if not self.executor:
            return "No executor attached"

        try:
            from nova.agent.planner import PlanStep, ExecutionPlan
            step = PlanStep(
                step_id=1,
                intent=intent,
                action=intent.lower(),
                parameters=params,
                description=f"Scheduled execution of '{name}'",
            )
            plan = ExecutionPlan(
                raw_utterance=f"Scheduled task: {name}",
                intent=intent,
                steps=[step],
            )
            res = self.executor.execute_plan(plan)
            status_text = "Success" if res.success else f"Failed: {res.error}"
            logger.info(f"Scheduled task '{name}' completed with status: {status_text}")
            return status_text
        except Exception as e:
            logger.error(f"Error running scheduled task '{name}': {e}")
            return f"Error: {e}"

    def start(self, interval_seconds: float = 2.0) -> None:
        """Starts background monitoring loop."""
        if self._loop_thread and self._loop_thread.is_alive():
            return

        self.recover_on_startup()
        self._stop_event.clear()

        def _worker():
            logger.info("TaskScheduler background service started.")
            while not self._stop_event.is_set():
                self.check_and_execute_due_tasks()
                self._stop_event.wait(interval_seconds)

        self._loop_thread = threading.Thread(target=_worker, daemon=True, name="NovaTaskScheduler")
        self._loop_thread.start()

    def stop(self) -> None:
        """Stops background scheduler service."""
        self._stop_event.set()
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=1.0)
            self._loop_thread = None
