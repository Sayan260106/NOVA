"""
Nova Persistent Memory Module
Provides persistent storage using SQLite for user preferences, configured project locations,
application aliases, and common directories across sessions.
"""

import os
import time
import sqlite3
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from contextlib import contextmanager

from nova.config import MEMORY_DB_PATH

logger = logging.getLogger("nova.memory")


class PersistentMemory:
    """
    Manages long-term user-approved configuration, custom aliases,
    and project/folder paths across Nova restarts.
    """

    CATEGORIES = {
        "project_location": "Configured project directories",
        "app_alias": "Custom application aliases",
        "common_directory": "Frequently accessed folders and paths",
        "user_preference": "General user preferences and configurations",
    }

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        self.db_path = Path(db_path) if db_path else MEMORY_DB_PATH
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._db_ok = True
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """Yields SQLite connection with WAL journal mode and row factory, closing upon exit."""
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
        """Creates table schema and indices."""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS preferences (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        category TEXT NOT NULL,
                        description TEXT,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_pref_category ON preferences(category);")
                conn.commit()
            self._db_ok = True
        except Exception as e:
            logger.warning(f"Could not initialize persistent memory SQLite database at {self.db_path}: {e}. Falling back to in-memory mode.")
            self._db_ok = False

    # --- Core CRUD Operations ---

    def set(
        self,
        key: str,
        value: str,
        category: str = "user_preference",
        description: str = "",
    ) -> bool:
        """
        Stores or updates a preference.
        """
        norm_key = key.strip().lower()
        norm_val = str(value).strip()
        cat = category if category else "user_preference"
        now = time.time()

        # Update cache
        self._memory_cache[norm_key] = {
            "key": norm_key,
            "value": norm_val,
            "category": cat,
            "description": description,
            "created_at": now,
            "updated_at": now,
        }

        if not self._db_ok:
            return True

        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO preferences (key, value, category, description, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        category = excluded.category,
                        description = COALESCE(excluded.description, preferences.description),
                        updated_at = excluded.updated_at
                """, (norm_key, norm_val, cat, description, now, now))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to persist memory key '{norm_key}': {e}")
            return False

    def get(
        self,
        key: str,
        default: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Optional[str]:
        """
        Retrieves a stored preference by key, with optional category filter.
        """
        norm_key = key.strip().lower()
        if not self._db_ok:
            item = self._memory_cache.get(norm_key)
            if item:
                if category and item.get("category") != category:
                    return default
                return item["value"]
            return default

        try:
            with self._get_connection() as conn:
                if category:
                    row = conn.execute(
                        "SELECT value FROM preferences WHERE key = ? AND category = ?",
                        (norm_key, category),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT value FROM preferences WHERE key = ?",
                        (norm_key,),
                    ).fetchone()
                if row:
                    return row["value"]
                return default
        except Exception as e:
            logger.error(f"Failed to query memory key '{norm_key}': {e}")
            item = self._memory_cache.get(norm_key)
            if item:
                if category and item.get("category") != category:
                    return default
                return item["value"]
            return default

    def delete(self, key: str, category: Optional[str] = None) -> bool:
        """
        Removes a stored preference, optionally ensuring category matches.
        """
        norm_key = key.strip().lower()
        cached = self._memory_cache.get(norm_key)
        if cached:
            if not category or cached.get("category") == category:
                self._memory_cache.pop(norm_key, None)

        if not self._db_ok:
            return True

        try:
            with self._get_connection() as conn:
                if category:
                    cursor = conn.execute(
                        "DELETE FROM preferences WHERE key = ? AND category = ?",
                        (norm_key, category),
                    )
                else:
                    cursor = conn.execute(
                        "DELETE FROM preferences WHERE key = ?",
                        (norm_key,),
                    )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to delete memory key '{norm_key}': {e}")
            return False

    def list_all(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Returns all stored items, optionally filtered by category.
        """
        if not self._db_ok:
            items = list(self._memory_cache.values())
            if category:
                items = [it for it in items if it["category"] == category]
            return items

        try:
            with self._get_connection() as conn:
                if category:
                    rows = conn.execute(
                        "SELECT key, value, category, description, created_at, updated_at FROM preferences WHERE category = ? ORDER BY key ASC",
                        (category,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT key, value, category, description, created_at, updated_at FROM preferences ORDER BY category, key ASC"
                    ).fetchall()

                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to list memories: {e}")
            return list(self._memory_cache.values())

    def clear_category(self, category: str) -> int:
        """Clears all records in a category."""
        if not self._db_ok:
            keys_to_del = [k for k, v in self._memory_cache.items() if v["category"] == category]
            for k in keys_to_del:
                del self._memory_cache[k]
            return len(keys_to_del)

        try:
            with self._get_connection() as conn:
                cursor = conn.execute("DELETE FROM preferences WHERE category = ?", (category,))
                conn.commit()
                return cursor.rowcount
        except Exception as e:
            logger.error(f"Failed to clear memory category '{category}': {e}")
            return 0

    def clear_all(self) -> int:
        """Clears all stored memories."""
        self._memory_cache.clear()
        if not self._db_ok:
            return 0

        try:
            with self._get_connection() as conn:
                cursor = conn.execute("DELETE FROM preferences")
                conn.commit()
                return cursor.rowcount
        except Exception as e:
            logger.error(f"Failed to clear all memories: {e}")
            return 0

    # --- Specialized Convenience Methods ---

    def set_project_location(self, project_name: str, path: Union[str, Path]) -> bool:
        """Associates a project name with its directory location."""
        p = Path(path).resolve()
        key = f"proj:{project_name.strip().lower()}"
        return self.set(
            key=key,
            value=str(p),
            category="project_location",
            description=f"Project directory for {project_name.strip()}",
        )

    def get_project_location(self, project_name: str) -> Optional[str]:
        """Resolves a project name to its stored path string, or None if not remembered."""
        clean_name = project_name.strip().lower()
        # Direct key check
        val = self.get(f"proj:{clean_name}")
        if val:
            return val

        # Check all project locations if fuzzy match
        for item in self.list_all(category="project_location"):
            item_key = item["key"].replace("proj:", "").lower()
            if clean_name in item_key or item_key in clean_name:
                return item["value"]
        return None

    def delete_project_location(self, project_name: str) -> bool:
        """Removes a stored project location."""
        key = f"proj:{project_name.strip().lower()}"
        return self.delete(key)

    def list_projects(self) -> Dict[str, str]:
        """Returns mapping of project name -> path."""
        projs = {}
        for item in self.list_all(category="project_location"):
            name = item["key"].replace("proj:", "")
            projs[name] = item["value"]
        return projs

    def set_app_alias(self, alias: str, app_name: str) -> bool:
        """Stores a custom application alias (e.g. 'code' -> 'Visual Studio Code')."""
        key = f"alias:{alias.strip().lower()}"
        return self.set(
            key=key,
            value=app_name.strip(),
            category="app_alias",
            description=f"Alias '{alias}' for {app_name.strip()}",
        )

    def get_app_alias(self, alias: str) -> Optional[str]:
        """Retrieves custom application alias."""
        return self.get(f"alias:{alias.strip().lower()}")

    def set_common_directory(self, name: str, path: Union[str, Path]) -> bool:
        """Stores a named common directory (e.g. 'work' -> 'D:\\Work')."""
        p = Path(path).resolve()
        key = f"dir:{name.strip().lower()}"
        return self.set(
            key=key,
            value=str(p),
            category="common_directory",
            description=f"Common directory for '{name}'",
        )

    def get_common_directory(self, name: str) -> Optional[str]:
        """Retrieves a common directory path string."""
        return self.get(f"dir:{name.strip().lower()}")
