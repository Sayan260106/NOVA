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
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from nova.config import START_MENU_SYSTEM, START_MENU_USER
from nova.core.results import ToolResult

logger = logging.getLogger("nova.app_manager")

# Common aliases for quick resolution
APP_ALIASES = {
    "calc": "Calculator",
    "calculator": "Calculator",
    "notes": "Notepad",
    "notepad": "Notepad",
    "terminal": "Windows Terminal",
    "cmd": "Command Prompt",
    "powershell": "Windows PowerShell",
    "pwsh": "PowerShell",
    "code": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "edge": "Microsoft Edge",
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

    def __init__(self):
        self._apps: Dict[str, ApplicationInfo] = {}
        self._initialized = False
        self._spawned_processes: List[subprocess.Popen] = []

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
        """Register essential Windows utilities."""
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
            if key not in apps_dict:
                apps_dict[key] = ApplicationInfo(
                    name=display_name,
                    path=target,
                    source="builtin",
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

        # Check aliases first
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

    def open_application(self, query: str) -> Dict[str, Any]:
        """
        Find and launch an application by name or alias.
        Returns a dictionary with execution status and details.
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

        try:
            detach_flag = getattr(subprocess, "DETACHED_PROCESS", 0)
            # Launch based on source type
            if best_app.app_id:
                # Launch via shell:AppsFolder
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
                    # URI protocol like ms-settings:
                    os.startfile(target)
                elif target.endswith(".lnk"):
                    os.startfile(target)
                else:
                    # Executable
                    proc = subprocess.Popen(
                        target,
                        shell=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=detach_flag,
                    )
                    self._spawned_processes.append(proc)
                return ToolResult.ok(
                    message=f"Launched '{best_app.name}' from {target}",
                    data={
                        "app_name": best_app.name,
                        "target": target,
                        "source": best_app.source,
                        "confidence": score,
                    },
                )
            else:
                # Direct startfile
                os.startfile(best_app.name)
                return ToolResult.ok(
                    message=f"Launched '{best_app.name}'",
                    data={
                        "app_name": best_app.name,
                        "target": best_app.name,
                        "confidence": score,
                    },
                )

        except Exception as e:
            return ToolResult.fail(
                error=f"Failed to launch '{best_app.name}': {str(e)}",
                data={"app_name": best_app.name},
            )
