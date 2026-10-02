"""
Nova Intent Parser
Parses natural language and structured user utterances into actionable intents
and parameters for Nova's brain.
"""

import re
from typing import Dict, Any, Optional


class NovaIntent:
    # Intent Constants
    OPEN_APP = "OPEN_APP"
    CREATE_FOLDER = "CREATE_FOLDER"
    CREATE_FILE = "CREATE_FILE"
    RENAME_ITEM = "RENAME_ITEM"
    DELETE_ITEM = "DELETE_ITEM"
    COPY_ITEM = "COPY_ITEM"
    MOVE_ITEM = "MOVE_ITEM"
    OPEN_ITEM = "OPEN_ITEM"
    FIND_ITEM = "FIND_ITEM"
    LOCK_SYSTEM = "LOCK_SYSTEM"
    SLEEP_SYSTEM = "SLEEP_SYSTEM"
    RESTART_SYSTEM = "RESTART_SYSTEM"
    SHUTDOWN_SYSTEM = "SHUTDOWN_SYSTEM"
    ABORT_POWER = "ABORT_POWER"
    BATTERY_STATUS = "BATTERY_STATUS"
    LANGUAGE_CHART = "LANGUAGE_CHART"
    HELP = "HELP"
    UNKNOWN = "UNKNOWN"


