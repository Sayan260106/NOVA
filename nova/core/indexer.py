"""
Nova Fast Filesystem & Entity Indexer
Uses SQLite to store and rapidly query files, folders, and metadata.
"""

import os
import time
import sqlite3
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Generator
from contextlib import contextmanager

from nova.config import (
    INDEX_DB_PATH,
    PRIORITY_SEARCH_ROOTS,
    EXCLUDED_DIR_NAMES,
)

logger = logging.getLogger("nova.indexer")


class FileItem:
    def __init__(
        self,
        name: str,
        path: str,
        is_dir: bool,
        extension: str = "",
        size: int = 0,
        mtime: float = 0.0,
        parent_name: str = "",
    ):
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.extension = extension
        self.size = size
        self.mtime = mtime
        self.parent_name = parent_name

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "is_dir": self.is_dir,
            "type": "folder" if self.is_dir else "file",
            "extension": self.extension,
            "size": self.size,
            "mtime": self.mtime,
            "parent_name": self.parent_name,
        }

    def __repr__(self) -> str:
        kind = "Dir" if self.is_dir else "File"
        return f"<{kind}: {self.name} ({self.path})>"


class Indexer:
    """Manages SQLite index of files, directories, and entities."""

    def __init__(self, db_path: Path = INDEX_DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create tables and indices if not already present."""
        with self._connection() as conn:
            with conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS files_index (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        lower_name TEXT NOT NULL,
                        path TEXT UNIQUE NOT NULL,
                        is_dir INTEGER NOT NULL,
                        extension TEXT,
                        size INTEGER,
                        mtime REAL,
                        parent_name TEXT
                    )
                    """
                )
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_lower_name ON files_index(lower_name)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_is_dir ON files_index(is_dir)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_extension ON files_index(extension)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_parent_name ON files_index(parent_name)")

    def record_item(self, item_path: Path) -> Optional[FileItem]:
        """Index a single file or directory in real time."""
        try:
            if not item_path.exists():
                return None
            stat = item_path.stat()
            is_dir = item_path.is_dir()
            name = item_path.name
            lower_name = name.lower()
            str_path = str(item_path.resolve())
            ext = item_path.suffix.lower() if not is_dir else ""
            size = stat.st_size if not is_dir else 0
            mtime = stat.st_mtime
            parent_name = item_path.parent.name

            with self._connection() as conn:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO files_index (name, lower_name, path, is_dir, extension, size, mtime, parent_name)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(path) DO UPDATE SET
                            name = excluded.name,
                            lower_name = excluded.lower_name,
                            is_dir = excluded.is_dir,
                            extension = excluded.extension,
                            size = excluded.size,
                            mtime = excluded.mtime,
                            parent_name = excluded.parent_name
                        """,
                        (name, lower_name, str_path, 1 if is_dir else 0, ext, size, mtime, parent_name),
                    )

            return FileItem(name, str_path, is_dir, ext, size, mtime, parent_name)
        except Exception as e:
            logger.debug(f"Error indexing item {item_path}: {e}")
            return None

    def remove_item(self, item_path: Path) -> None:
        """Remove a deleted item from the index."""
        try:
            str_path = str(item_path.resolve())
            with self._connection() as conn:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM files_index WHERE path = ? OR path LIKE ?", (str_path, f"{str_path}\\%"))
        except Exception as e:
            logger.debug(f"Error removing item from index {item_path}: {e}")

    def index_directory(
        self,
        directory: Path,
        max_depth: int = 5,
        max_files: int = 15000,
    ) -> int:
        """Walk and index a directory structure."""
        if not directory.exists() or not directory.is_dir():
            return 0

        count = 0
        batch: List[Tuple] = []

        try:
            for root, dirs, files in os.walk(directory):
                # Filter out excluded directories
                dirs[:] = [
                    d for d in dirs
                    if d.lower() not in EXCLUDED_DIR_NAMES
                    and not any(exc in os.path.join(root, d).lower() for exc in EXCLUDED_DIR_NAMES)
                ]

                # Calculate depth
                rel_parts = Path(root).relative_to(directory).parts
                if len(rel_parts) >= max_depth:
                    dirs.clear()

                root_path = Path(root)

                # Index subdirectories
                for d in dirs:
                    d_path = root_path / d
                    try:
                        stat = d_path.stat()
                        batch.append((
                            d,
                            d.lower(),
                            str(d_path.resolve()),
                            1,
                            "",
                            0,
                            stat.st_mtime,
                            root_path.name,
                        ))
                        count += 1
                    except (PermissionError, OSError):
                        continue

                # Index files
                for f in files:
                    f_path = root_path / f
                    try:
                        stat = f_path.stat()
                        batch.append((
                            f,
                            f.lower(),
                            str(f_path.resolve()),
                            0,
                            f_path.suffix.lower(),
                            stat.st_size,
                            stat.st_mtime,
                            root_path.name,
                        ))
                        count += 1
                    except (PermissionError, OSError):
                        continue

                if count >= max_files:
                    break

                if len(batch) >= 1000:
                    self._insert_batch(batch)
                    batch.clear()

            if batch:
                self._insert_batch(batch)

        except Exception as e:
            logger.warning(f"Error scanning directory {directory}: {e}")

        return count

    def _insert_batch(self, batch: List[Tuple]) -> None:
        with self._connection() as conn:
            with conn:
                cursor = conn.cursor()
                cursor.executemany(
                    """
                    INSERT INTO files_index (name, lower_name, path, is_dir, extension, size, mtime, parent_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        name = excluded.name,
                        lower_name = excluded.lower_name,
                        is_dir = excluded.is_dir,
                        extension = excluded.extension,
                        size = excluded.size,
                        mtime = excluded.mtime,
                        parent_name = excluded.parent_name
                    """,
                    batch,
                )

    def search(
        self,
        query: str,
        is_dir: Optional[bool] = None,
        extension: Optional[str] = None,
        parent_name: Optional[str] = None,
        limit: int = 20,
    ) -> List[FileItem]:
        """Fast indexed search by query, kind, and extension."""
        query_clean = query.strip().lower()
        sql = "SELECT name, path, is_dir, extension, size, mtime, parent_name FROM files_index WHERE "
        params: List[Any] = []
        conditions = []

        if query_clean:
            conditions.append("(lower_name = ? OR lower_name LIKE ?)")
            params.extend([query_clean, f"%{query_clean}%"])

        if is_dir is not None:
            conditions.append("is_dir = ?")
            params.append(1 if is_dir else 0)

        if extension:
            ext = extension.lower() if extension.startswith(".") else f".{extension.lower()}"
            conditions.append("extension = ?")
            params.append(ext)

        if parent_name:
            conditions.append("lower(parent_name) = ?")
            params.append(parent_name.strip().lower())

        if not conditions:
            sql = "SELECT name, path, is_dir, extension, size, mtime, parent_name FROM files_index "
        else:
            sql += " AND ".join(conditions)

        sql += " ORDER BY CASE WHEN lower_name = ? THEN 1 WHEN lower_name LIKE ? THEN 2 ELSE 3 END, mtime DESC LIMIT ?"
        params.extend([query_clean, f"{query_clean}%", limit])

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [
                FileItem(
                    name=r["name"],
                    path=r["path"],
                    is_dir=bool(r["is_dir"]),
                    extension=r["extension"] or "",
                    size=r["size"] or 0,
                    mtime=r["mtime"] or 0.0,
                    parent_name=r["parent_name"] or "",
                )
                for r in rows
            ]

    def count(self) -> int:
        """Total indexed entities."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM files_index")
            return cursor.fetchone()[0]
