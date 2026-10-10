"""
Nova Fast Filesystem & Entity Indexer
Uses SQLite to store and rapidly query files, folders, and metadata.
"""

import os
import re
import time
import sqlite3
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Generator, Union
from contextlib import contextmanager

from nova.config import (
    INDEX_DB_PATH,
    PRIORITY_SEARCH_ROOTS,
    EXCLUDED_DIR_NAMES,
)

logger = logging.getLogger("nova.indexer")

# Common category to file extensions mapping
EXTENSION_CATEGORY_MAP: Dict[str, List[str]] = {
    "python": [".py", ".pyw"],
    "javascript": [".js", ".mjs", ".cjs"],
    "typescript": [".ts", ".tsx"],
    "c": [".c", ".h"],
    "cpp": [".cpp", ".hpp", ".cc", ".cxx"],
    "java": [".java", ".jar"],
    "rust": [".rs"],
    "go": [".go"],
    "html": [".html", ".htm"],
    "css": [".css", ".scss", ".sass"],
    "json": [".json"],
    "yaml": [".yaml", ".yml"],
    "xml": [".xml"],
    "markdown": [".md", ".markdown"],
    "text": [".txt", ".text", ".log", ".md"],
    "pdf": [".pdf"],
    "document": [".pdf", ".docx", ".doc", ".xlsx", ".pptx", ".txt", ".odt", ".rtf"],
    "spreadsheet": [".xlsx", ".xls", ".csv"],
    "presentation": [".pptx", ".ppt"],
    "image": [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".ico"],
    "video": [".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm"],
    "audio": [".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma"],
    "archive": [".zip", ".tar", ".gz", ".7z", ".rar", ".bz2"],
    "code": [".py", ".js", ".ts", ".html", ".css", ".cpp", ".c", ".java", ".rs", ".go", ".sql"],
}


def parse_size_str(size_str: str) -> Optional[int]:
    """Parses human-readable size string (e.g. '10MB', '500KB', '1.5GB') into bytes."""
    if not size_str:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([a-zA-Z]*)$", str(size_str).strip())
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).lower()
    if unit in ("g", "gb", "gigabytes", "gigabyte"):
        return int(val * 1024 * 1024 * 1024)
    elif unit in ("m", "mb", "megabytes", "megabyte"):
        return int(val * 1024 * 1024)
    elif unit in ("k", "kb", "kilobytes", "kilobyte"):
        return int(val * 1024)
    elif unit in ("b", "bytes", "byte", ""):
        return int(val)
    return None


