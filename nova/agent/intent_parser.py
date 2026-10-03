"""
Nova Intent Parser
Parses natural language and structured user utterances into actionable intents
and parameters for Nova's brain. Supports single intents, summarization, and
compound / complex multi-step commands.
"""

import re
from typing import Dict, Any, Optional, List


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
    SUMMARIZE = "SUMMARIZE"
    LOCK_SYSTEM = "LOCK_SYSTEM"
    SLEEP_SYSTEM = "SLEEP_SYSTEM"
    RESTART_SYSTEM = "RESTART_SYSTEM"
    SHUTDOWN_SYSTEM = "SHUTDOWN_SYSTEM"
    ABORT_POWER = "ABORT_POWER"
    BATTERY_STATUS = "BATTERY_STATUS"
    LANGUAGE_CHART = "LANGUAGE_CHART"
    HELP = "HELP"
    COMPLEX_COMMAND = "COMPLEX_COMMAND"
    UNKNOWN = "UNKNOWN"


class IntentParser:
    """Extracts intent and parameters from user input."""

    def __init__(self):
        pass

    def is_compound_command(self, text: str) -> bool:
        """Determines if the text contains multiple linked action commands."""
        parts = self.split_compound(text)
        return len(parts) > 1

    def split_compound(self, text: str) -> List[str]:
        """
        Splits compound natural language commands by conjunctions:
        e.g., 'Make a folder Demo in Project folder and create a file xyz.txt'
        returns ['Make a folder Demo in Project folder', 'create a file xyz.txt']
        """
        raw = text.strip()
        cleaned = re.sub(r"^(hey\s+nova|nova|please|could\s+you|can\s+you)\b[,:\s]*", "", raw, flags=re.IGNORECASE).strip()

        # Split on explicit connectors like ';', ' and then ', ', then ', ' then ', ' after that '
        explicit_split = re.split(r";\s*|\s+(?:and\s+then|then|after\s+that|,\s*then)\s+", cleaned, flags=re.IGNORECASE)
        if len(explicit_split) > 1:
            return [p.strip() for p in explicit_split if p.strip()]

        # Split on ' and ' if both sides look like commands (contain action verbs)
        action_verbs = r"(?:create|make|new|write|open|launch|start|run|delete|remove|rename|copy|move|find|search|summarize|lock|sleep|restart|shutdown)"
        and_parts = re.split(r"\s+and\s+", cleaned, flags=re.IGNORECASE)
        if len(and_parts) > 1:
            # Check if all parts start with an action verb (or article + action noun)
            is_all_actions = True
            for part in and_parts:
                part_clean = part.strip()
                if not re.search(rf"^(?:also\s+)?(?:please\s+)?{action_verbs}\b", part_clean, re.IGNORECASE):
                    is_all_actions = False
                    break
            if is_all_actions:
                return [p.strip() for p in and_parts if p.strip()]

        return [cleaned]

    def parse(self, text: str) -> Dict[str, Any]:
        """
        Analyzes text input. If compound, returns COMPLEX_COMMAND with sub-commands,
        otherwise parses the single intent.
        """
        raw = text.strip()
        cleaned = re.sub(r"^(hey\s+nova|nova|please|could\s+you|can\s+you)\b[,:\s]*", "", raw, flags=re.IGNORECASE).strip()

        # Check if this is a compound command
        sub_commands = self.split_compound(cleaned)
        if len(sub_commands) > 1:
            return {
                "intent": NovaIntent.COMPLEX_COMMAND,
                "raw": raw,
                "sub_commands": sub_commands,
            }

        return self.parse_single(cleaned, raw=raw)

    def parse_single(self, text: str, raw: Optional[str] = None) -> Dict[str, Any]:
        """Extracts intent and parameters for a single command string."""
        raw_text = raw or text
        cleaned = re.sub(r"^(hey\s+nova|nova|please|could\s+you|can\s+you)\b[,:\s]*", "", text, flags=re.IGNORECASE).strip()

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

        # 3. Summarization Intents
        # e.g., "summarize file report.txt", "summarize context", "summarize this text: ...", "summarize notes.txt"
        m_sum_context = re.match(r"^summarize\s+(?:the\s+)?(?:context|conversation|history|session|recent\s+actions|what\s+we\s+did)\b", cleaned, re.IGNORECASE)
        if m_sum_context:
            return {"intent": NovaIntent.SUMMARIZE, "target_type": "context"}

        m_sum_file = re.match(
            r"^summarize\s+(?:the\s+)?(?:file|document|doc)\s+['\"]?([\w\s\.-]+?)['\"]?(?:\s+(?:inside|in)\s+['\"]?([\w\s\.-]+?)['\"]?)?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_sum_file:
            name = m_sum_file.group(1).strip().strip("'\"")
            parent = m_sum_file.group(2).strip().strip("'\"") if m_sum_file.group(2) else None
            return {"intent": NovaIntent.SUMMARIZE, "target_type": "file", "target": name, "parent": parent}

        m_sum_text_colon = re.match(r"^summarize\s+(?:this\s+)?(?:text|content|paragraph|article|note)?\s*:\s*(.+)$", cleaned, re.IGNORECASE | re.DOTALL)
        if m_sum_text_colon:
            return {"intent": NovaIntent.SUMMARIZE, "target_type": "text", "text": m_sum_text_colon.group(1).strip()}

        m_sum_generic = re.match(r"^summarize\s+(.+)$", cleaned, re.IGNORECASE | re.DOTALL)
        if m_sum_generic:
            target_str = m_sum_generic.group(1).strip()
            # If target has a file extension like .txt, .pdf, .docx, .py, treat as file
            if re.match(r"^['\"]?[\w\s\.-]+\.[a-zA-Z0-9]{1,5}['\"]?$", target_str):
                clean_target = target_str.strip("'\"")
                return {"intent": NovaIntent.SUMMARIZE, "target_type": "file", "target": clean_target}
            elif any(w in target_str.lower() for w in ["context", "conversation", "history", "session"]):
                return {"intent": NovaIntent.SUMMARIZE, "target_type": "context"}
            else:
                return {"intent": NovaIntent.SUMMARIZE, "target_type": "text", "text": target_str}

        # 4. Rename Item
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
                "old_name": m_rename.group(2).strip().strip("'\""),
                "new_name": m_rename.group(3).strip().strip("'\""),
                "is_dir": is_dir,
            }

        # 5. Create Folder
        # e.g., "create folder Projects inside Desktop", "make a folder 'Demo' in Project folder"
        m_folder = re.match(
            r"^(?:create|make|new)\s+(?:a\s+)?(?:folder|dir|directory)\s+['\"]?([\w\s\.-]+?)['\"]?(?:\s+(?:inside|in(?:\s+specific\s+folder)?|in(?:\s+folder)?|in(?:\s+directory)?)\s+['\"]?([\w\s\.:\\/-]+?)['\"]?)?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_folder:
            name = m_folder.group(1).strip().strip("'\"")
            raw_parent = m_folder.group(2).strip().strip("'\"") if m_folder.group(2) else None
            # Clean trailing 'folder' or 'directory' from parent if present
            parent = re.sub(r"\s+(folder|directory|dir)$", "", raw_parent, flags=re.IGNORECASE).strip("'\"") if raw_parent else None
            return {"intent": NovaIntent.CREATE_FOLDER, "name": name, "parent": parent}

        # 6. Create File
        # Order A: with content before in folder
        m_file1 = re.match(
            r"^(?:create|make|new|write)\s+(?:a\s+)?file\s+['\"]?([\w\s\.-]+?)['\"]?(?:\s+with\s+content\s+['\"](.*?)['\"])?(?:\s+(?:inside|in(?:\s+specific\s+folder)?|in(?:\s+folder)?|in(?:\s+directory)?)\s+['\"]?([\w\s\.:\\/-]+?)['\"]?)?$",
            cleaned,
            re.IGNORECASE,
        )
        # Order B: in folder before with content
        m_file2 = re.match(
            r"^(?:create|make|new|write)\s+(?:a\s+)?file\s+['\"]?([\w\s\.-]+?)['\"]?(?:\s+(?:inside|in(?:\s+specific\s+folder)?|in(?:\s+folder)?|in(?:\s+directory)?)\s+['\"]?([\w\s\.:\\/-]+?)['\"]?)?(?:\s+with\s+content\s+['\"](.*?)['\"])?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_file2 and m_file2.group(3):
            name = m_file2.group(1).strip().strip("'\"")
            raw_parent = m_file2.group(2).strip().strip("'\"") if m_file2.group(2) else None
            parent = re.sub(r"\s+(folder|directory|dir)$", "", raw_parent, flags=re.IGNORECASE).strip("'\"") if raw_parent else None
            content = m_file2.group(3) or ""
            return {"intent": NovaIntent.CREATE_FILE, "name": name, "content": content, "parent": parent}
        elif m_file1:
            name = m_file1.group(1).strip().strip("'\"")
            content = m_file1.group(2) or ""
            raw_parent = m_file1.group(3).strip().strip("'\"") if m_file1.group(3) else None
            parent = re.sub(r"\s+(folder|directory|dir)$", "", raw_parent, flags=re.IGNORECASE).strip("'\"") if raw_parent else None
            return {"intent": NovaIntent.CREATE_FILE, "name": name, "content": content, "parent": parent}

        # 7. Copy Item
        m_copy = re.match(
            r"^copy\s+(?:file\s+|folder\s+)?['\"]?([\w\s\.-]+?)['\"]?\s+(?:to|into)\s+['\"]?([\w\s\.-]+?)['\"]?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_copy:
            return {
                "intent": NovaIntent.COPY_ITEM,
                "source": m_copy.group(1).strip().strip("'\""),
                "destination": m_copy.group(2).strip().strip("'\""),
            }

        # 8. Move Item
        m_move = re.match(
            r"^move\s+(?:file\s+|folder\s+)?['\"]?([\w\s\.-]+?)['\"]?\s+(?:to|into)\s+['\"]?([\w\s\.-]+?)['\"]?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_move:
            return {
                "intent": NovaIntent.MOVE_ITEM,
                "source": m_move.group(1).strip().strip("'\""),
                "destination": m_move.group(2).strip().strip("'\""),
            }

        # 9. Delete Item
        m_del = re.match(
            r"^(?:delete|remove|trash|erase)\s+(?:(file|folder|directory)\s+)?['\"]?([\w\s\.-]+?)['\"]?(?:\s+(permanently))?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_del:
            kind_str = m_del.group(1) or "any"
            is_dir = True if kind_str in ("folder", "directory") else (False if kind_str == "file" else None)
            name = m_del.group(2).strip().strip("'\"")
            permanent = bool(m_del.group(3))
            return {
                "intent": NovaIntent.DELETE_ITEM,
                "name": name,
                "is_dir": is_dir,
                "permanent": permanent,
            }

        # 10. Find / Search
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
            return {"intent": NovaIntent.FIND_ITEM, "query": m_find.group(2).strip().strip("'\""), "kind": kind}

        # 11. Open Application
        m_open_app = re.match(
            r"^(?:open|launch|start|run)\s+(?:app|application)\s+['\"]?([\w\s\.-]+?)['\"]?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_open_app:
            return {"intent": NovaIntent.OPEN_APP, "name": m_open_app.group(1).strip().strip("'\"")}

        # 12. Open File or Folder
        m_open_file_folder = re.match(
            r"^(?:open)\s+(file|folder|directory)\s+['\"]?([\w\s\.-]+?)['\"]?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_open_file_folder:
            return {
                "intent": NovaIntent.OPEN_ITEM,
                "name": m_open_file_folder.group(2).strip().strip("'\""),
                "kind": m_open_file_folder.group(1),
            }

        # 13. Generic "Open <something>"
        m_open_generic = re.match(r"^(?:open|launch|start)\s+['\"]?([\w\s\.-]+?)['\"]?$", cleaned, re.IGNORECASE)
        if m_open_generic:
            target = m_open_generic.group(1).strip().strip("'\"")
            if "." in target and not target.endswith(".exe"):
                return {"intent": NovaIntent.OPEN_ITEM, "name": target}
            return {"intent": NovaIntent.OPEN_APP, "name": target}

        # 14. Help
        if cleaned.lower() in ("help", "commands", "what can you do", "features"):
            return {"intent": NovaIntent.HELP}

        return {"intent": NovaIntent.UNKNOWN, "raw": raw_text}