class IntentParser:
    """Extracts intent and parameters from user input."""

    def __init__(self):
        pass

    def parse(self, text: str) -> Dict[str, Any]:
        """Analyzes text input and returns structured intent and parameters."""
        raw = text.strip()
        cleaned = re.sub(r"^(hey\s+nova|nova|please|could\s+you|can\s+you)\b[,:\s]*", "", raw, flags=re.IGNORECASE).strip()

        # 1. Power & Session Intents
        if re.search(r"\b(lock\b|(?:lock|make)\s+(?:the\s+)?(?:laptop|screen|workstation|pc|computer|system))\b", cleaned, re.IGNORECASE):
            return {"intent": NovaIntent.LOCK_SYSTEM}

        if re.search(r"\b(sleep\b|standby\b|(?:put|make)\s+(?:the\s+)?(?:laptop|pc|computer|system)?\s*(?:to|into|go\s+to)?\s*sleep)\b", cleaned, re.IGNORECASE):
            return {"intent": NovaIntent.SLEEP_SYSTEM}

        # Abort power operations must be checked before shutdown/restart
        if re.search(r"\b(cancel|abort)\s+(?:the\s+)?(?:shutdown|restart|reboot|power)\b", cleaned, re.IGNORECASE):
            return {"intent": NovaIntent.ABORT_POWER}

        if re.search(r"\b(restart|reboot|(?:make\s+(?:the\s+)?(?:laptop|pc|computer|system)\s+restart))\b", cleaned, re.IGNORECASE):
            m_delay = re.search(r"in\s+(\d+)\s*(s|sec|seconds)", cleaned, re.IGNORECASE)
            delay = int(m_delay.group(1)) if m_delay else 0
            return {"intent": NovaIntent.RESTART_SYSTEM, "delay": delay}

        if re.search(r"\b(shutdown|shut\s+down|power\s+off|turn\s+off|(?:make\s+(?:the\s+)?(?:laptop|pc|computer|system)\s+shut\s+down))\b", cleaned, re.IGNORECASE):
            m_delay = re.search(r"in\s+(\d+)\s*(s|sec|seconds)", cleaned, re.IGNORECASE)
            delay = int(m_delay.group(1)) if m_delay else 0
            return {"intent": NovaIntent.SHUTDOWN_SYSTEM, "delay": delay}

        if re.search(r"\b(battery|power\s+status|battery\s+level|charge)\b", cleaned, re.IGNORECASE):
            return {"intent": NovaIntent.BATTERY_STATUS}

        # 2. Architecture / Language Chart
        if re.search(r"\b(language\s+chart|languages|tech\s+stack|what\s+languages\s+(are\s+used|do\s+you\s+use))\b", cleaned, re.IGNORECASE):
            return {"intent": NovaIntent.LANGUAGE_CHART}

        # 3. Rename Item
        # e.g., "rename file notes.txt to summary.txt", "rename folder ProjectA to ProjectB", "rename old.txt to new.txt"
        m_rename = re.match(
            r"^(?:rename|change\s+name\s+of)\s+(?:(file|folder|directory)\s+)?['\"]?([\w\s\.-]+?)['\"]?\s+(?:to|as)\s+['\"]?([\w\s\.-]+?)['\"]?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_rename:
            kind_str = m_rename.group(1) or "any"
            is_dir = True if kind_str in ("folder", "directory") else (False if kind_str == "file" else None)
            return {
                "intent": NovaIntent.RENAME_ITEM,
                "old_name": m_rename.group(2).strip(),
                "new_name": m_rename.group(3).strip(),
                "is_dir": is_dir,
            }

        # 4. Create Folder
        # e.g., "create folder Projects inside Desktop", "make folder Notes in ProjectAlpha", "create directory MyDir in D: drive"
        m_folder = re.match(
            r"^(?:create|make|new)\s+(?:folder|dir|directory)\s+['\"]?([\w\s\.-]+?)['\"]?(?:\s+(?:inside|in(?:\s+specific\s+folder)?|in(?:\s+folder)?|in(?:\s+directory)?)\s+['\"]?([\w\s\.:\\/-]+?)['\"]?)?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_folder:
            name = m_folder.group(1).strip()
            parent = m_folder.group(2).strip() if m_folder.group(2) else None
            return {"intent": NovaIntent.CREATE_FOLDER, "name": name, "parent": parent}

        # 5. Create File
        # Order A: with content before in folder
        m_file1 = re.match(
            r"^(?:create|make|new|write)\s+file\s+['\"]?([\w\s\.-]+?)['\"]?(?:\s+with\s+content\s+['\"](.*?)['\"])?(?:\s+(?:inside|in(?:\s+specific\s+folder)?|in(?:\s+folder)?|in(?:\s+directory)?)\s+['\"]?([\w\s\.:\\/-]+?)['\"]?)?$",
            cleaned,
            re.IGNORECASE,
        )
        # Order B: in folder before with content
        m_file2 = re.match(
            r"^(?:create|make|new|write)\s+file\s+['\"]?([\w\s\.-]+?)['\"]?(?:\s+(?:inside|in(?:\s+specific\s+folder)?|in(?:\s+folder)?|in(?:\s+directory)?)\s+['\"]?([\w\s\.:\\/-]+?)['\"]?)?(?:\s+with\s+content\s+['\"](.*?)['\"])?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_file2 and m_file2.group(3):
            name = m_file2.group(1).strip()
            parent = m_file2.group(2).strip() if m_file2.group(2) else None
            content = m_file2.group(3) or ""
            return {"intent": NovaIntent.CREATE_FILE, "name": name, "content": content, "parent": parent}
        elif m_file1:
            name = m_file1.group(1).strip()
            content = m_file1.group(2) or ""
            parent = m_file1.group(3).strip() if m_file1.group(3) else None
            return {"intent": NovaIntent.CREATE_FILE, "name": name, "content": content, "parent": parent}

        # 5. Copy Item
        # e.g., "copy file notes.txt to Backup", "copy notes.txt into Archive"
        m_copy = re.match(
            r"^copy\s+(?:file\s+|folder\s+)?['\"]?([\w\s\.-]+?)['\"]?\s+(?:to|into)\s+['\"]?([\w\s\.-]+?)['\"]?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_copy:
            return {
                "intent": NovaIntent.COPY_ITEM,
                "source": m_copy.group(1).strip(),
                "destination": m_copy.group(2).strip(),
            }

        # 6. Move Item
        # e.g., "move file notes.txt to Archive", "move MyFolder to Documents"
        m_move = re.match(
            r"^move\s+(?:file\s+|folder\s+)?['\"]?([\w\s\.-]+?)['\"]?\s+(?:to|into)\s+['\"]?([\w\s\.-]+?)['\"]?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_move:
            return {
                "intent": NovaIntent.MOVE_ITEM,
                "source": m_move.group(1).strip(),
                "destination": m_move.group(2).strip(),
            }

        # 7. Delete Item
        # e.g., "delete file notes.txt", "remove folder MyFolder", "delete notes.txt"
        m_del = re.match(
            r"^(?:delete|remove|trash|erase)\s+(?:(file|folder|directory)\s+)?['\"]?([\w\s\.-]+?)['\"]?(?:\s+(permanently))?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_del:
            kind_str = m_del.group(1) or "any"
            is_dir = True if kind_str in ("folder", "directory") else (False if kind_str == "file" else None)
            name = m_del.group(2).strip()
            permanent = bool(m_del.group(3))
            return {
                "intent": NovaIntent.DELETE_ITEM,
                "name": name,
                "is_dir": is_dir,
                "permanent": permanent,
            }

        # 8. Find / Search
        # e.g., "find file report.docx", "find folder Photos", "find app chrome", "search for notes"
        m_find = re.match(
            r"^(?:find|search(?:\s+for)?|locate)\s+(?:(file|folder|directory|app|application)\s+)?['\"]?([\w\s\.-]+?)['\"]?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_find:
            kind_str = m_find.group(1) or "any"
            if kind_str in ("app", "application"):
                kind = "app"
            elif kind_str in ("folder", "directory"):
                kind = "folder"
            elif kind_str == "file":
                kind = "file"
            else:
                kind = "any"
            return {"intent": NovaIntent.FIND_ITEM, "query": m_find.group(2).strip(), "kind": kind}

        # 9. Open Application
        # e.g., "open application Chrome", "launch Calculator", "open app Notepad", "start Spotify"
        m_open_app = re.match(
            r"^(?:open|launch|start|run)\s+(?:app|application)\s+['\"]?([\w\s\.-]+?)['\"]?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_open_app:
            return {"intent": NovaIntent.OPEN_APP, "name": m_open_app.group(1).strip()}

        # 10. Open File or Folder
        # e.g., "open file summary.txt", "open folder Downloads"
        m_open_file_folder = re.match(
            r"^(?:open)\s+(file|folder|directory)\s+['\"]?([\w\s\.-]+?)['\"]?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_open_file_folder:
            return {
                "intent": NovaIntent.OPEN_ITEM,
                "name": m_open_file_folder.group(2).strip(),
                "kind": m_open_file_folder.group(1),
            }

        # 11. Generic "Open <something>"
        # e.g. "open notepad", "open chrome", "open report.docx"
        m_open_generic = re.match(r"^(?:open|launch|start)\s+['\"]?([\w\s\.-]+?)['\"]?$", cleaned, re.IGNORECASE)
        if m_open_generic:
            target = m_open_generic.group(1).strip()
            # If it has a file extension (.txt, .docx, .py, etc.), treat as OPEN_ITEM first
            if "." in target and not target.endswith(".exe"):
                return {"intent": NovaIntent.OPEN_ITEM, "name": target}
            # Otherwise default to OPEN_APP with fallback to OPEN_ITEM
            return {"intent": NovaIntent.OPEN_APP, "name": target}

        # 12. Help
        if cleaned.lower() in ("help", "commands", "what can you do", "features"):
            return {"intent": NovaIntent.HELP}

        return {"intent": NovaIntent.UNKNOWN, "raw": raw}
