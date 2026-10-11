"""
Nova Reminders & Task Tracking
Provides persistent scheduling, status tracking, recurrence handling,
and non-blocking background alerting for reminders and tasks.
"""

import re
import time
import json
import sqlite3
import logging
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union, Callable, Tuple
from contextlib import contextmanager

from nova.config import REMINDERS_DB_PATH
from nova.core.results import ToolResult

logger = logging.getLogger("nova.tools.reminders")


class ReminderManager:
    """
    Manages reminders, due dates, completion states, and background checks.
    """

    VALID_RECURRENCES = {"daily", "weekly", "hourly", "workdays"}

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        auto_start: bool = False,
        notification_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.db_path = Path(db_path) if db_path else REMINDERS_DB_PATH
        self.notification_callback = notification_callback
        self._checker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._init_db()

        if auto_start:
            self.start_background_checker()

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
        """Initializes database schema and indices."""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS reminders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        message TEXT NOT NULL,
                        due_time REAL NOT NULL,
                        due_time_iso TEXT NOT NULL,
                        recurrence TEXT,
                        status TEXT NOT NULL DEFAULT 'pending',
                        created_at REAL NOT NULL,
                        notified_at REAL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_status_due ON reminders(status, due_time);")
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to initialize reminders DB at {self.db_path}: {e}")

    # --- Date & Time Parsing Engine ---

    def parse_due_time(self, time_expr: Union[str, float, int, datetime], now: Optional[datetime] = None) -> Tuple[Optional[float], Optional[str]]:
        """
        Parses a relative or absolute natural language time expression into a unix timestamp.
        Returns (timestamp, error_message).
        """
        ref_now = now or datetime.now()

        # Direct timestamp or datetime
        if isinstance(time_expr, (int, float)):
            val = float(time_expr)
            if val <= 0:
                return None, "Timestamp must be a positive number."
            return val, None

        if isinstance(time_expr, datetime):
            return time_expr.timestamp(), None

        raw = str(time_expr).strip().lower()
        if not raw:
            return None, "Time expression cannot be empty."

        # 1. Relative duration: "in 10 minutes", "in 2 hours", "in 30 seconds"
        rel_match = re.search(
            r"in\s+(?:(\d+)\s*(?:d|day|days))?\s*(?:(\d+)\s*(?:h|hr|hrs|hour|hours))?\s*(?:(\d+)\s*(?:m|min|mins|minute|minutes))?\s*(?:(\d+)\s*(?:s|sec|secs|second|seconds))?",
            raw,
        )
        if rel_match and any(rel_match.groups()):
            days = int(rel_match.group(1) or 0)
            hours = int(rel_match.group(2) or 0)
            minutes = int(rel_match.group(3) or 0)
            seconds = int(rel_match.group(4) or 0)
            if days == 0 and hours == 0 and minutes == 0 and seconds == 0:
                return None, "Relative duration cannot be zero."
            target = ref_now + timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
            return target.timestamp(), None

        # 2. ISO or standard format: "2026-10-12 20:00", "2026-10-12T20:00:00"
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(raw, fmt)
                if fmt == "%Y-%m-%d":
                    # default to 09:00 AM if date only
                    dt = dt.replace(hour=9, minute=0, second=0)
                return dt.timestamp(), None
            except ValueError:
                pass

        # 3. Relative day markers: "today at ...", "tonight at ...", "tomorrow at ..."
        day_offset = 0
        if "tomorrow" in raw:
            day_offset = 1
            raw = raw.replace("tomorrow", "").strip()
        elif "today" in raw or "tonight" in raw:
            day_offset = 0
            raw = raw.replace("tonight", "").replace("today", "").strip()

        # Remove "at " or "around "
        raw = re.sub(r"^(?:at|around|by)\s+", "", raw).strip()

        # 4. Time format: "8 pm", "8:30 am", "20:00", "8pm", "8:00"
        time_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", raw)
        if time_match:
            try:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2) or 0)
                meridiem = time_match.group(3)

                if minute < 0 or minute > 59:
                    return None, f"Invalid minute '{minute}'. Minutes must be between 0 and 59."

                if meridiem:
                    if hour < 1 or hour > 12:
                        return None, f"Invalid 12-hour hour '{hour}'. Must be between 1 and 12."
                    if meridiem == "pm" and hour < 12:
                        hour += 12
                    elif meridiem == "am" and hour == 12:
                        hour = 0
                else:
                    if hour < 0 or hour > 23:
                        return None, f"Invalid 24-hour hour '{hour}'. Must be between 0 and 23."

                target_date = (ref_now + timedelta(days=day_offset)).replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )

                # If time was e.g. "at 8 PM" without "tomorrow" and it's already past 8 PM today, roll to tomorrow
                if day_offset == 0 and target_date < ref_now:
                    target_date += timedelta(days=1)

                return target_date.timestamp(), None
            except Exception as e:
                return None, f"Invalid time specified: {e}"

        return None, f"Could not parse due date/time from '{time_expr}'. Use formats like 'at 8 PM', 'in 15 minutes', or 'tomorrow at 9 AM'."

    # --- CRUD Operations ---

    def add_reminder(
        self,
        message: str,
        due_time: Union[str, float, int, datetime],
        recurrence: Optional[str] = None,
        allow_duplicate: bool = False,
    ) -> ToolResult:
        """
        Creates a new reminder with safety validation and duplicate detection.
        """
        clean_msg = str(message).strip()
        if not clean_msg:
            return ToolResult.fail(
                error="Reminder message cannot be empty.",
                message="Cannot set a reminder without a message.",
            )

        ts, err = self.parse_due_time(due_time)
        if err or ts is None:
            return ToolResult.fail(
                error=err or "Invalid due time.",
                message=f"Date parsing error: {err}",
            )

        clean_rec = recurrence.strip().lower() if recurrence else None
        if clean_rec and clean_rec not in self.VALID_RECURRENCES:
            return ToolResult.fail(
                error=f"Unsupported recurrence '{recurrence}'. Choose from: {', '.join(sorted(self.VALID_RECURRENCES))}.",
                message=f"Invalid recurrence schedule '{recurrence}'.",
            )

        due_dt = datetime.fromtimestamp(ts)
        due_iso = due_dt.strftime("%Y-%m-%d %H:%M:%S")

        # Duplicate detection: check if active reminder with same message & close due time exists
        if not allow_duplicate:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        SELECT id, due_time_iso FROM reminders
                        WHERE status = 'pending'
                          AND LOWER(message) = LOWER(?)
                          AND ABS(due_time - ?) < 60
                        """,
                        (clean_msg, ts),
                    )
                    existing = cursor.fetchone()
                    if existing:
                        return ToolResult.fail(
                            error=f"Duplicate reminder: A pending reminder for '{clean_msg}' due at {existing['due_time_iso']} already exists (ID #{existing['id']}).",
                            message=f"Duplicate reminder detected. You already have a reminder for '{clean_msg}' set for {existing['due_time_iso']}.",
                            data={"existing_id": existing["id"]},
                        )
            except Exception as e:
                logger.error(f"Error checking duplicate reminders: {e}")

        now = time.time()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO reminders (message, due_time, due_time_iso, recurrence, status, created_at)
                    VALUES (?, ?, ?, ?, 'pending', ?)
                    """,
                    (clean_msg, ts, due_iso, clean_rec, now),
                )
                rem_id = cursor.lastrowid
                conn.commit()

            rec_desc = f" ({clean_rec})" if clean_rec else ""
            rem_data = {
                "id": rem_id,
                "message": clean_msg,
                "due_time": ts,
                "due_time_iso": due_iso,
                "recurrence": clean_rec,
                "status": "pending",
                "created_at": now,
            }

            return ToolResult.ok(
                message=f"Reminder #{rem_id} set for {due_iso}{rec_desc}: '{clean_msg}'.",
                data=rem_data,
                undo_info={"action": "dismiss_reminder", "id": rem_id},
                reminder=rem_data,
            )
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Failed to create reminder: {e}")

    def list_reminders(
        self,
        status: Optional[str] = "pending",
        include_completed: bool = False,
    ) -> ToolResult:
        """Lists stored reminders filtered by status."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if include_completed or status is None:
                    cursor.execute("SELECT * FROM reminders ORDER BY due_time ASC")
                else:
                    cursor.execute("SELECT * FROM reminders WHERE status = ? ORDER BY due_time ASC", (status,))
                rows = cursor.fetchall()

            reminders = []
            for r in rows:
                reminders.append({
                    "id": r["id"],
                    "message": r["message"],
                    "due_time": r["due_time"],
                    "due_time_iso": r["due_time_iso"],
                    "recurrence": r["recurrence"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "notified_at": r["notified_at"],
                })

            if not reminders:
                desc = f" with status '{status}'" if status else ""
                return ToolResult.ok(
                    message=f"No reminders found{desc}.",
                    data={"reminders": [], "count": 0},
                    reminders=[],
                    count=0,
                )

            lines = [f"Found {len(reminders)} reminder(s):"]
            for r in reminders:
                rec_str = f" [{r['recurrence']}]" if r['recurrence'] else ""
                status_icon = "⏳" if r['status'] == "pending" else ("✅" if r['status'] == "completed" else "🔔")
                lines.append(f" {status_icon} #{r['id']} ({r['due_time_iso']}){rec_str}: {r['message']} [{r['status']}]")

            return ToolResult.ok(
                message="\n".join(lines),
                data={"reminders": reminders, "count": len(reminders)},
                reminders=reminders,
                count=len(reminders),
            )
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Failed to list reminders: {e}")

    def complete_reminder(self, reminder_id: Union[int, str]) -> ToolResult:
        """Marks a reminder as completed."""
        try:
            r_id = int(reminder_id)
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM reminders WHERE id = ?", (r_id,))
                row = cursor.fetchone()
                if not row:
                    return ToolResult.fail(
                        error=f"Reminder #{reminder_id} not found.",
                        message=f"Could not find reminder #{reminder_id}.",
                    )

                cursor.execute("UPDATE reminders SET status = 'completed' WHERE id = ?", (r_id,))
                conn.commit()

            return ToolResult.ok(
                message=f"Marked reminder #{r_id} as completed: '{row['message']}'.",
                data={"id": r_id, "status": "completed"},
            )
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Failed to complete reminder: {e}")

    def dismiss_reminder(self, reminder_id: Union[int, str]) -> ToolResult:
        """Dismisses an active or triggered reminder."""
        try:
            r_id = int(reminder_id)
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM reminders WHERE id = ?", (r_id,))
                row = cursor.fetchone()
                if not row:
                    return ToolResult.fail(
                        error=f"Reminder #{reminder_id} not found.",
                        message=f"Could not find reminder #{reminder_id}.",
                    )

                cursor.execute("UPDATE reminders SET status = 'dismissed' WHERE id = ?", (r_id,))
                conn.commit()

            return ToolResult.ok(
                message=f"Dismissed reminder #{r_id}: '{row['message']}'.",
                data={"id": r_id, "status": "dismissed"},
            )
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Failed to dismiss reminder: {e}")

    def delete_reminder(self, reminder_id: Union[int, str]) -> ToolResult:
        """Deletes a reminder completely from database."""
        try:
            r_id = int(reminder_id)
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM reminders WHERE id = ?", (r_id,))
                row = cursor.fetchone()
                if not row:
                    return ToolResult.fail(
                        error=f"Reminder #{reminder_id} not found.",
                        message=f"Could not find reminder #{reminder_id}.",
                    )

                cursor.execute("DELETE FROM reminders WHERE id = ?", (r_id,))
                conn.commit()

            return ToolResult.ok(
                message=f"Deleted reminder #{r_id}: '{row['message']}'.",
                data={"id": r_id, "deleted": True},
            )
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Failed to delete reminder: {e}")

    def clear_completed(self) -> ToolResult:
        """Cleans up completed and dismissed reminders."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM reminders WHERE status IN ('completed', 'dismissed')")
                count = cursor.rowcount
                conn.commit()
            return ToolResult.ok(
                message=f"Removed {count} finished reminder(s).",
                data={"cleared_count": count},
            )
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Failed to clear completed reminders: {e}")

    # --- Background Evaluation & Alerting Engine ---

    def check_due_reminders(self) -> List[Dict[str, Any]]:
        """
        Finds pending reminders whose due_time <= now, marks them triggered,
        and reschedules if recurring.
        """
        now = time.time()
        triggered = []

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM reminders
                    WHERE status = 'pending' AND due_time <= ?
                    ORDER BY due_time ASC
                    """,
                    (now,),
                )
                rows = cursor.fetchall()

                for r in rows:
                    rem_id = r["id"]
                    msg = r["message"]
                    rec = r["recurrence"]
                    due_t = r["due_time"]

                    triggered.append({
                        "id": rem_id,
                        "message": msg,
                        "due_time": due_t,
                        "due_time_iso": r["due_time_iso"],
                        "recurrence": rec,
                    })

                    if rec:
                        # Reschedule next recurrence
                        next_ts = self._compute_next_recurrence(due_t, rec)
                        next_iso = datetime.fromtimestamp(next_ts).strftime("%Y-%m-%d %H:%M:%S")
                        cursor.execute(
                            """
                            UPDATE reminders
                            SET due_time = ?, due_time_iso = ?, notified_at = ?
                            WHERE id = ?
                            """,
                            (next_ts, next_iso, now, rem_id),
                        )
                    else:
                        cursor.execute(
                            """
                            UPDATE reminders
                            SET status = 'triggered', notified_at = ?
                            WHERE id = ?
                            """,
                            (now, rem_id),
                        )
                conn.commit()
        except Exception as e:
            logger.error(f"Error checking due reminders: {e}")

        return triggered

    def _compute_next_recurrence(self, last_due: float, recurrence: str) -> float:
        """Computes the next timestamp for recurring tasks."""
        dt = datetime.fromtimestamp(last_due)
        now_dt = datetime.now()

        while dt <= now_dt:
            if recurrence == "hourly":
                dt += timedelta(hours=1)
            elif recurrence == "daily":
                dt += timedelta(days=1)
            elif recurrence == "weekly":
                dt += timedelta(weeks=1)
            elif recurrence == "workdays":
                dt += timedelta(days=1)
                while dt.weekday() >= 5:  # Saturday or Sunday
                    dt += timedelta(days=1)
            else:
                dt += timedelta(days=1)
                break
        return dt.timestamp()

    def start_background_checker(self, interval_seconds: float = 2.0) -> None:
        """Starts a background daemon thread that periodically checks for due reminders."""
        if self._checker_thread and self._checker_thread.is_alive():
            return

        self._stop_event.clear()

        def _loop():
            logger.info("Reminder background monitor started.")
            while not self._stop_event.is_set():
                due_list = self.check_due_reminders()
                for due_rem in due_list:
                    logger.info(f"REMINDER ALERT: #{due_rem['id']} - {due_rem['message']}")
                    if self.notification_callback:
                        try:
                            self.notification_callback(due_rem)
                        except Exception as e:
                            logger.error(f"Error invoking reminder callback: {e}")
                self._stop_event.wait(interval_seconds)

        self._checker_thread = threading.Thread(target=_loop, daemon=True, name="NovaReminderMonitor")
        self._checker_thread.start()

    def stop_background_checker(self) -> None:
        """Stops the background reminder checker."""
        self._stop_event.set()
        if self._checker_thread and self._checker_thread.is_alive():
            self._checker_thread.join(timeout=1.0)
            self._checker_thread = None