def format_size(bytes_val: int) -> str:
    """Formats bytes into human-readable string (e.g. '12.4 KB', '3.1 MB')."""
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} KB"
    elif bytes_val < 1024 * 1024 * 1024:
        return f"{bytes_val / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"


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
        score: float = 0.0,
    ):
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.extension = extension
        self.size = size
        self.mtime = mtime
        self.parent_name = parent_name
        self.score = score

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "is_dir": self.is_dir,
            "type": "folder" if self.is_dir else "file",
            "extension": self.extension,
            "size": self.size,
            "size_formatted": format_size(self.size) if not self.is_dir else "",
            "mtime": self.mtime,
            "parent_name": self.parent_name,
            "score": round(self.score, 2),
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
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA busy_timeout = 30000;")
        except Exception:
            pass
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
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_mtime ON files_index(mtime)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_size ON files_index(size)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_path ON files_index(path)")

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

    def search_advanced(
        self,
        query: Optional[str] = None,
        is_dir: Optional[bool] = None,
        extension: Optional[Union[str, List[str]]] = None,
        directory: Optional[Union[str, Path]] = None,
        min_mtime: Optional[float] = None,
        max_mtime: Optional[float] = None,
        modified_within_days: Optional[float] = None,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
        limit: int = 50,
        sort_by: str = "relevance",
    ) -> List[FileItem]:
        """
        Comprehensive search supporting query, extension categories, directory subtree,
        modification date boundaries, file size filtering, and relevance ranking.
        """
        now = time.time()
        query_clean = (query or "").strip().lower()

        # Handle modified_within_days
        if modified_within_days is not None and min_mtime is None:
            try:
                min_mtime = now - (float(modified_within_days) * 86400.0)
            except Exception:
                pass

        # Handle extensions (categories and lists)
        allowed_exts: List[str] = []
        if extension:
            if isinstance(extension, str):
                ext_str = extension.strip().lower()
                if ext_str in EXTENSION_CATEGORY_MAP:
                    allowed_exts.extend(EXTENSION_CATEGORY_MAP[ext_str])
                elif ext_str.startswith("."):
                    allowed_exts.append(ext_str)
                else:
                    allowed_exts.append(f".{ext_str}")
            elif isinstance(extension, (list, tuple, set)):
                for e in extension:
                    e_str = str(e).strip().lower()
                    if e_str in EXTENSION_CATEGORY_MAP:
                        allowed_exts.extend(EXTENSION_CATEGORY_MAP[e_str])
                    elif e_str.startswith("."):
                        allowed_exts.append(e_str)
                    else:
                        allowed_exts.append(f".{e_str}")

        # Build SQL conditions
        sql = "SELECT name, path, is_dir, extension, size, mtime, parent_name FROM files_index WHERE "
        params: List[Any] = []
        conditions: List[str] = []

        if query_clean:
            conditions.append("(lower_name = ? OR lower_name LIKE ? OR path LIKE ?)")
            params.extend([query_clean, f"%{query_clean}%", f"%{query_clean}%"])

        if is_dir is not None:
            conditions.append("is_dir = ?")
            params.append(1 if is_dir else 0)

        if allowed_exts:
            placeholders = ",".join(["?"] * len(allowed_exts))
            conditions.append(f"extension IN ({placeholders})")
            params.extend(allowed_exts)

        if directory:
            str_dir = str(directory).strip()
            dir_path = Path(str_dir)
            if dir_path.is_absolute() and dir_path.exists():
                resolved_dir = str(dir_path.resolve())
                conditions.append("(path LIKE ? OR path = ?)")
                params.extend([f"{resolved_dir}\\%", resolved_dir])
            else:
                clean_dir_name = str_dir.lower().rstrip("\\/").split("\\")[-1].split("/")[-1]
                conditions.append("(lower(parent_name) = ? OR lower(path) LIKE ? OR lower(path) LIKE ?)")
                params.extend([clean_dir_name, f"%\\{clean_dir_name}\\%", f"%/{clean_dir_name}/%"])

        if min_mtime is not None:
            conditions.append("mtime >= ?")
            params.append(float(min_mtime))

        if max_mtime is not None:
            conditions.append("mtime <= ?")
            params.append(float(max_mtime))

        if min_size is not None:
            conditions.append("size >= ?")
            params.append(int(min_size))

        if max_size is not None:
            conditions.append("size <= ?")
            params.append(int(max_size))

        if conditions:
            sql += " AND ".join(conditions)
        else:
            sql = "SELECT name, path, is_dir, extension, size, mtime, parent_name FROM files_index"

        # Fetch candidates for ranking
        fetch_limit = max(limit * 3, 100) if sort_by == "relevance" else limit
        sql += " LIMIT ?"
        params.append(fetch_limit)

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        items: List[FileItem] = []
        for r in rows:
            name = r["name"]
            path = r["path"]
            item_is_dir = bool(r["is_dir"])
            ext = r["extension"] or ""
            size = r["size"] or 0
            mtime = r["mtime"] or 0.0
            parent_name = r["parent_name"] or ""

            # Calculate relevance score
            score = 0.0
            name_lower = name.lower()
            if query_clean:
                if name_lower == query_clean:
                    score += 100.0
                elif Path(name).stem.lower() == query_clean:
                    score += 90.0
                elif name_lower.startswith(query_clean):
                    score += 75.0
                elif query_clean in name_lower:
                    score += 55.0
                elif query_clean in path.lower():
                    score += 30.0
            else:
                score += 50.0

            # Recency boost
            if mtime > 0:
                age_days = (now - mtime) / 86400.0
                if age_days <= 1:
                    score += 25.0
                elif age_days <= 7:
                    score += 18.0
                elif age_days <= 30:
                    score += 10.0
                elif age_days <= 90:
                    score += 5.0

            # Filter exact match boost
            if allowed_exts and ext in allowed_exts:
                score += 10.0

            items.append(FileItem(name, path, item_is_dir, ext, size, mtime, parent_name, score=score))

        # Sort items
        if sort_by == "relevance":
            items.sort(key=lambda x: (x.score, x.mtime), reverse=True)
        elif sort_by == "mtime_desc":
            items.sort(key=lambda x: x.mtime, reverse=True)
        elif sort_by == "size_desc":
            items.sort(key=lambda x: x.size, reverse=True)
        elif sort_by == "name_asc":
            items.sort(key=lambda x: x.name.lower())

        return items[:limit]

    def search(
        self,
        query: str,
        is_dir: Optional[bool] = None,
        extension: Optional[str] = None,
        parent_name: Optional[str] = None,
        limit: int = 20,
    ) -> List[FileItem]:
        """Fast indexed search by query, kind, and extension."""
        return self.search_advanced(
            query=query,
            is_dir=is_dir,
            extension=extension,
            directory=parent_name,
            limit=limit,
            sort_by="relevance",
        )

    def count(self) -> int:
        """Total indexed entities."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM files_index")
            return cursor.fetchone()[0]
