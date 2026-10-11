"""
Nova Assistant Configuration
Stores path configurations, default directories, search exclusion rules,
and system constants.
"""

from pathlib import Path
import os
import sys

# Nova Data Directory for indices and logs
NOVA_DATA_DIR = Path.home() / ".nova"
NOVA_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Database path for indexed files, folders, and applications
INDEX_DB_PATH = NOVA_DATA_DIR / "nova_index.db"

# Database paths for Phase 3 persistent user memory and action audit logs
MEMORY_DB_PATH = NOVA_DATA_DIR / "nova_memory.db"
ACTION_HISTORY_DB_PATH = NOVA_DATA_DIR / "nova_history.db"

# Database paths for Phase 4 productivity tools (notes, reminders, schedules)
NOTES_DB_PATH = NOVA_DATA_DIR / "nova_notes.db"
REMINDERS_DB_PATH = NOVA_DATA_DIR / "nova_reminders.db"
SCHEDULES_DB_PATH = NOVA_DATA_DIR / "nova_schedules.db"

# High-priority user directories for instant search and zero-path resolution
USER_HOME = Path.home()
USER_DESKTOP = USER_HOME / "Desktop"
USER_DOCUMENTS = USER_HOME / "Documents"
USER_DOWNLOADS = USER_HOME / "Downloads"
USER_PICTURES = USER_HOME / "Pictures"
USER_VIDEOS = USER_HOME / "Videos"
USER_MUSIC = USER_HOME / "Music"

def get_available_drives():
    """Dynamically returns all existing logical drive roots (e.g. C:/, D:/)."""
    drives = []
    try:
        import ctypes, string
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if (bitmask >> (ord(letter) - 65)) & 1:
                p = Path(f"{letter}:/")
                if p.exists():
                    drives.append(p)
    except Exception:
        for letter in ["C", "D", "E", "F", "G"]:
            p = Path(f"{letter}:/")
            if p.exists():
                drives.append(p)
    return drives

AVAILABLE_DRIVES = get_available_drives()

# Default directory where files/folders are created if no specific folder is specified (D: drive)
D_DRIVE = Path("D:/")
DEFAULT_WORKSPACE = D_DRIVE if D_DRIVE.exists() else (USER_DOCUMENTS / "Nova_Workspace")
if not DEFAULT_WORKSPACE.exists():
    try:
        DEFAULT_WORKSPACE.mkdir(parents=True, exist_ok=True)
    except Exception:
        DEFAULT_WORKSPACE = USER_HOME

# Priority search roots (searched first before full system crawl)
PRIORITY_SEARCH_ROOTS = [
    DEFAULT_WORKSPACE,
    Path("D:/Nova"),
    USER_DESKTOP,
    USER_DOWNLOADS,
    USER_DOCUMENTS,
    USER_PICTURES,
    USER_VIDEOS,
    USER_MUSIC,
    USER_HOME,
]
# Add any other available drives to priority search
for drv in AVAILABLE_DRIVES:
    if drv not in PRIORITY_SEARCH_ROOTS:
        PRIORITY_SEARCH_ROOTS.append(drv)

# System directories to exclude from deep filesystem search for speed and safety
EXCLUDED_DIR_NAMES = {
    "$recycle.bin",
    "system volume information",
    "recovery",
    "winsxs",
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "appdata\\local\\temp",
    "windows\\installer",
}

# Start Menu locations
START_MENU_SYSTEM = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs"
START_MENU_USER = Path(os.environ.get("APPDATA", str(USER_HOME / "AppData/Roaming"))) / r"Microsoft\Windows\Start Menu\Programs"

# Architecture Languages Chart (Saved in memory as requested by user)
LANGUAGE_CHART = {
    "Main AI / Agent Brain": "Python",
    "LLM Integration": "Python",
    "Speech-to-Text (STT)": "Python",
    "Text-to-Speech (TTS)": "Python",
    "Wake Word Detection": "Python + C++ engine if needed",
    "Real-Time Audio Processing": "C++",
    "Memory System": "Python",
    "RAG / Document Search": "Python",
    "Tool/Function Calling": "Python",
    "Windows OS Automation": "Python",
    "Linux System Control": "Python + Bash",
    "Low-Level OS Operations": "C++",
    "Hardware / ESP32 / IoT": "C/C++",
    "Backend Server": "Python (FastAPI)",
    "Real-Time Communication": "Python + WebSocket",
    "JARVIS Desktop UI": "TypeScript + React",
    "JARVIS HUD / Animations": "TypeScript + React + CSS/WebGL",
    "Web Dashboard": "TypeScript + React",
    "Mobile App": "TypeScript + React Native",
    "Database": "SQL",
    "Vector Database": "Python + Qdrant/FAISS/etc.",
    "Data/Analytics": "Python",
    "Authentication/Security": "Python/TypeScript",
    "Performance-Critical Algorithms": "C++",
    "Testing / Automation": "Python",
}
