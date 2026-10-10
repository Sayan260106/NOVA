"""
Nova File Manager
Implements zero-path file and folder operations:
create, delete, rename, move, copy, open, and find across all drives in File Explorer.
"""

import os
import re
import shutil
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union, Set
from collections import defaultdict

import send2trash

from nova.config import (
    DEFAULT_WORKSPACE,
    PRIORITY_SEARCH_ROOTS,
    EXCLUDED_DIR_NAMES,
    USER_HOME,
    AVAILABLE_DRIVES,
)
from nova.core.indexer import Indexer, FileItem
from nova.core.results import ToolResult

logger = logging.getLogger("nova.file_manager")

# Categories for folder organization by file extension
ORGANIZATION_CATEGORIES: Dict[str, Set[str]] = {
    "Documents": {".pdf", ".docx", ".doc", ".txt", ".pptx", ".ppt", ".xlsx", ".xls", ".csv", ".rtf", ".odt", ".epub"},
    "Images": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".ico", ".tiff"},
    "Videos": {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v"},
    "Audio": {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma"},
    "Archives": {".zip", ".tar", ".gz", ".7z", ".rar", ".bz2", ".xz", ".iso"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".cpp", ".c", ".h", ".hpp", ".java", ".rs", ".go", ".json", ".sql", ".yaml", ".yml", ".xml", ".sh", ".ps1"},
    "Installers": {".exe", ".msi", ".bat", ".cmd"},
}


class FileManager:
    """Provides smart zero-path file and directory operations for Nova."""

    def __init__(self, indexer: Optional[Indexer] = None, default_root: Optional[Union[str, Path]] = None):
        self.indexer = indexer or Indexer()
        self.default_root = Path(default_root).resolve() if default_root else None

    def resolve_target(
        self,
        name: str,
        is_dir: Optional[bool] = None,
        parent_name: Optional[str] = None,
        deep_search: bool = True,
    ) -> Optional[Path]:
        """
        Locates a file or directory across the computer without requiring the full path.
        Priority:
        1. Check if name refers to a drive root (e.g. "D:", "D drive", "D:\", "C:")
        2. Direct check if path is absolute and exists
        3. Check in Priority roots (Workspace / D: drive, Desktop, Documents, Downloads, etc.)
        4. SQLite Index lookup
        5. Real-time fast pruned search across all drives in File Explorer
        """
        target_name = name.strip()
        lower_name = target_name.lower()

        # 1. Check if drive letter or drive name requested (e.g. "d:", "d drive", "d:\", "d:/")
        drive_match = re.match(r"^([a-zA-Z]):?(?:\s*drive)?(?:[\\/])?$", target_name, re.IGNORECASE)
        if drive_match and len(target_name.split()) <= 2:
            letter = drive_match.group(1).upper()
            drive_candidate = Path(f"{letter}:/")
            if drive_candidate.exists():
                return drive_candidate.resolve()

        # 2. Check if already an absolute existing path
        candidate = Path(target_name)
        if candidate.is_absolute() and candidate.exists():
            if is_dir is None or candidate.is_dir() == is_dir:
                return candidate.resolve()

        # 2b. Check default_root if configured
        if self.default_root and self.default_root.exists():
            direct_root_child = self.default_root / target_name
            if direct_root_child.exists() and (is_dir is None or direct_root_child.is_dir() == is_dir):
                return direct_root_child.resolve()
            for sub_p in self.default_root.rglob(target_name):
                if is_dir is None or sub_p.is_dir() == is_dir:
                    return sub_p.resolve()

        # 3. Check Priority Roots
        for root in PRIORITY_SEARCH_ROOTS:
            if not root.exists():
                continue
            # Direct child check first
            direct_child = root / target_name
            if direct_child.exists():
                if is_dir is None or direct_child.is_dir() == is_dir:
                    return direct_child.resolve()

            # Check shallow subdirectories (avoid unbounded whole-drive glob)
            is_drive_root = (root.parent == root or len(str(root).rstrip("\\/")) <= 2)
            if is_drive_root:
                try:
                    for child in root.iterdir():
                        if child.is_dir() and child.name.lower() not in EXCLUDED_DIR_NAMES:
                            sub_candidate = child / target_name
                            if sub_candidate.exists() and (is_dir is None or sub_candidate.is_dir() == is_dir):
                                if parent_name:
                                    if sub_candidate.parent.name.lower() == parent_name.lower():
                                        return sub_candidate.resolve()
                                else:
                                    return sub_candidate.resolve()
                except (PermissionError, OSError):
                    pass
            else:
                try:
                    for p in root.glob(f"*/{target_name}"):
                        if p.exists() and (is_dir is None or p.is_dir() == is_dir):
                            if parent_name:
                                if p.parent.name.lower() == parent_name.lower():
                                    return p.resolve()
                            else:
                                return p.resolve()
                except (PermissionError, OSError):
                    pass

        # 4. Check SQLite Index
        matches = self.indexer.search(
            query=target_name,
            is_dir=is_dir,
            parent_name=parent_name,
            limit=10,
        )
        for item in matches:
            p = Path(item.path)
            if p.exists():
                if lower_name == p.name.lower():
                    return p.resolve()

        if matches:
            for item in matches:
                p = Path(item.path)
                if p.exists():
                    return p.resolve()

        # 5. Deep search across all drives if still not found
        if deep_search:
            found = self._deep_search_filesystem(target_name, is_dir, parent_name)
            if found:
                self.indexer.record_item(found)
                return found

        return None

    def find_all_candidates(
        self,
        name: str,
        is_dir: Optional[bool] = None,
    ) -> List[Path]:
        """
        Finds all files or folders across the system that match the exact name.
        Used to detect duplicates and disambiguate deletions.
        """
        target_name = name.strip()
        lower_name = target_name.lower()
        candidates: List[Path] = []
        seen = set()

        def add_candidate(p: Path):
            try:
                resolved = p.resolve()
                str_p = str(resolved).lower()
                if str_p not in seen and resolved.exists():
                    if is_dir is None or resolved.is_dir() == is_dir:
                        if resolved.name.lower() == lower_name:
                            seen.add(str_p)
                            candidates.append(resolved)
            except (PermissionError, OSError):
                pass

        # 1. Direct check in priority roots
        for root in PRIORITY_SEARCH_ROOTS:
            if not root.exists():
                continue
            direct_child = root / target_name
            if direct_child.exists():
                add_candidate(direct_child)
            is_drive_root = (root.parent == root or len(str(root).rstrip("\\/")) <= 2)
            if is_drive_root:
                try:
                    for child in root.iterdir():
                        if child.is_dir() and child.name.lower() not in EXCLUDED_DIR_NAMES:
                            sub = child / target_name
                            if sub.exists():
                                add_candidate(sub)
                except (PermissionError, OSError):
                    pass
            else:
                try:
                    for p in root.glob(f"*/{target_name}"):
                        add_candidate(p)
                except (PermissionError, OSError):
                    pass

        # 2. Check SQLite index
        matches = self.indexer.search(query=target_name, is_dir=is_dir, limit=50)
        for item in matches:
            p = Path(item.path)
            if p.exists() and p.name.lower() == lower_name:
                add_candidate(p)

        return candidates

    def find_open_candidates(
        self,
        name: str,
        is_dir: Optional[bool] = None,
    ) -> List[Path]:
        """
        Finds all files or folders matching a target name for opening.
        Matches exact name, and if no extension specified, also matches files with matching stem.
        Supports filtering by is_dir (True for folders only, False for files only).
        """
        target_name = name.strip()
        lower_name = target_name.lower()
        has_ext = bool(Path(target_name).suffix)
        candidates: List[Path] = []
        seen = set()

        def add_candidate(p: Path):
            try:
                resolved = p.resolve()
                str_p = str(resolved).lower()
                if str_p not in seen and resolved.exists():
                    if is_dir is not None and resolved.is_dir() != is_dir:
                        return
                    p_name_lower = resolved.name.lower()
                    p_stem_lower = resolved.stem.lower()

                    if p_name_lower == lower_name:
                        seen.add(str_p)
                        candidates.append(resolved)
                    elif not has_ext and not resolved.is_dir() and p_stem_lower == lower_name:
                        seen.add(str_p)
                        candidates.append(resolved)
            except (PermissionError, OSError):
                pass

        # 1. Check priority roots
        for root in PRIORITY_SEARCH_ROOTS:
            if not root.exists():
                continue
            direct_child = root / target_name
            if direct_child.exists():
                add_candidate(direct_child)

            # If no extension, also check for file with matching stem in root
            if not has_ext and is_dir is not True:
                try:
                    for ext_match in root.glob(f"{target_name}.*"):
                        add_candidate(ext_match)
                except (PermissionError, OSError):
                    pass

            is_drive_root = (root.parent == root or len(str(root).rstrip("\\/")) <= 2)
            if is_drive_root:
                try:
                    for child in root.iterdir():
                        if child.name.lower() in EXCLUDED_DIR_NAMES:
                            continue
                        add_candidate(child)
                        if child.is_dir():
                            sub = child / target_name
                            if sub.exists():
                                add_candidate(sub)
                            if not has_ext and is_dir is not True:
                                for ext_match in child.glob(f"{target_name}.*"):
                                    add_candidate(ext_match)
                except (PermissionError, OSError):
                    pass
            else:
                try:
                    for child in root.iterdir():
                        add_candidate(child)
                    for p in root.glob(f"*/{target_name}"):
                        add_candidate(p)
                    if not has_ext and is_dir is not True:
                        for p in root.glob(f"*/{target_name}.*"):
                            add_candidate(p)
                except (PermissionError, OSError):
                    pass

        # 2. Check SQLite index
        matches = self.indexer.search(query=target_name, is_dir=is_dir, limit=50)
        for item in matches:
            p = Path(item.path)
            if p.exists():
                add_candidate(p)

        return candidates

    def _deep_search_filesystem(
        self,
        name: str,
        is_dir: Optional[bool] = None,
        parent_name: Optional[str] = None,
    ) -> Optional[Path]:
        """Perform a fast pruned search starting from User Home then all logical drives."""
        lower_name = name.lower()
        search_roots = [USER_HOME]

        # Add all available logical drives (e.g. C:/, D:/, etc.)
        for drv in AVAILABLE_DRIVES:
            if drv not in search_roots:
                search_roots.append(drv)

        for search_root in search_roots:
            if not search_root.exists():
                continue
            try:
                for root, dirs, files in os.walk(search_root):
                    # Prune excluded directories
                    dirs[:] = [
                        d for d in dirs
                        if d.lower() not in EXCLUDED_DIR_NAMES
                        and not any(exc in os.path.join(root, d).lower() for exc in EXCLUDED_DIR_NAMES)
                    ]

                    # Prune depth beyond 4 levels from search root for performance
                    root_path = Path(root)
                    try:
                        rel_parts = root_path.relative_to(search_root).parts
                        if len(rel_parts) >= 4:
                            dirs.clear()
                    except ValueError:
                        pass

                    # Check directories if is_dir is True or None
                    if is_dir in (True, None):
                        for d in dirs:
                            if d.lower() == lower_name:
                                candidate = Path(root) / d
                                if parent_name:
                                    if candidate.parent.name.lower() == parent_name.lower():
                                        return candidate.resolve()
                                else:
                                    return candidate.resolve()

                    # Check files if is_dir is False or None
                    if is_dir in (False, None):
                        for f in files:
                            if f.lower() == lower_name:
                                candidate = Path(root) / f
                                if parent_name:
                                    if candidate.parent.name.lower() == parent_name.lower():
                                        return candidate.resolve()
                                else:
                                    return candidate.resolve()
            except (PermissionError, OSError):
                continue

        return None

    def create_folder(self, folder_name: str, parent_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Creates a new folder.
        If parent_name is specified, resolves the parent folder path automatically.
        If parent_name is omitted, creates in D: drive (DEFAULT_WORKSPACE).
        """
        target_parent = self.default_root if self.default_root else DEFAULT_WORKSPACE
        resolved_parent_msg = f"D: drive ({target_parent})" if str(target_parent).startswith("D:") else f"workspace ({target_parent.name})"

        if parent_name:
            clean_parent = re.sub(r"\s+(folder|directory|dir|drive)$", "", parent_name.strip(), flags=re.IGNORECASE).strip("'\" ")
            lower_clean = clean_parent.lower().rstrip(":")
            if lower_clean in ("d", "d drive") or clean_parent.lower() in ("d:", "d: drive"):
                target_parent = DEFAULT_WORKSPACE
                resolved_parent_msg = f"D: drive ({DEFAULT_WORKSPACE})"
            elif os.path.isabs(clean_parent) and Path(clean_parent).is_dir():
                target_parent = Path(clean_parent).resolve()
                resolved_parent_msg = f"'{target_parent.name}' at {target_parent}"
            else:
                resolved = self.resolve_target(clean_parent, is_dir=True)
                if resolved and resolved.is_dir():
                    target_parent = resolved
                    resolved_parent_msg = f"'{resolved.name}' at {resolved}"
                else:
                    # If parent folder does not exist, auto-create it in DEFAULT_WORKSPACE
                    try:
                        auto_parent = DEFAULT_WORKSPACE / clean_parent
                        auto_parent.mkdir(parents=True, exist_ok=True)
                        self.indexer.record_item(auto_parent)
                        target_parent = auto_parent
                        resolved_parent_msg = f"'{auto_parent.name}' at {auto_parent}"
                    except Exception:
                        return ToolResult.fail(
                            error=f"Parent folder '{parent_name}' could not be located or created.",
                            data={"folder_name": folder_name, "parent_name": parent_name},
                        )

        clean_folder_name = folder_name.strip().strip("'\" ")
        new_folder_path = target_parent / clean_folder_name
        try:
            new_folder_path.mkdir(parents=True, exist_ok=True)
            self.indexer.record_item(new_folder_path)
            str_path = str(new_folder_path.resolve())
            return ToolResult.ok(
                message=f"Folder '{new_folder_path.name}' created inside {resolved_parent_msg}.",
                data={
                    "folder_name": new_folder_path.name,
                    "path": str_path,
                    "parent": str(target_parent.resolve()),
                },
                undo_info={
                    "action": "delete",
                    "path": str_path,
                    "type": "folder",
                    "permanent": False,
                },
            )
        except Exception as e:
            return ToolResult.fail(
                error=f"Failed to create folder '{folder_name}': {str(e)}",
                data={"folder_name": folder_name, "parent": str(target_parent.resolve())},
            )

    def create_file(
        self,
        file_name: str,
        content: str = "",
        parent_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Creates a new file with optional content.
        If parent_name is specified, locates the folder automatically.
        If parent_name is omitted, creates in D: drive (DEFAULT_WORKSPACE).
        """
        target_parent = self.default_root if self.default_root else DEFAULT_WORKSPACE
        resolved_parent_msg = f"D: drive ({target_parent})" if str(target_parent).startswith("D:") else f"workspace ({target_parent.name})"

        if parent_name:
            clean_parent = re.sub(r"\s+(folder|directory|dir|drive)$", "", parent_name.strip(), flags=re.IGNORECASE).strip("'\" ")
            lower_clean = clean_parent.lower().rstrip(":")
            if lower_clean in ("d", "d drive") or clean_parent.lower() in ("d:", "d: drive"):
                target_parent = DEFAULT_WORKSPACE
                resolved_parent_msg = f"D: drive ({DEFAULT_WORKSPACE})"
            elif os.path.isabs(clean_parent) and Path(clean_parent).is_dir():
                target_parent = Path(clean_parent).resolve()
                resolved_parent_msg = f"'{target_parent.name}' at {target_parent}"
            else:
                resolved = self.resolve_target(clean_parent, is_dir=True)
                if resolved and resolved.is_dir():
                    target_parent = resolved
                    resolved_parent_msg = f"'{resolved.name}' at {resolved}"
                else:
                    # If parent folder does not exist, auto-create it in DEFAULT_WORKSPACE
                    try:
                        auto_parent = DEFAULT_WORKSPACE / clean_parent
                        auto_parent.mkdir(parents=True, exist_ok=True)
                        self.indexer.record_item(auto_parent)
                        target_parent = auto_parent
                        resolved_parent_msg = f"'{auto_parent.name}' at {auto_parent}"
                    except Exception:
                        return ToolResult.fail(
                            error=f"Parent folder '{parent_name}' could not be located.",
                            data={"file_name": file_name, "parent_name": parent_name},
                        )

        clean_file_name = file_name.strip().strip("'\" ")
        new_file_path = target_parent / clean_file_name
        try:
            new_file_path.write_text(content, encoding="utf-8")
            self.indexer.record_item(new_file_path)
            str_path = str(new_file_path.resolve())
            return ToolResult.ok(
                message=f"File '{new_file_path.name}' created inside {resolved_parent_msg}.",
                data={
                    "file_name": new_file_path.name,
                    "path": str_path,
                    "parent": str(target_parent.resolve()),
                    "size": len(content.encode("utf-8")),
                },
                undo_info={
                    "action": "delete",
                    "path": str_path,
                    "type": "file",
                    "permanent": False,
                },
            )
        except Exception as e:
            return ToolResult.fail(
                error=f"Failed to create file '{file_name}': {str(e)}",
                data={"file_name": file_name, "parent": str(target_parent.resolve())},
            )

    def read_file(
        self,
        file_name: str,
        parent_name: Optional[str] = None,
        max_chars: int = 15000,
    ) -> Dict[str, Any]:
        """
        Reads content from a file located by name without requiring full path.
        """
        clean_name = file_name.strip().strip("'\" ")
        clean_parent = re.sub(r"\s+(folder|directory|dir)$", "", parent_name.strip(), flags=re.IGNORECASE).strip("'\" ") if parent_name else None
        target_path = self.resolve_target(clean_name, is_dir=False, parent_name=clean_parent)
        if not target_path or not target_path.exists() or target_path.is_dir():
            return ToolResult.fail(
                error=f"File '{clean_name}' could not be located to read.",
                data={"file_name": clean_name},
            )

        try:
            content = target_path.read_text(encoding="utf-8", errors="replace")
            is_truncated = len(content) > max_chars
            if is_truncated:
                content = content[:max_chars]
            return ToolResult.ok(
                message=f"Read {len(content)} characters from '{target_path.name}'.",
                data={
                    "file_name": target_path.name,
                    "path": str(target_path.resolve()),
                    "content": content,
                    "size": target_path.stat().st_size,
                    "truncated": is_truncated,
                },
            )
        except Exception as e:
            return ToolResult.fail(
                error=f"Failed to read file '{target_path.name}': {str(e)}",
                data={"file_name": target_path.name},
            )

    def rename_item(
        self,
        old_name: str,
        new_name: str,
        is_dir: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Renames a file or folder by resolving its existing name without requiring full path.
        """
        target_path = self.resolve_target(old_name, is_dir=is_dir)
        if not target_path or not target_path.exists():
            return ToolResult.fail(
                error=f"Item '{old_name}' could not be located to rename.",
                data={"old_name": old_name, "new_name": new_name},
            )

        clean_new_name = new_name.strip()
        new_path = target_path.parent / clean_new_name
        item_type = "folder" if target_path.is_dir() else "file"

        if new_path.exists() and new_path != target_path:
            return ToolResult.fail(
                error=f"Cannot rename: An item named '{clean_new_name}' already exists in {target_path.parent}.",
                data={"old_name": old_name, "new_name": new_name, "existing_path": str(new_path)},
            )

        try:
            target_path.rename(new_path)
            self.indexer.remove_item(target_path)
            self.indexer.record_item(new_path)

            old_str = str(target_path.resolve())
            new_str = str(new_path.resolve())
            return ToolResult.ok(
                message=f"Successfully renamed {item_type} '{target_path.name}' to '{new_path.name}' in {target_path.parent}.",
                data={
                    "old_name": target_path.name,
                    "new_name": new_path.name,
                    "old_path": old_str,
                    "new_path": new_str,
                    "type": item_type,
                },
                undo_info={
                    "action": "rename",
                    "old_path": new_str,
                    "new_path": old_str,
                    "type": item_type,
                },
            )
        except Exception as e:
            return ToolResult.fail(
                error=f"Failed to rename {item_type} '{old_name}' to '{new_name}': {str(e)}",
                data={"old_name": old_name, "new_name": new_name},
            )

    def delete_path(
        self,
        target_path: Path,
        permanent: bool = False,
    ) -> Dict[str, Any]:
        """Deletes a specific resolved file or directory path directly."""
        if not target_path or not target_path.exists():
            return ToolResult.fail(
                error=f"Item at '{target_path}' does not exist.",
                data={"path": str(target_path) if target_path else ""},
            )

        item_type = "folder" if target_path.is_dir() else "file"
        str_path = str(target_path.resolve())

        try:
            if permanent:
                if target_path.is_dir():
                    shutil.rmtree(target_path)
                else:
                    target_path.unlink()
                recycled = False
            else:
                send2trash.send2trash(str_path)
                recycled = True

            self.indexer.remove_item(target_path)
            action = "permanently deleted" if permanent else "moved to Recycle Bin"
            undo_info = (
                {"action": "restore_recycle_bin", "path": str_path, "type": item_type, "recycled": True}
                if recycled else None
            )
            return ToolResult.ok(
                message=f"Successfully {action} {item_type} '{target_path.name}'.",
                data={
                    "name": target_path.name,
                    "path": str_path,
                    "type": item_type,
                    "recycled": recycled,
                },
                undo_info=undo_info,
            )
        except Exception as e:
            return ToolResult.fail(
                error=f"Failed to delete {item_type} at '{str_path}': {str(e)}",
                data={"path": str_path, "type": item_type},
            )

    def delete_item(
        self,
        name: str,
        is_dir: Optional[bool] = None,
        permanent: bool = False,
    ) -> Dict[str, Any]:
        """
        Deletes a file or folder by resolving its name.
        Defaults to safe Recycle Bin deletion via send2trash.
        """
        target_path = self.resolve_target(name, is_dir=is_dir)
        if not target_path or not target_path.exists():
            return ToolResult.fail(
                error=f"Item '{name}' could not be found to delete.",
                data={"name": name},
            )

        return self.delete_path(target_path, permanent=permanent)

    def copy_item(
        self,
        source_name: str,
        destination_folder_name: str,
    ) -> Dict[str, Any]:
        """
        Copies a file or folder to a target destination folder,
        resolving both source and destination without needing explicit full paths.
        """
        source_path = self.resolve_target(source_name)
        if not source_path or not source_path.exists():
            return ToolResult.fail(
                error=f"Source item '{source_name}' could not be found.",
                data={"source_name": source_name},
            )

        dest_dir = self.resolve_target(destination_folder_name, is_dir=True)
        if not dest_dir or not dest_dir.is_dir():
            return ToolResult.fail(
                error=f"Destination folder '{destination_folder_name}' could not be found.",
                data={"destination_folder_name": destination_folder_name},
            )

        dest_path = dest_dir / source_path.name

        try:
            if source_path.is_dir():
                if dest_path.exists():
                    shutil.rmtree(dest_path)
                shutil.copytree(source_path, dest_path)
            else:
                shutil.copy2(source_path, dest_path)

            self.indexer.record_item(dest_path)
            dest_str = str(dest_path.resolve())
            return ToolResult.ok(
                message=f"Copied '{source_path.name}' to '{dest_dir.name}' ({dest_dir}).",
                data={
                    "name": source_path.name,
                    "source": str(source_path.resolve()),
                    "destination": dest_str,
                },
                undo_info={
                    "action": "delete",
                    "path": dest_str,
                    "type": "folder" if source_path.is_dir() else "file",
                    "permanent": False,
                },
            )
        except Exception as e:
            return ToolResult.fail(
                error=f"Failed to copy '{source_name}': {str(e)}",
                data={"source_name": source_name, "destination": destination_folder_name},
            )

    def move_item(
        self,
        source_name: str,
        destination_folder_name: str,
    ) -> Dict[str, Any]:
        """
        Moves a file or folder to a target destination folder,
        resolving both source and destination without needing explicit full paths.
        """
        source_path = self.resolve_target(source_name)
        if not source_path or not source_path.exists():
            return ToolResult.fail(
                error=f"Source item '{source_name}' could not be found.",
                data={"source_name": source_name},
            )

        dest_dir = self.resolve_target(destination_folder_name, is_dir=True)
        if not dest_dir or not dest_dir.is_dir():
            return ToolResult.fail(
                error=f"Destination folder '{destination_folder_name}' could not be found.",
                data={"destination_folder_name": destination_folder_name},
            )

        dest_path = dest_dir / source_path.name
        source_parent_str = str(source_path.parent.resolve())

        try:
            shutil.move(str(source_path), str(dest_path))
            self.indexer.remove_item(source_path)
            self.indexer.record_item(dest_path)
            dest_str = str(dest_path.resolve())
            return ToolResult.ok(
                message=f"Moved '{dest_path.name}' to '{dest_dir.name}' ({dest_dir}).",
                data={
                    "name": dest_path.name,
                    "source": str(source_path),
                    "destination": dest_str,
                },
                undo_info={
                    "action": "move",
                    "source": dest_str,
                    "destination": source_parent_str,
                },
            )
        except Exception as e:
            return ToolResult.fail(
                error=f"Failed to move '{source_name}': {str(e)}",
                data={"source_name": source_name, "destination": destination_folder_name},
            )

    def resolve_conflict_path(
        self,
        target_path: Path,
        strategy: str = "rename",
    ) -> Optional[Path]:
        """
        Resolves path conflict if file already exists at destination.
        strategy:
          - 'rename': appends (1), (2), etc. before suffix.
          - 'skip': returns None.
          - 'overwrite': returns original path.
        """
        if not target_path.exists():
            return target_path

        if strategy == "skip":
            return None
        elif strategy == "overwrite":
            return target_path

        # Default strategy: rename to avoid overwrite
        parent = target_path.parent
        stem = target_path.stem
        suffix = target_path.suffix
        idx = 1
        while True:
            candidate = parent / f"{stem} ({idx}){suffix}"
            if not candidate.exists():
                return candidate
            idx += 1

    def organize_folder_by_type(
        self,
        folder_name: str,
        preview: bool = False,
        conflict_strategy: str = "rename",
    ) -> ToolResult:
        """
        Organizes files in a target folder into category subfolders based on extension.
        Skips subdirectories. Supports dry-run preview and safe conflict resolution.
        """
        target_dir = self.resolve_target(folder_name, is_dir=True)
        if not target_dir or not target_dir.exists() or not target_dir.is_dir():
            return ToolResult.fail(
                error=f"Folder '{folder_name}' could not be located to organize.",
                data={"folder_name": folder_name},
            )

        # Plan moves
        moves: List[Dict[str, Any]] = []
        try:
            for item in target_dir.iterdir():
                if item.is_dir():
                    continue  # Do not touch subfolders

                ext = item.suffix.lower()
                category = "Others"
                for cat_name, ext_set in ORGANIZATION_CATEGORIES.items():
                    if ext in ext_set:
                        category = cat_name
                        break

                dest_folder = target_dir / category
                dest_file = dest_folder / item.name
                resolved_dest = self.resolve_conflict_path(dest_file, strategy=conflict_strategy)
                if resolved_dest is None:
                    continue  # Skipped due to conflict strategy

                moves.append({
                    "source": str(item.resolve()),
                    "destination": str(resolved_dest.resolve()),
                    "category": category,
                    "file_name": item.name,
                    "target_name": resolved_dest.name,
                })
        except Exception as e:
            return ToolResult.fail(
                error=f"Error scanning folder '{target_dir.name}': {str(e)}",
                data={"folder": str(target_dir)},
            )

        if preview:
            return ToolResult.ok(
                message=f"Preview: {len(moves)} file(s) would be organized into category subfolders in '{target_dir.name}'.",
                data={
                    "folder": str(target_dir),
                    "preview": True,
                    "count": len(moves),
                    "moves": moves,
                },
            )

        # Execute moves
        executed_moves: List[Dict[str, Any]] = []
        errors: List[str] = []
        for m in moves:
            src = Path(m["source"])
            dst = Path(m["destination"])
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                self.indexer.remove_item(src)
                self.indexer.record_item(dst)
                executed_moves.append(m)
            except Exception as e:
                errors.append(f"Failed to move '{src.name}': {str(e)}")

        count = len(executed_moves)
        if count == 0 and len(moves) == 0:
            return ToolResult.ok(
                message=f"Folder '{target_dir.name}' is already organized or contains no files to move.",
                data={"folder": str(target_dir), "count": 0, "moves": []},
            )

        err_msg = f" ({len(errors)} error(s))" if errors else ""
        return ToolResult.ok(
            message=f"Successfully organized {count} file(s) in '{target_dir.name}' by file type{err_msg}.",
            data={
                "folder": str(target_dir),
                "count": count,
                "moves": executed_moves,
                "errors": errors,
            },
            undo_info={
                "action": "bulk_move",
                "moves": [{"source": m["destination"], "destination": m["source"]} for m in executed_moves],
            },
        )

    def bulk_move(
        self,
        items: List[str],
        destination_folder_name: str,
        conflict_strategy: str = "rename",
    ) -> ToolResult:
        """Moves multiple files or folders to a target destination folder."""
        dest_dir = self.resolve_target(destination_folder_name, is_dir=True)
        if not dest_dir or not dest_dir.is_dir():
            return ToolResult.fail(
                error=f"Destination folder '{destination_folder_name}' could not be located.",
                data={"destination": destination_folder_name},
            )

        moved: List[Dict[str, str]] = []
        errors: List[str] = []

        for item_name in items:
            src = self.resolve_target(item_name)
            if not src or not src.exists():
                errors.append(f"Item '{item_name}' could not be located.")
                continue

            dest_target = dest_dir / src.name
            resolved_dest = self.resolve_conflict_path(dest_target, strategy=conflict_strategy)
            if resolved_dest is None:
                continue

            try:
                shutil.move(str(src), str(resolved_dest))
                self.indexer.remove_item(src)
                self.indexer.record_item(resolved_dest)
                moved.append({"source": str(src.resolve()), "destination": str(resolved_dest.resolve())})
            except Exception as e:
                errors.append(f"Failed to move '{src.name}': {str(e)}")

        return ToolResult.ok(
            message=f"Bulk moved {len(moved)} of {len(items)} items to '{dest_dir.name}'.",
            data={"moved": moved, "errors": errors, "destination": str(dest_dir)},
            undo_info={
                "action": "bulk_move",
                "moves": [{"source": m["destination"], "destination": m["source"]} for m in moved],
            },
        )

    def bulk_copy(
        self,
        items: List[str],
        destination_folder_name: str,
        conflict_strategy: str = "rename",
    ) -> ToolResult:
        """Copies multiple files or folders to a target destination folder."""
        dest_dir = self.resolve_target(destination_folder_name, is_dir=True)
        if not dest_dir or not dest_dir.is_dir():
            return ToolResult.fail(
                error=f"Destination folder '{destination_folder_name}' could not be located.",
                data={"destination": destination_folder_name},
            )

        copied: List[Dict[str, str]] = []
        errors: List[str] = []

        for item_name in items:
            src = self.resolve_target(item_name)
            if not src or not src.exists():
                errors.append(f"Item '{item_name}' could not be located.")
                continue

            dest_target = dest_dir / src.name
            resolved_dest = self.resolve_conflict_path(dest_target, strategy=conflict_strategy)
            if resolved_dest is None:
                continue

            try:
                if src.is_dir():
                    shutil.copytree(str(src), str(resolved_dest))
                else:
                    shutil.copy2(str(src), str(resolved_dest))
                self.indexer.record_item(resolved_dest)
                copied.append({"source": str(src.resolve()), "destination": str(resolved_dest.resolve())})
            except Exception as e:
                errors.append(f"Failed to copy '{src.name}': {str(e)}")

        return ToolResult.ok(
            message=f"Bulk copied {len(copied)} of {len(items)} items to '{dest_dir.name}'.",
            data={"copied": copied, "errors": errors, "destination": str(dest_dir)},
        )

    def find_duplicates(
        self,
        folder_name: Optional[str] = None,
        max_files: int = 1000,
    ) -> ToolResult:
        """
        Scans a folder for duplicate files using size grouping and SHA256 checksum matching.
        """
        target_dir = self.resolve_target(folder_name, is_dir=True) if folder_name else DEFAULT_WORKSPACE
        if not target_dir or not target_dir.exists() or not target_dir.is_dir():
            return ToolResult.fail(
                error=f"Folder '{folder_name}' could not be located to check duplicates.",
                data={"folder_name": folder_name},
            )

        # 1. Group files by size
        size_groups: Dict[int, List[Path]] = defaultdict(list)
        count = 0
        try:
            for root, dirs, files in os.walk(target_dir):
                dirs[:] = [d for d in dirs if d.lower() not in EXCLUDED_DIR_NAMES]
                for f in files:
                    fp = Path(root) / f
                    try:
                        sz = fp.stat().st_size
                        if sz > 0:  # ignore 0-byte empty files
                            size_groups[sz].append(fp)
                            count += 1
                            if count >= max_files:
                                break
                    except (PermissionError, OSError):
                        continue
                if count >= max_files:
                    break
        except Exception as e:
            return ToolResult.fail(error=f"Error scanning for duplicates: {str(e)}")

        # 2. Hash files with identical sizes
        duplicate_groups: List[Dict[str, Any]] = []
        wasted_bytes = 0

        for sz, files in size_groups.items():
            if len(files) < 2:
                continue

            hash_buckets: Dict[str, List[Path]] = defaultdict(list)
            for f in files:
                try:
                    h = hashlib.sha256()
                    with open(f, "rb") as fh:
                        while chunk := fh.read(65536):
                            h.update(chunk)
                    hash_buckets[h.hexdigest()].append(f)
                except (PermissionError, OSError):
                    continue

            for hval, dups in hash_buckets.items():
                if len(dups) > 1:
                    wasted_bytes += sz * (len(dups) - 1)
                    duplicate_groups.append({
                        "hash": hval,
                        "size": sz,
                        "size_formatted": f"{sz / 1024:.1f} KB" if sz < 1048576 else f"{sz / 1048576:.1f} MB",
                        "files": [str(p.resolve()) for p in dups],
                        "count": len(dups),
                    })

        wasted_formatted = (
            f"{wasted_bytes / (1024 * 1024):.2f} MB" if wasted_bytes >= 1048576 else f"{wasted_bytes / 1024:.1f} KB"
        )
        msg = (
            f"Found {len(duplicate_groups)} duplicate group(s) ({wasted_formatted} potentially reclaimable) in '{target_dir.name}'."
            if duplicate_groups else f"No duplicate files found in '{target_dir.name}'."
        )

        return ToolResult.ok(
            message=msg,
            data={
                "folder": str(target_dir),
                "duplicate_groups": duplicate_groups,
                "group_count": len(duplicate_groups),
                "wasted_bytes": wasted_bytes,
                "wasted_formatted": wasted_formatted,
            },
        )

    def open_path(self, target_path: Path) -> Dict[str, Any]:
        """Opens a specific resolved file or folder path directly."""
        if not target_path or not target_path.exists():
            return ToolResult.fail(
                error=f"Item at '{target_path}' does not exist.",
                data={"path": str(target_path) if target_path else ""},
            )

        try:
            os.startfile(str(target_path.resolve()))
            item_type = "folder" if target_path.is_dir() else "file"
            return ToolResult.ok(
                message=f"Opened {item_type} '{target_path.name}'.",
                data={
                    "name": target_path.name,
                    "path": str(target_path.resolve()),
                    "type": item_type,
                },
            )
        except Exception as e:
            return ToolResult.fail(
                error=f"Failed to open '{target_path}': {str(e)}",
                data={"path": str(target_path) if target_path else ""},
            )

    def open_item(
        self,
        name: str,
        app: Optional[str] = None,
        app_manager=None,
    ) -> Dict[str, Any]:
        """
        Finds any file or folder and opens it with the default Windows application,
        with a specified application, or in File Explorer. Detects and reports ambiguous
        matches cleanly.
        """
        clean_name = name.strip().strip("'\" ")
        if not clean_name:
            return ToolResult.fail(error="No item name specified to open.")

        # 1. If explicit app provided and app_manager passed
        if app and app_manager:
            target_path = self.resolve_target(clean_name)
            if target_path and target_path.exists():
                return app_manager.open_application(app, path=target_path)
            candidates = self.find_open_candidates(clean_name)
            if len(candidates) > 1:
                return ToolResult.fail(
                    error=f"Multiple items found matching '{clean_name}'. Please specify exact path.",
                    data={"candidates": [str(c) for c in candidates], "ambiguous": True},
                )
            elif len(candidates) == 1:
                return app_manager.open_application(app, path=candidates[0])
            else:
                return ToolResult.fail(
                    error=f"Item '{clean_name}' could not be found to open with '{app}'.",
                    data={"name": clean_name, "app": app},
                )

        # 2. Check for ambiguous candidates across filesystem
        candidates = self.find_open_candidates(clean_name)
        if len(candidates) > 1:
            # Check if there is an exact case-insensitive match on name
            exact = [c for c in candidates if c.name.lower() == clean_name.lower()]
            if len(exact) == 1:
                return self.open_path(exact[0])
            elif len(exact) > 1:
                cand_paths = [str(c) for c in exact]
                return ToolResult.fail(
                    error=f"Multiple items found matching '{clean_name}'. Please specify which one to open.",
                    data={"candidates": cand_paths, "ambiguous": True},
                )
            else:
                cand_paths = [str(c) for c in candidates]
                return ToolResult.fail(
                    error=f"Multiple items found matching '{clean_name}'. Please specify which one to open.",
                    data={"candidates": cand_paths, "ambiguous": True},
                )
        elif len(candidates) == 1:
            return self.open_path(candidates[0])

        # 3. Fallback to resolve_target
        target_path = self.resolve_target(clean_name)
        if not target_path or not target_path.exists():
            return ToolResult.fail(
                error=f"Item '{clean_name}' could not be found to open.",
                data={"name": clean_name},
            )

        return self.open_path(target_path)

    def find_advanced(
        self,
        query: Optional[str] = None,
        kind: str = "any",
        extension: Optional[Union[str, List[str]]] = None,
        directory: Optional[Union[str, Path]] = None,
        modified_within_days: Optional[float] = None,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
        limit: int = 50,
        sort_by: str = "relevance",
    ) -> List[Dict[str, Any]]:
        """
        Advanced search supporting query string, kind, extension categories/lists,
        directory constraints, modification recency, file size, and relevance ranking.
        """
        is_dir = None
        if kind.lower() in ("folder", "dir", "directory"):
            is_dir = True
        elif kind.lower() in ("file",):
            is_dir = False

        resolved_dir: Optional[Path] = None
        if directory:
            str_dir = str(directory).strip()
            # Try to resolve target directory
            target_p = self.resolve_target(str_dir, is_dir=True)
            if target_p and target_p.is_dir():
                resolved_dir = target_p
                # Fast index the directory's immediate files to ensure freshness
                try:
                    for child in list(resolved_dir.iterdir())[:300]:
                        if child.name.lower() not in EXCLUDED_DIR_NAMES:
                            self.indexer.record_item(child)
                except Exception:
                    pass

        # Search indexer
        indexed_items = self.indexer.search_advanced(
            query=query,
            is_dir=is_dir,
            extension=extension,
            directory=resolved_dir or directory,
            modified_within_days=modified_within_days,
            min_size=min_size,
            max_size=max_size,
            limit=limit,
            sort_by=sort_by,
        )

        results = [item.to_dict() for item in indexed_items]

        # If zero results and query is provided and no complex filters, do priority roots check
        if len(results) == 0 and query and not (extension or modified_within_days or min_size):
            return self._fallback_priority_roots_search(query, is_dir=is_dir, limit=limit)

        return results

    def find_items(
        self,
        query: str,
        kind: str = "any",
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """
        Finds all files or folders matching the query present in File Explorer (all drives).
        kind can be 'any', 'file', or 'folder'.
        """
        return self.find_advanced(
            query=query,
            kind=kind,
            limit=limit,
            sort_by="relevance",
        )

    def _fallback_priority_roots_search(
        self,
        query: str,
        is_dir: Optional[bool] = None,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """Deep search across priority roots and available drives if index has no records."""
        query_clean = query.strip().lower()
        results: List[Dict[str, Any]] = []
        seen_paths = set()

        for root in PRIORITY_SEARCH_ROOTS:
            if not root.exists():
                continue
            try:
                for child in root.iterdir():
                    if child.name.lower() in EXCLUDED_DIR_NAMES:
                        continue
                    if query_clean in child.name.lower():
                        str_p = str(child.resolve())
                        if str_p not in seen_paths:
                            item_dir = child.is_dir()
                            if is_dir is None or item_dir == is_dir:
                                seen_paths.add(str_p)
                                stat = child.stat()
                                item_dict = {
                                    "name": child.name,
                                    "path": str_p,
                                    "is_dir": item_dir,
                                    "type": "folder" if item_dir else "file",
                                    "extension": child.suffix.lower() if not item_dir else "",
                                    "size": stat.st_size if not item_dir else 0,
                                    "mtime": stat.st_mtime,
                                    "parent_name": child.parent.name,
                                }
                                results.append(item_dict)
                                self.indexer.record_item(child)

                    if child.is_dir():
                        try:
                            for sub in child.iterdir():
                                if query_clean in sub.name.lower():
                                    str_sub = str(sub.resolve())
                                    if str_sub not in seen_paths:
                                        item_dir = sub.is_dir()
                                        if is_dir is None or item_dir == is_dir:
                                            seen_paths.add(str_sub)
                                            stat = sub.stat()
                                            item_dict = {
                                                "name": sub.name,
                                                "path": str_sub,
                                                "is_dir": item_dir,
                                                "type": "folder" if item_dir else "file",
                                                "extension": sub.suffix.lower() if not item_dir else "",
                                                "size": stat.st_size if not item_dir else 0,
                                                "mtime": stat.st_mtime,
                                                "parent_name": sub.parent.name,
                                            }
                                            results.append(item_dict)
                                            self.indexer.record_item(sub)
                        except (PermissionError, OSError):
                            continue
            except (PermissionError, OSError):
                continue

            if len(results) >= limit:
                break

        # Drive scan across available drives if still empty
        if len(results) == 0:
            for drv in list(AVAILABLE_DRIVES):
                if not drv.exists():
                    continue
                try:
                    for root, dirs, files in os.walk(drv):
                        dirs[:] = [
                            d for d in dirs
                            if d.lower() not in EXCLUDED_DIR_NAMES
                            and not any(exc in os.path.join(root, d).lower() for exc in EXCLUDED_DIR_NAMES)
                        ]
                        root_path = Path(root)
                        try:
                            rel_parts = root_path.relative_to(drv).parts
                            if len(rel_parts) >= 4:
                                dirs.clear()
                        except ValueError:
                            pass

                        if is_dir in (True, None):
                            for d in dirs:
                                if query_clean in d.lower():
                                    d_path = root_path / d
                                    str_d = str(d_path.resolve())
                                    if str_d not in seen_paths:
                                        seen_paths.add(str_d)
                                        try:
                                            stat = d_path.stat()
                                            item_dict = {
                                                "name": d,
                                                "path": str_d,
                                                "is_dir": True,
                                                "type": "folder",
                                                "extension": "",
                                                "size": 0,
                                                "mtime": stat.st_mtime,
                                                "parent_name": root_path.name,
                                            }
                                            results.append(item_dict)
                                            self.indexer.record_item(d_path)
                                        except (PermissionError, OSError):
                                            continue

                        if is_dir in (False, None):
                            for f in files:
                                if query_clean in f.lower():
                                    f_path = root_path / f
                                    str_f = str(f_path.resolve())
                                    if str_f not in seen_paths:
                                        seen_paths.add(str_f)
                                        try:
                                            stat = f_path.stat()
                                            item_dict = {
                                                "name": f,
                                                "path": str_f,
                                                "is_dir": False,
                                                "type": "file",
                                                "extension": f_path.suffix.lower(),
                                                "size": stat.st_size,
                                                "mtime": stat.st_mtime,
                                                "parent_name": root_path.name,
                                            }
                                            results.append(item_dict)
                                            self.indexer.record_item(f_path)
                                        except (PermissionError, OSError):
                                            continue

                        if len(results) >= limit:
                            break
                except (PermissionError, OSError):
                    continue
                if len(results) >= limit:
                    break

        results.sort(
            key=lambda x: (
                0 if x["name"].lower() == query_clean else (1 if x["name"].lower().startswith(query_clean) else 2),
                -x.get("mtime", 0),
            )
        )
        return results[:limit]
