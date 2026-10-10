"""
Nova File Manager
Implements zero-path file and folder operations:
create, delete, rename, move, copy, open, and find across all drives in File Explorer.
"""

import os
import re
import shutil
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

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


class FileManager:
    """Provides smart zero-path file and directory operations for Nova."""

    def __init__(self, indexer: Optional[Indexer] = None):
        self.indexer = indexer or Indexer()

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
        target_parent = DEFAULT_WORKSPACE
        resolved_parent_msg = f"D: drive ({DEFAULT_WORKSPACE})" if str(DEFAULT_WORKSPACE).startswith("D:") else "default workspace"

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
        target_parent = DEFAULT_WORKSPACE
        resolved_parent_msg = f"D: drive ({DEFAULT_WORKSPACE})" if str(DEFAULT_WORKSPACE).startswith("D:") else "default workspace"

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

    def open_item(self, name: str) -> Dict[str, Any]:
        """
        Finds any file or folder and opens it with the default Windows application
        or in File Explorer.
        """
        target_path = self.resolve_target(name)
        if not target_path or not target_path.exists():
            return ToolResult.fail(
                error=f"Item '{name}' could not be found to open.",
                data={"name": name},
            )

        return self.open_path(target_path)

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
        is_dir = None
        if kind.lower() in ("folder", "dir", "directory"):
            is_dir = True
        elif kind.lower() in ("file",):
            is_dir = False

        query_clean = query.strip().lower()
        results: List[Dict[str, Any]] = []
        seen_paths = set()

        # 1. Search SQLite index
        indexed_matches = self.indexer.search(query=query_clean, is_dir=is_dir, limit=limit)
        for item in indexed_matches:
            p = Path(item.path)
            if p.exists() and str(p) not in seen_paths:
                seen_paths.add(str(p))
                results.append(item.to_dict())

        # 2. Priority roots search (depth 1..3)
        for root in PRIORITY_SEARCH_ROOTS:
            if not root.exists():
                continue
            try:
                # Direct check children
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

                    # Subdirectory shallow check
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

        # 3. Comprehensive drive scan across all drives if nothing found in index/priority roots
        if len(results) == 0:
            search_drives = list(AVAILABLE_DRIVES)
            for drv in search_drives:
                if not drv.exists():
                    continue
                try:
                    for root, dirs, files in os.walk(drv):
                        # Prune system and heavy directories
                        dirs[:] = [
                            d for d in dirs
                            if d.lower() not in EXCLUDED_DIR_NAMES
                            and not any(exc in os.path.join(root, d).lower() for exc in EXCLUDED_DIR_NAMES)
                        ]

                        root_path = Path(root)

                        # Limit depth from drive root for speed
                        try:
                            rel_parts = root_path.relative_to(drv).parts
                            if len(rel_parts) >= 4:
                                dirs.clear()
                        except ValueError:
                            pass

                        # Match folders
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

                        # Match files
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

        # Sort exact match first, then starts-with, then recent mtime
        results.sort(
            key=lambda x: (
                0 if x["name"].lower() == query_clean else (1 if x["name"].lower().startswith(query_clean) else 2),
                -x.get("mtime", 0),
            )
        )
        return results[:limit]
