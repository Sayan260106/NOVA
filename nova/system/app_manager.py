"""
Nova Application Manager
Handles application discovery, fuzzy searching, and launching for all
Windows desktop, Start Menu, Registry, PATH, and UWP / Store applications.
"""

import os
import sys
import json
import logging
import winreg
import difflib
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union

from nova.config import START_MENU_SYSTEM, START_MENU_USER, USER_HOME, DEFAULT_WORKSPACE
from nova.core.results import ToolResult

logger = logging.getLogger("nova.app_manager")

# Common aliases for quick resolution
APP_ALIASES = {
    "calc": "Calculator",
    "calculator": "Calculator",
    "notes": "Notepad",
    "notepad": "Notepad",
    "terminal": "Windows Terminal",
    "wt": "Windows Terminal",
    "windows terminal": "Windows Terminal",
    "cmd": "Command Prompt",
    "command prompt": "Command Prompt",
    "powershell": "Windows PowerShell",
    "pwsh": "PowerShell",
    "code": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "vsc": "Visual Studio Code",
    "visual studio code": "Visual Studio Code",
    "pycharm": "PyCharm",
    "sublime": "Sublime Text",
    "sublime text": "Sublime Text",
    "notepad++": "Notepad++",
    "npp": "Notepad++",
    "git bash": "Git Bash",
    "bash": "Git Bash",
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "edge": "Microsoft Edge",
    "ms edge": "Microsoft Edge",
    "word": "Word",
    "ms word": "Word",
    "excel": "Excel",
    "ms excel": "Excel",
    "powerpoint": "PowerPoint",
    "ppt": "PowerPoint",
    "paint": "Paint",
    "mspaint": "Paint",
    "settings": "Settings",
    "control panel": "Control Panel",
    "explorer": "File Explorer",
    "files": "File Explorer",
    "file explorer": "File Explorer",
    "task manager": "Task Manager",
    "taskmgr": "Task Manager",
    "spotify": "Spotify",
    "discord": "Discord",
    "steam": "Steam",
    "studio": "Android Studio",
    "android studio": "Android Studio",
}


class ApplicationInfo:
    def __init__(
        self,
        name: str,
        app_id: Optional[str] = None,
        path: Optional[str] = None,
        source: str = "unknown",
        description: str = "",
    ):
        self.name = name
        self.app_id = app_id
        self.path = path
        self.source = source  # 'uwp', 'start_menu', 'registry', 'path', 'builtin'
        self.description = description

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "app_id": self.app_id,
            "path": self.path,
            "source": self.source,
            "description": self.description,
        }

    def __repr__(self) -> str:
        return f"<App: {self.name} ({self.source})>"


