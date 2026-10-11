"""
Nova Quick Notes & Personal Scratchpad
Provides persistent note creation, retrieval, search, update, and deletion using SQLite.
Supports tagged notes, title auto-generation, full-text search, and undo restoration.
"""

import time
import json
import sqlite3
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from contextlib import contextmanager

from nova.config import NOTES_DB_PATH
from nova.core.results import ToolResult

logger = logging.getLogger("nova.tools.notes")


class NotesManager:
    """
    Manages persistent user notes and quick scratchpad entries across Nova sessions.
    """

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        self.db_path = Path(db_path) if db_path else NOTES_DB_PATH
        self._init_db()

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
        """Initializes table schema and search indices."""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS notes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        tags TEXT DEFAULT '[]',
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created_at DESC);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at DESC);")
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to initialize notes database at {self.db_path}: {e}")

    def _derive_title(self, content: str, title: Optional[str] = None) -> str:
        """Derives a concise title if none is explicitly provided."""
        if title and title.strip():
            return title.strip()
        first_line = content.strip().split("\n", 1)[0].strip()
        words = first_line.split()
        if len(words) <= 7:
            derived = first_line
        else:
            derived = " ".join(words[:7]) + "..."
        return derived[:60] if derived else "Quick Note"

    def _normalize_tags(self, tags: Optional[Union[List[str], str]]) -> List[str]:
        """Normalizes tags into a clean list of lowercase strings."""
        if not tags:
            return []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        return sorted(list({t.strip().lower() for t in tags if t and t.strip()}))

    def add_note(
        self,
        content: str,
        title: Optional[str] = None,
        tags: Optional[Union[List[str], str]] = None,
    ) -> ToolResult:
        """
        Saves a new note to the SQLite database.
        """
        clean_content = str(content).strip()
        if not clean_content:
            return ToolResult.fail(
                error="Cannot create an empty note.",
                message="Note content cannot be empty.",
            )

        final_title = self._derive_title(clean_content, title)
        tag_list = self._normalize_tags(tags)
        now = time.time()

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO notes (title, content, tags, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (final_title, clean_content, json.dumps(tag_list), now, now),
                )
                note_id = cursor.lastrowid
                conn.commit()

            note_data = {
                "id": note_id,
                "title": final_title,
                "content": clean_content,
                "tags": tag_list,
                "created_at": now,
                "updated_at": now,
            }

            undo_info = {
                "action": "delete_note",
                "note_id": note_id,
            }

            return ToolResult.ok(
                message=f"Saved note #{note_id}: '{final_title}'.",
                data=note_data,
                undo_info=undo_info,
                note=note_data,
            )
        except Exception as e:
            logger.error(f"Error adding note: {e}")
            return ToolResult.fail(
                error=str(e),
                message=f"Failed to save note: {e}",
            )

    def get_note(self, note_id: Union[int, str]) -> ToolResult:
        """Retrieves a single note by its integer ID or exact title."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if str(note_id).isdigit():
                    cursor.execute("SELECT * FROM notes WHERE id = ?", (int(note_id),))
                else:
                    cursor.execute("SELECT * FROM notes WHERE LOWER(title) = LOWER(?)", (str(note_id).strip(),))
                row = cursor.fetchone()

            if not row:
                return ToolResult.fail(
                    error=f"Note '{note_id}' not found.",
                    message=f"Could not find a note matching '{note_id}'.",
                )

            note_data = {
                "id": row["id"],
                "title": row["title"],
                "content": row["content"],
                "tags": json.loads(row["tags"] or "[]"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            return ToolResult.ok(
                message=f"Note #{row['id']}: {row['title']}\n{row['content']}",
                data=note_data,
                note=note_data,
            )
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Failed to retrieve note: {e}")

    def list_notes(self, limit: int = 20, tag: Optional[str] = None) -> ToolResult:
        """Lists recently saved notes, optionally filtered by tag."""
        try:
            clean_tag = tag.strip().lower() if tag else None
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM notes ORDER BY updated_at DESC LIMIT ?",
                    (max(1, int(limit) * 3 if clean_tag else int(limit)),),
                )
                rows = cursor.fetchall()

            notes = []
            for r in rows:
                tag_list = json.loads(r["tags"] or "[]")
                if clean_tag and clean_tag not in [t.lower() for t in tag_list]:
                    continue
                notes.append({
                    "id": r["id"],
                    "title": r["title"],
                    "content": r["content"],
                    "tags": tag_list,
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                })
                if len(notes) >= limit:
                    break

            if not notes:
                filt_str = f" with tag '{tag}'" if tag else ""
                return ToolResult.ok(
                    message=f"No notes found{filt_str}.",
                    data={"notes": [], "count": 0},
                    notes=[],
                    count=0,
                )

            lines = [f"Found {len(notes)} note(s):"]
            for n in notes:
                tags_str = f" [{', '.join(n['tags'])}]" if n['tags'] else ""
                preview = n['content'].replace("\n", " ")
                if len(preview) > 50:
                    preview = preview[:50] + "..."
                lines.append(f" • #{n['id']} {n['title']}{tags_str}: {preview}")

            return ToolResult.ok(
                message="\n".join(lines),
                data={"notes": notes, "count": len(notes)},
                notes=notes,
                count=len(notes),
            )
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Failed to list notes: {e}")

    def search_notes(self, query: str) -> ToolResult:
        """Searches notes by keyword in title, content, or tags."""
        clean_q = query.strip()
        if not clean_q:
            return self.list_notes()

        try:
            param = f"%{clean_q}%"
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM notes
                    WHERE title LIKE ? OR content LIKE ? OR tags LIKE ?
                    ORDER BY updated_at DESC
                    LIMIT 50
                    """,
                    (param, param, param),
                )
                rows = cursor.fetchall()

            notes = []
            for r in rows:
                notes.append({
                    "id": r["id"],
                    "title": r["title"],
                    "content": r["content"],
                    "tags": json.loads(r["tags"] or "[]"),
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                })

            if not notes:
                return ToolResult.ok(
                    message=f"No notes found matching '{clean_q}'.",
                    data={"query": clean_q, "notes": [], "count": 0},
                    notes=[],
                    count=0,
                )

            lines = [f"Found {len(notes)} note(s) matching '{clean_q}':"]
            for n in notes:
                lines.append(f" • #{n['id']} {n['title']}: {n['content'][:60]}...")

            return ToolResult.ok(
                message="\n".join(lines),
                data={"query": clean_q, "notes": notes, "count": len(notes)},
                notes=notes,
                count=len(notes),
            )
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Search failed: {e}")

    def update_note(
        self,
        note_id: Union[int, str],
        content: Optional[str] = None,
        title: Optional[str] = None,
        tags: Optional[Union[List[str], str]] = None,
        append: bool = False,
    ) -> ToolResult:
        """Updates or appends content to an existing note."""
        current = self.get_note(note_id)
        if not current.success:
            return current

        curr_note = current.data
        new_content = curr_note["content"]
        if content:
            if append:
                new_content = f"{curr_note['content']}\n{content.strip()}"
            else:
                new_content = content.strip()

        new_title = title.strip() if title else curr_note["title"]
        new_tags = self._normalize_tags(tags) if tags is not None else curr_note["tags"]
        now = time.time()

        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    UPDATE notes
                    SET title = ?, content = ?, tags = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (new_title, new_content, json.dumps(new_tags), now, curr_note["id"]),
                )
                conn.commit()

            updated_data = {
                "id": curr_note["id"],
                "title": new_title,
                "content": new_content,
                "tags": new_tags,
                "created_at": curr_note["created_at"],
                "updated_at": now,
            }
            return ToolResult.ok(
                message=f"Updated note #{curr_note['id']}: '{new_title}'.",
                data=updated_data,
                note=updated_data,
            )
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Failed to update note: {e}")

    def delete_note(self, note_id: Union[int, str]) -> ToolResult:
        """Deletes a note by ID and returns undo information."""
        current = self.get_note(note_id)
        if not current.success:
            return current

        curr_note = current.data
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM notes WHERE id = ?", (curr_note["id"],))
                conn.commit()

            undo_info = {
                "action": "restore_note",
                "id": curr_note["id"],
                "title": curr_note["title"],
                "content": curr_note["content"],
                "tags": curr_note["tags"],
                "created_at": curr_note["created_at"],
            }

            return ToolResult.ok(
                message=f"Deleted note #{curr_note['id']}: '{curr_note['title']}'.",
                data={"deleted_id": curr_note["id"], "title": curr_note["title"]},
                undo_info=undo_info,
            )
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Failed to delete note: {e}")

    def restore_note(self, undo_info: Dict[str, Any]) -> ToolResult:
        """Restores a deleted note from undo metadata."""
        try:
            note_id = undo_info.get("id")
            title = undo_info.get("title", "Restored Note")
            content = undo_info.get("content", "")
            tags = self._normalize_tags(undo_info.get("tags"))
            created_at = undo_info.get("created_at", time.time())
            now = time.time()

            with self._get_connection() as conn:
                if note_id:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO notes (id, title, content, tags, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (note_id, title, content, json.dumps(tags), created_at, now),
                    )
                else:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO notes (title, content, tags, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (title, content, json.dumps(tags), created_at, now),
                    )
                    note_id = cursor.lastrowid
                conn.commit()

            return ToolResult.ok(
                message=f"Restored note #{note_id}: '{title}'.",
                data={"id": note_id, "title": title},
            )
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Failed to restore note: {e}")

    def clear_all(self) -> ToolResult:
        """Wipes all notes."""
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM notes")
                conn.commit()
            return ToolResult.ok(message="Cleared all saved notes.", data={"cleared": True})
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Failed to clear notes: {e}")