class AppManager:
    """Discovers, indexes, finds, and launches applications on Windows."""

    def __init__(self, memory: Optional[Any] = None):
        self._apps: Dict[str, ApplicationInfo] = {}
        self._initialized = False
        self._spawned_processes: List[subprocess.Popen] = []
        self.memory = memory

    def initialize(self, force_refresh: bool = False) -> None:
        """Scan system to discover all installed applications."""
        if self._initialized and not force_refresh:
            return

        apps_dict: Dict[str, ApplicationInfo] = {}

        # 1. Discover UWP and StartApps via PowerShell Get-StartApps
        self._load_start_apps(apps_dict)

        # 2. Discover Start Menu shortcuts (.lnk files)
        self._load_start_menu_shortcuts(apps_dict)

        # 3. Discover Registry App Paths
        self._load_registry_apps(apps_dict)

        # 4. Discover Standard Builtin Tools in PATH / Windows
        self._load_builtin_tools(apps_dict)

        self._apps = apps_dict
        self._initialized = True
        logger.info(f"AppManager initialized with {len(self._apps)} applications.")

    def _load_start_apps(self, apps_dict: Dict[str, ApplicationInfo]) -> None:
        """Query Windows Get-StartApps to find Modern and Desktop apps."""
        try:
            ps_script = (
                "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
                "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=12,
            )
            if res.returncode == 0 and res.stdout.strip():
                try:
                    data = json.loads(res.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    for item in data:
                        name = item.get("Name", "").strip()
                        app_id = item.get("AppID", "").strip()
                        if name and app_id:
                            apps_dict[name.lower()] = ApplicationInfo(
                                name=name,
                                app_id=app_id,
                                source="uwp" if ("!" in app_id or "_" in app_id) else "start_apps",
                            )
                except Exception as e:
                    logger.warning(f"Error parsing Get-StartApps JSON: {e}")
        except Exception as e:
            logger.warning(f"Could not load Get-StartApps: {e}")

    def _load_start_menu_shortcuts(self, apps_dict: Dict[str, ApplicationInfo]) -> None:
        """Scan system and user Start Menu directories for .lnk files."""
        for root_dir in [START_MENU_SYSTEM, START_MENU_USER]:
            if not root_dir.exists():
                continue
            try:
                for lnk_file in root_dir.rglob("*.lnk"):
                    app_name = lnk_file.stem
                    lower_name = app_name.lower()
                    # Skip uninstaller shortcuts
                    if "uninstall" in lower_name:
                        continue
                    if lower_name not in apps_dict:
                        apps_dict[lower_name] = ApplicationInfo(
                            name=app_name,
                            path=str(lnk_file),
                            source="start_menu",
                        )
            except Exception as e:
                logger.warning(f"Error scanning start menu {root_dir}: {e}")

    def _load_registry_apps(self, apps_dict: Dict[str, ApplicationInfo]) -> None:
        """Scan Windows Registry App Paths for registered executable apps."""
        reg_keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        ]

        for hkey, subkey in reg_keys:
            try:
                with winreg.OpenKey(hkey, subkey) as key:
                    num_subkeys = winreg.QueryInfoKey(key)[0]
                    for i in range(num_subkeys):
                        try:
                            app_key_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, app_key_name) as app_key:
                                try:
                                    app_path, _ = winreg.QueryValueEx(app_key, "")
                                    if app_path and os.path.exists(app_path):
                                        clean_name = Path(app_key_name).stem
                                        lower_name = clean_name.lower()
                                        if lower_name not in apps_dict:
                                            apps_dict[lower_name] = ApplicationInfo(
                                                name=clean_name,
                                                path=app_path,
                                                source="registry",
                                            )
                                except OSError:
                                    pass
                        except OSError:
                            continue
            except OSError:
                continue

    def _load_builtin_tools(self, apps_dict: Dict[str, ApplicationInfo]) -> None:
        """Register essential Windows utilities and developer tools."""
        builtins = {
            "notepad": ("Notepad", "notepad.exe"),
            "calculator": ("Calculator", "calc.exe"),
            "paint": ("Paint", "mspaint.exe"),
            "command prompt": ("Command Prompt", "cmd.exe"),
            "powershell": ("PowerShell", "powershell.exe"),
            "file explorer": ("File Explorer", "explorer.exe"),
            "task manager": ("Task Manager", "taskmgr.exe"),
            "control panel": ("Control Panel", "control.exe"),
            "settings": ("Settings", "ms-settings:"),
        }
        for key, (display_name, target) in builtins.items():
            if key in apps_dict:
                apps_dict[key].path = target
            else:
                apps_dict[key] = ApplicationInfo(
                    name=display_name,
                    path=target,
                    source="builtin",
                )

        # Developer tools & editors from PATH or common LocalAppData locations
        dev_tools = {
            "visual studio code": ("Visual Studio Code", ["code.cmd", "code.exe", "code"]),
            "vscode": ("Visual Studio Code", ["code.cmd", "code.exe", "code"]),
            "code": ("Visual Studio Code", ["code.cmd", "code.exe", "code"]),
            "sublime text": ("Sublime Text", ["subl.exe", "sublime_text.exe"]),
            "notepad++": ("Notepad++", ["notepad++.exe"]),
            "pycharm": ("PyCharm", ["pycharm64.exe", "pycharm.exe"]),
            "windows terminal": ("Windows Terminal", ["wt.exe"]),
            "git bash": ("Git Bash", ["git-bash.exe"]),
        }

        # Check common local app data directory for VS Code
        local_app_data = os.environ.get("LOCALAPPDATA")
        vscode_candidates = []
        if local_app_data:
            vscode_candidates.extend([
                Path(local_app_data) / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd",
                Path(local_app_data) / "Programs" / "Microsoft VS Code" / "Code.exe",
            ])

        for key, (display_name, exes) in dev_tools.items():
            resolved_path = None
            for exe in exes:
                found = shutil.which(exe)
                if found:
                    resolved_path = found
                    break
            if not resolved_path and "code" in key:
                for v_path in vscode_candidates:
                    if v_path.exists():
                        resolved_path = str(v_path)
                        break
            if resolved_path:
                if key in apps_dict:
                    apps_dict[key].path = resolved_path
                else:
                    apps_dict[key] = ApplicationInfo(
                        name=display_name,
                        path=resolved_path,
                        source="path",
                    )

    def list_applications(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return list of all registered applications."""
        if not self._initialized:
            self.initialize()
        apps = [app.to_dict() for app in self._apps.values()]
        apps.sort(key=lambda x: x["name"].lower())
        return apps[:limit] if limit else apps

    def find_applications(self, query: str, limit: int = 10) -> List[Tuple[ApplicationInfo, float]]:
        """
        Search for applications matching query with confidence scoring.
        Returns a list of (ApplicationInfo, score) sorted by score descending.
        """
        if not self._initialized:
            self.initialize()

        query_clean = query.strip().lower()
        if not query_clean:
            return []

        # Check aliases first (persistent memory aliases take precedence over static aliases)
        resolved_name = None
        if self.memory:
            try:
                resolved_name = self.memory.get_app_alias(query_clean)
            except Exception:
                pass
        if not resolved_name:
            resolved_name = APP_ALIASES.get(query_clean, query_clean)

        results: List[Tuple[ApplicationInfo, float]] = []

        for key, app in self._apps.items():
            app_lower = app.name.lower()
            score = 0.0

            # 1. Exact match on alias or key or app name
            if query_clean == key or query_clean == app_lower or resolved_name.lower() == app_lower:
                score = 1.0
            # 2. Prefix match
            elif app_lower.startswith(query_clean) or app_lower.startswith(resolved_name.lower()):
                score = 0.85
            # 3. Substring match
            elif query_clean in app_lower or resolved_name.lower() in app_lower:
                score = 0.75
            # 4. Fuzzy sequence matcher (require high similarity)
            else:
                ratio = difflib.SequenceMatcher(None, query_clean, app_lower).ratio()
                alias_ratio = difflib.SequenceMatcher(None, resolved_name.lower(), app_lower).ratio()
                best_ratio = max(ratio, alias_ratio)
                if best_ratio >= 0.75:
                    score = best_ratio * 0.75

            if score >= 0.65:
                results.append((app, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def open_application(
        self,
        query: str,
        path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """
        Find and launch an application by name or alias, optionally passing a file or directory path.
        Returns a ToolResult dictionary with execution status and details.
        """
        if not self._initialized:
            self.initialize()

        matches = self.find_applications(query, limit=5)
        if not matches or matches[0][1] < 0.65:
            return ToolResult.fail(
                error=f"Application '{query}' not found.",
                data={"app_name": query},
            )

        best_app, score = matches[0]

        target_path_resolved: Optional[Path] = None
        if path:
            target_path_resolved = Path(path).resolve()
            if not target_path_resolved.exists():
                return ToolResult.fail(
                    error=f"Target path '{path}' does not exist.",
                    data={"app_name": best_app.name, "path": str(path)},
                )

        try:
            detach_flag = getattr(subprocess, "DETACHED_PROCESS", 0)
            target_str = str(target_path_resolved) if target_path_resolved else None

            # Launch based on source type
            if best_app.app_id:
                if target_str:
                    if best_app.name.lower() in ("file explorer", "explorer"):
                        # Launch explorer on target path
                        proc = subprocess.Popen(
                            ["explorer.exe", target_str],
                            shell=False,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=detach_flag,
                        )
                        self._spawned_processes.append(proc)
                        return ToolResult.ok(
                            message=f"Opened '{target_path_resolved.name}' in File Explorer",
                            data={"app_name": best_app.name, "target": target_str, "confidence": score},
                        )
                    else:
                        exe = shutil.which(best_app.name) or shutil.which(f"{best_app.name}.exe")
                        if not exe and best_app.path:
                            exe = best_app.path
                        if exe:
                            proc = subprocess.Popen(
                                [exe, target_str],
                                shell=exe.lower().endswith((".cmd", ".bat")),
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                creationflags=detach_flag,
                            )
                            self._spawned_processes.append(proc)
                            return ToolResult.ok(
                                message=f"Launched '{best_app.name}' with '{target_path_resolved.name}'",
                                data={"app_name": best_app.name, "target": target_str, "confidence": score},
                            )
                        else:
                            os.startfile(target_str)
                            return ToolResult.ok(
                                message=f"Opened '{target_path_resolved.name}' with '{best_app.name}'",
                                data={"app_name": best_app.name, "target": target_str, "confidence": score},
                            )
                else:
                    target = f"shell:AppsFolder\\{best_app.app_id}"
                    proc = subprocess.Popen(
                        ["explorer.exe", target],
                        shell=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=detach_flag,
                    )
                    self._spawned_processes.append(proc)
                    return ToolResult.ok(
                        message=f"Launched '{best_app.name}' (AppID: {best_app.app_id})",
                        data={
                            "app_name": best_app.name,
                            "target": target,
                            "source": best_app.source,
                            "confidence": score,
                        },
                    )

            elif best_app.path:
                target = best_app.path
                if target.startswith("ms-"):
                    os.startfile(target)
                elif target.endswith(".lnk"):
                    if target_str:
                        os.startfile(target_str)
                    else:
                        os.startfile(target)
                elif "explorer.exe" in target.lower():
                    cmd = ["explorer.exe", target_str] if target_str else ["explorer.exe"]
                    proc = subprocess.Popen(
                        cmd,
                        shell=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=detach_flag,
                    )
                    self._spawned_processes.append(proc)
                else:
                    cmd = [target]
                    if target_str:
                        cmd.append(target_str)
                    is_batch = target.lower().endswith((".cmd", ".bat"))
                    proc = subprocess.Popen(
                        cmd,
                        shell=is_batch,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=detach_flag,
                    )
                    self._spawned_processes.append(proc)

                msg = (
                    f"Launched '{best_app.name}' with '{target_path_resolved.name}'"
                    if target_path_resolved
                    else f"Launched '{best_app.name}' from {target}"
                )
                return ToolResult.ok(
                    message=msg,
                    data={
                        "app_name": best_app.name,
                        "target": target,
                        "path": target_str,
                        "source": best_app.source,
                        "confidence": score,
                    },
                )
            else:
                # Direct startfile
                if target_str:
                    os.startfile(target_str)
                else:
                    os.startfile(best_app.name)
                return ToolResult.ok(
                    message=f"Launched '{best_app.name}'" + (f" with '{target_path_resolved.name}'" if target_path_resolved else ""),
                    data={
                        "app_name": best_app.name,
                        "target": best_app.name,
                        "path": target_str,
                        "confidence": score,
                    },
                )

        except Exception as e:
            return ToolResult.fail(
                error=f"Failed to launch '{best_app.name}': {str(e)}",
                data={"app_name": best_app.name, "path": str(path) if path else None},
            )

    def resolve_project_path(
        self,
        project_name: str,
        file_manager=None,
        memory=None,
    ) -> Optional[Path]:
        """
        Resolves project directory location from project name, workspace, or filesystem.
        """
        clean_name = project_name.strip().strip("'\" ")
        if not clean_name:
            return None

        # 0. Check persistent memory first
        mem = memory or self.memory
        if mem:
            try:
                candidates = [clean_name]
                lower_name = clean_name.lower()
                if lower_name.startswith("my "):
                    candidates.append(clean_name[3:].strip())
                if lower_name.endswith(" project"):
                    candidates.append(clean_name[:-8].strip())
                if lower_name.startswith("my ") and lower_name.endswith(" project"):
                    candidates.append(clean_name[3:-8].strip())

                for c in candidates:
                    stored_loc = mem.get_project_location(c)
                    if stored_loc:
                        p_mem = Path(stored_loc)
                        if p_mem.is_dir():
                            return p_mem.resolve()

                for c in candidates:
                    stored_dir = mem.get_common_directory(c)
                    if stored_dir:
                        p_dir = Path(stored_dir)
                        if p_dir.is_dir():
                            return p_dir.resolve()
            except Exception as e:
                logger.debug(f"Memory lookup notice during project resolution: {e}")

        # 1. Direct path check
        p_direct = Path(clean_name)
        if p_direct.is_dir():
            return p_direct.resolve()

        lower_proj = clean_name.lower()

        # 2. Match current working directory / workspace
        cwd = Path.cwd().resolve()
        if lower_proj in ("this", "current", "here", "workspace", cwd.name.lower()):
            return cwd
        if (cwd / clean_name).is_dir():
            return (cwd / clean_name).resolve()

        # Check DEFAULT_WORKSPACE (e.g. D:\)
        if DEFAULT_WORKSPACE.exists():
            if DEFAULT_WORKSPACE.name.lower() == lower_proj:
                return DEFAULT_WORKSPACE.resolve()
            if (DEFAULT_WORKSPACE / clean_name).is_dir():
                return (DEFAULT_WORKSPACE / clean_name).resolve()

        # 3. Known project locations
        dev_locations = [
            USER_HOME / "Projects" / clean_name,
            USER_HOME / "source" / "repos" / clean_name,
            USER_HOME / "Documents" / clean_name,
            USER_HOME / "Desktop" / clean_name,
            Path("D:/Nova"),
            Path("C:/Nova"),
            Path("D:/") / clean_name,
            Path("C:/") / clean_name,
        ]
        for candidate in dev_locations:
            if candidate.exists() and candidate.is_dir() and candidate.name.lower() == lower_proj:
                return candidate.resolve()

        # 4. Use file_manager if available
        if file_manager:
            found = file_manager.resolve_target(clean_name, is_dir=True)
            if found and found.is_dir():
                return found.resolve()

        return None

    def open_file_with_app(
        self,
        file_path: Union[str, Path],
        app_name: str,
    ) -> Dict[str, Any]:
        """Opens a file or directory with a specific designated application."""
        return self.open_application(app_name, path=file_path)
