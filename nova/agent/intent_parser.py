"""
Nova Intent Parser
Parses natural language and structured user utterances into actionable intents
and parameters for Nova's brain. Supports single intents, summarization, and
compound / complex multi-step commands.
"""

import re
from pathlib import Path
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
    ORGANIZE_FOLDER = "ORGANIZE_FOLDER"
    FIND_DUPLICATES = "FIND_DUPLICATES"
    OPEN_PROJECT = "OPEN_PROJECT"
    REMEMBER = "REMEMBER"
    RECALL = "RECALL"
    FORGET = "FORGET"
    ACTION_HISTORY = "ACTION_HISTORY"
    UNDO = "UNDO"
    # Phase 4 Productivity Tools
    SAVE_NOTE = "SAVE_NOTE"
    LIST_NOTES = "LIST_NOTES"
    SEARCH_NOTES = "SEARCH_NOTES"
    GET_NOTE = "GET_NOTE"
    UPDATE_NOTE = "UPDATE_NOTE"
    DELETE_NOTE = "DELETE_NOTE"
    SET_REMINDER = "SET_REMINDER"
    LIST_REMINDERS = "LIST_REMINDERS"
    COMPLETE_REMINDER = "COMPLETE_REMINDER"
    DISMISS_REMINDER = "DISMISS_REMINDER"
    CLEAR_REMINDERS = "CLEAR_REMINDERS"
    GET_CLIPBOARD = "GET_CLIPBOARD"
    SET_CLIPBOARD = "SET_CLIPBOARD"
    CLEAR_CLIPBOARD = "CLEAR_CLIPBOARD"
    SAVE_CLIPBOARD_NOTE = "SAVE_CLIPBOARD_NOTE"
    SYSTEM_DIAGNOSTICS = "SYSTEM_DIAGNOSTICS"
    SCHEDULE_TASK = "SCHEDULE_TASK"
    LIST_SCHEDULES = "LIST_SCHEDULES"
    CANCEL_SCHEDULE = "CANCEL_SCHEDULE"
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

        # Action verbs
        action_verbs = r"(?:create|make|new|write|open|launch|start|run|delete|remove|rename|copy|move|find|search|locate|list|summarize|lock|sleep|restart|shutdown|organize|detect|preview|note|save|remind|schedule|diagnose|clipboard)"

        # Split on ', and ' or ' and ' if parts look like commands (contain action verbs)
        and_parts = re.split(r",?\s+and\s+", cleaned, flags=re.IGNORECASE)
        if len(and_parts) > 1:
            is_all_actions = True
            for part in and_parts:
                part_clean = part.strip()
                if not re.search(rf"^(?:also\s+)?(?:please\s+)?{action_verbs}\b", part_clean, re.IGNORECASE):
                    is_all_actions = False
                    break
            if is_all_actions:
                return [p.strip() for p in and_parts if p.strip()]

        # Split on comma clauses if all parts are action commands
        comma_parts = re.split(r",\s+", cleaned)
        if len(comma_parts) > 1:
            is_all_actions = True
            for part in comma_parts:
                part_clean = part.strip()
                if not re.search(rf"^(?:also\s+)?(?:please\s+)?{action_verbs}\b", part_clean, re.IGNORECASE):
                    is_all_actions = False
                    break
            if is_all_actions:
                return [p.strip() for p in comma_parts if p.strip()]

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

        # 0. Help & Documentation Intents
        m_help = re.match(
            r"^(?:please\s+)?(?:help(?:\s+me)?|commands|show\s+help|what\s+can\s+you\s+do|manual|man)(?:\s+(?:with\s+|for\s+|about\s+)?([\w\s]+))?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_help:
            topic = m_help.group(1).strip().lower() if m_help.group(1) else None
            return {"intent": NovaIntent.HELP, "topic": topic}

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

        # 3b. Undo and Rollback
        # e.g., "undo", "undo that", "undo the last action", "undo the last file move", "undo last rename"
        m_undo = re.match(
            r"^(?:please\s+)?undo(?:\s+(?:the\s+|that\s+)?last\s+([a-zA-Z_\-\. ]+?)|(?:\s+that))?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_undo:
            raw_filter = m_undo.group(1).strip().lower() if m_undo.group(1) else None
            filt = None
            if raw_filter:
                if "move" in raw_filter:
                    filt = "MOVE_ITEM"
                elif "rename" in raw_filter:
                    filt = "RENAME_ITEM"
                elif "file" in raw_filter or "create" in raw_filter:
                    filt = "CREATE_FILE"
                elif "folder" in raw_filter:
                    filt = "CREATE_FOLDER"
                elif "copy" in raw_filter:
                    filt = "COPY_ITEM"
            return {"intent": NovaIntent.UNDO, "filter": filt}

        # 3c. Action History & Audit Logs
        # e.g., "what files did you move today", "what did you do today", "show action history", "audit log"
        m_history = re.match(
            r"^(?:what\s+(?:files|actions|things|operations|folders)?\s+did\s+you\s+([a-zA-Z_\-]+)\s+today|what\s+did\s+you\s+do\s+today|show\s+(?:action\s+)?history|action\s+history|audit\s+log|list\s+past\s+actions)\b",
            cleaned,
            re.IGNORECASE,
        )
        if m_history:
            verb = m_history.group(1).lower() if m_history.group(1) else None
            intent_filter = None
            if verb:
                if "move" in verb:
                    intent_filter = NovaIntent.MOVE_ITEM
                elif "rename" in verb:
                    intent_filter = NovaIntent.RENAME_ITEM
                elif "create" in verb:
                    intent_filter = NovaIntent.CREATE_FILE
                elif "delete" in verb:
                    intent_filter = NovaIntent.DELETE_ITEM
                elif "copy" in verb:
                    intent_filter = NovaIntent.COPY_ITEM
            return {
                "intent": NovaIntent.ACTION_HISTORY,
                "today": True,
                "intent_filter": intent_filter,
            }

        # 3d. Persistent User Memory - Remember
        # e.g., "Remember that my NOVA project is in D:\Projects\NOVA"
        m_remember_proj = re.match(
            r"^(?:please\s+)?remember\s+(?:that\s+)?(?:my\s+)?(?:project\s+)?['\"]?([a-zA-Z0-9_\-\. ]+?)['\"]?\s+(?:project\s+)?(?:is\s+in|is\s+at|location\s+is|path\s+is)\s+['\"]?([a-zA-Z0-9_\-\.\:\\/ ]+?)['\"]?$",
            cleaned,
            re.IGNORECASE,
        )
        if not m_remember_proj and "project" in cleaned.lower():
            m_remember_proj = re.match(
                r"^(?:please\s+)?remember\s+(?:that\s+)?(?:my\s+)?(?:project\s+)?['\"]?([a-zA-Z0-9_\-\. ]+?)['\"]?\s+(?:project\s+)?(?:is)\s+['\"]?([a-zA-Z0-9_\-\.\:\\/ ]+?)['\"]?$",
                cleaned,
                re.IGNORECASE,
            )
        if m_remember_proj:
            key_name = m_remember_proj.group(1).strip().strip("'\" ")
            path_val = m_remember_proj.group(2).strip().strip("'\" ")
            return {
                "intent": NovaIntent.REMEMBER,
                "type": "project_location",
                "key": key_name,
                "value": path_val,
            }

        m_remember_gen = re.match(
            r"^(?:please\s+)?remember\s+(?:that\s+)?['\"]?([a-zA-Z0-9_\-\. ]+?)['\"]?\s+(?:is|means|=|as)\s+['\"]?([a-zA-Z0-9_\-\.\:\\/ ]+?)['\"]?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_remember_gen:
            k = m_remember_gen.group(1).strip().strip("'\" ")
            if k.lower().startswith("my "):
                k = k[3:].strip()
            return {
                "intent": NovaIntent.REMEMBER,
                "type": "user_preference",
                "key": k,
                "value": m_remember_gen.group(2).strip().strip("'\" "),
            }

        # 3e. Persistent User Memory - Recall
        # e.g., "where is my NOVA project?", "what do you remember?", "show memories"
        m_recall_proj = re.match(
            r"^(?:where\s+is|recall|what\s+is\s+(?:the\s+)?(?:path|location)\s+(?:of|for))\s+(?:my\s+)?(?:project\s+)?['\"]?([a-zA-Z0-9_\-\. ]+?)['\"]?(?:\s+project)?\??$",
            cleaned,
            re.IGNORECASE,
        )
        if m_recall_proj:
            return {
                "intent": NovaIntent.RECALL,
                "key": m_recall_proj.group(1).strip().strip("'\" "),
            }

        if re.match(r"^(?:what\s+do\s+you\s+remember|show\s+(?:my\s+)?(?:memories|preferences|memory)|list\s+(?:my\s+)?(?:memories|preferences|memory)|recall\s+all)\b", cleaned, re.IGNORECASE):
            return {"intent": NovaIntent.RECALL}

        # 3f. Persistent User Memory - Forget
        # e.g., "forget my old project path", "forget my NOVA project", "clear memories"
        if cleaned.lower() in ("clear memories", "forget everything", "clear all memory", "wipe memory"):
            return {"intent": NovaIntent.FORGET, "all": True}

        m_forget = re.match(
            r"^(?:please\s+)?forget\s+(?:that\s+)?(?:my\s+)?(?:project\s+)?['\"]?([a-zA-Z0-9_\-\. ]+?)['\"]?(?:\s+(?:path|project|location|preference))?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_forget:
            return {
                "intent": NovaIntent.FORGET,
                "key": m_forget.group(1).strip().strip("'\" "),
            }

        # =========================================================================
        # 3g. Phase 4: Daily Productivity Tools
        # =========================================================================

        # --- Clipboard Utilities ---
        if re.match(r"^(?:please\s+)?save\s+(?:the\s+)?(?:current\s+)?clipboard(?:\s+text|\s+content)?\s+as\s+(?:a\s+)?note(?:\s+(?:titled|called)\s+['\"]?([\w\s\.-]+?)['\"]?)?$", cleaned, re.IGNORECASE):
            m_clip_note = re.match(r"^.*?note(?:\s+(?:titled|called)\s+['\"]?([\w\s\.-]+?)['\"]?)?$", cleaned, re.IGNORECASE)
            title = m_clip_note.group(1).strip() if (m_clip_note and m_clip_note.group(1)) else None
            return {"intent": NovaIntent.SAVE_CLIPBOARD_NOTE, "title": title}

        if re.match(r"^(?:please\s+)?(?:clear|empty|wipe)\s+(?:the\s+)?clipboard$", cleaned, re.IGNORECASE):
            return {"intent": NovaIntent.CLEAR_CLIPBOARD}

        m_copy_clip = re.match(
            r"^(?:please\s+)?(?:copy\s+(?:text\s+)?['\"](.+?)['\"]\s+to\s+(?:the\s+)?clipboard|copy\s+to\s+(?:the\s+)?clipboard:?\s+(.+)|set\s+clipboard\s+(?:to\s+)?['\"]?(.+?)['\"]?)$",
            cleaned,
            re.IGNORECASE,
        )
        if m_copy_clip:
            text_to_copy = m_copy_clip.group(1) or m_copy_clip.group(2) or m_copy_clip.group(3) or ""
            return {"intent": NovaIntent.SET_CLIPBOARD, "text": text_to_copy.strip()}

        if re.match(r"^(?:please\s+)?(?:read|get|show|check|view)\s+(?:the\s+)?clipboard$|^what(?:'s|\s+is)\s+in\s+(?:the\s+|my\s+)?clipboard$", cleaned, re.IGNORECASE):
            return {"intent": NovaIntent.GET_CLIPBOARD}

        # --- System Diagnostics ---
        if re.search(r"\b(?:check\s+why\s+(?:my\s+)?(?:computer|pc|laptop|machine|system)\s+is\s+running\s+slow(?:ly)?|why\s+is\s+(?:my\s+)?(?:computer|pc|laptop|machine|system)\s+(?:running\s+)?slow(?:ly)?|diagnose\s+(?:my\s+)?(?:system|pc|computer|performance))\b", cleaned, re.IGNORECASE):
            return {"intent": NovaIntent.SYSTEM_DIAGNOSTICS, "action": "diagnose_performance"}

        if re.search(r"\b(?:system\s+diagnostics?|check\s+(?:system\s+)?(?:health|specs|resources)|resource\s+usage|cpu\s+usage|memory\s+usage|ram\s+usage)\b", cleaned, re.IGNORECASE):
            return {"intent": NovaIntent.SYSTEM_DIAGNOSTICS, "action": "full_diagnostics"}

        # --- Quick Notes ---
        # Note deletion
        m_del_note = re.match(r"^(?:please\s+)?(?:delete|remove)\s+note\s+(?:#)?['\"]?(\d+|[\w\s\.-]+?)['\"]?$", cleaned, re.IGNORECASE)
        if m_del_note:
            return {"intent": NovaIntent.DELETE_NOTE, "note_id": m_del_note.group(1).strip()}

        # Note update / append
        m_upd_note = re.match(r"^(?:please\s+)?(?:update|append\s+to)\s+note\s+(?:#)?['\"]?(\d+|[\w\s\.-]+?)['\"]?\s+(?:with|to|:)\s+['\"]?(.+?)['\"]?$", cleaned, re.IGNORECASE)
        if m_upd_note:
            is_append = "append" in cleaned.lower()
            return {
                "intent": NovaIntent.UPDATE_NOTE,
                "note_id": m_upd_note.group(1).strip(),
                "content": m_upd_note.group(2).strip(),
                "append": is_append,
            }

        # Read specific note
        m_get_note = re.match(r"^(?:please\s+)?(?:get|read|view)\s+note\s+(?:#)?['\"]?(\d+|[\w\s\.-]+?)['\"]?$", cleaned, re.IGNORECASE)
        if m_get_note:
            return {"intent": NovaIntent.GET_NOTE, "note_id": m_get_note.group(1).strip()}

        # Search notes
        m_find_note = re.match(r"^(?:please\s+)?(?:search|find)\s+notes?\s+(?:for|about|with)?\s*['\"]?(.+?)['\"]?$", cleaned, re.IGNORECASE)
        if m_find_note and not re.match(r"^(?:all|my)?$", m_find_note.group(1).strip().lower()):
            return {"intent": NovaIntent.SEARCH_NOTES, "query": m_find_note.group(1).strip()}

        # List notes
        if re.match(r"^(?:please\s+)?(?:list|show|view|get)\s+(?:all\s+)?(?:my\s+)?notes(?:\s+with\s+tag\s+['\"]?([\w\-]+)['\"]?)?$", cleaned, re.IGNORECASE):
            m_tag = re.search(r"tag\s+['\"]?([\w\-]+)['\"]?", cleaned, re.IGNORECASE)
            tag_val = m_tag.group(1).strip() if m_tag else None
            return {"intent": NovaIntent.LIST_NOTES, "tag": tag_val}

        # Save note (e.g. "Save a note that I need to revise operating systems tonight", "Take a note: XYZ", "Save note XYZ")
        m_save_note = re.match(
            r"^(?:please\s+)?(?:save|take|add|create)\s+(?:a\s+)?note\s+(?:that\s+|called\s+|titled\s+)?['\"]?(.+?)['\"]?$",
            cleaned,
            re.IGNORECASE,
        ) or re.match(r"^note:\s*(.+)$", cleaned, re.IGNORECASE)
        if m_save_note:
            content_part = m_save_note.group(1).strip()
            # If formatted like "titled <title> with content <content>"
            m_title_content = re.match(r"^(?:titled|called)\s+['\"]?(.+?)['\"]?\s+(?:with\s+content|:)\s+['\"]?(.+?)['\"]?$", content_part, re.IGNORECASE)
            if m_title_content:
                return {
                    "intent": NovaIntent.SAVE_NOTE,
                    "title": m_title_content.group(1).strip(),
                    "content": m_title_content.group(2).strip(),
                }
            return {
                "intent": NovaIntent.SAVE_NOTE,
                "content": content_part,
                "title": None,
            }

        # --- Reminders ---
        # List reminders
        if re.match(r"^(?:please\s+)?(?:list|show|view|what\s+are)\s+(?:all\s+)?(?:my\s+)?reminders\b", cleaned, re.IGNORECASE):
            return {"intent": NovaIntent.LIST_REMINDERS}

        # Complete reminder
        m_comp_rem = re.match(r"^(?:please\s+)?(?:complete|finish|mark\s+done)\s+reminder\s+(?:#)?(\d+)\b", cleaned, re.IGNORECASE)
        if m_comp_rem:
            return {"intent": NovaIntent.COMPLETE_REMINDER, "id": int(m_comp_rem.group(1))}

        # Dismiss reminder
        m_dism_rem = re.match(r"^(?:please\s+)?(?:dismiss|delete|remove|cancel)\s+reminder\s+(?:#)?(\d+)\b", cleaned, re.IGNORECASE)
        if m_dism_rem:
            return {"intent": NovaIntent.DISMISS_REMINDER, "id": int(m_dism_rem.group(1))}

        # Clear completed reminders
        if re.match(r"^(?:please\s+)?clear\s+(?:completed\s+|finished\s+)?reminders\b", cleaned, re.IGNORECASE):
            return {"intent": NovaIntent.CLEAR_REMINDERS}

        # Set reminder:
        # 1. "Remind me at 8 PM to revise operating systems" or "Remind me in 10 minutes to take a break"
        m_rem_time_first = re.match(
            r"^(?:please\s+)?remind\s+me\s+(at\s+[\w\s:]+|in\s+[\w\s]+|on\s+[\w\s]+|tomorrow(?:\s+at\s+[\w\s:]+)?|tonight(?:\s+at\s+[\w\s:]+)?|today(?:\s+at\s+[\w\s:]+)?)\s+to\s+(.+)$",
            cleaned,
            re.IGNORECASE,
        )
        if m_rem_time_first:
            time_part = m_rem_time_first.group(1).strip()
            action_part = m_rem_time_first.group(2).strip()
            rec = "daily" if "every day" in cleaned.lower() or "daily" in cleaned.lower() else None
            return {
                "intent": NovaIntent.SET_REMINDER,
                "message": action_part,
                "due_time": time_part,
                "recurrence": rec,
            }

        # 2. "Remind me to revise operating systems at 8 PM" or "Remind me to check email in 15 minutes"
        m_rem_action_first = re.match(
            r"^(?:please\s+)?remind\s+me\s+to\s+(.+?)\s+(at\s+[\w\s:]+|in\s+[\w\s]+|on\s+[\w\s]+|tomorrow(?:\s+at\s+[\w\s:]+)?|tonight(?:\s+at\s+[\w\s:]+)?|today(?:\s+at\s+[\w\s:]+)?)$",
            cleaned,
            re.IGNORECASE,
        )
        if m_rem_action_first:
            action_part = m_rem_action_first.group(1).strip()
            time_part = m_rem_action_first.group(2).strip()
            rec = "daily" if "every day" in cleaned.lower() or "daily" in cleaned.lower() else None
            return {
                "intent": NovaIntent.SET_REMINDER,
                "message": action_part,
                "due_time": time_part,
                "recurrence": rec,
            }

        # 3. Generic "set reminder to <action> at <time>"
        m_set_rem = re.match(
            r"^(?:please\s+)?(?:set\s+(?:a\s+)?reminder|new\s+reminder)\s+(?:to\s+|for\s+)?(.+?)\s+(at\s+[\w\s:]+|in\s+[\w\s]+|on\s+[\w\s]+|tomorrow(?:\s+at\s+[\w\s:]+)?)$",
            cleaned,
            re.IGNORECASE,
        )
        if m_set_rem:
            action_part = m_set_rem.group(1).strip()
            time_part = m_set_rem.group(2).strip()
            return {
                "intent": NovaIntent.SET_REMINDER,
                "message": action_part,
                "due_time": time_part,
                "recurrence": None,
            }

        # --- Scheduled Tasks ---
        # List schedules
        if re.match(r"^(?:please\s+)?(?:list|show|view)\s+(?:scheduled\s+tasks|schedules)\b", cleaned, re.IGNORECASE):
            return {"intent": NovaIntent.LIST_SCHEDULES}

        # Cancel schedule
        m_cancel_sched = re.match(r"^(?:please\s+)?(?:cancel|delete|remove)\s+(?:schedule|scheduled\s+task)\s+(?:#)?(\d+)\b", cleaned, re.IGNORECASE)
        if m_cancel_sched:
            return {"intent": NovaIntent.CANCEL_SCHEDULE, "id": int(m_cancel_sched.group(1))}

        # Daily schedule: "Every day at 9 AM, open my college project" / "Daily at 8 PM: ..."
        m_daily_sched = re.match(
            r"^(?:every\s+day|daily)\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)[,:\s]+(.+)$",
            cleaned,
            re.IGNORECASE,
        )
        if m_daily_sched:
            raw_time = m_daily_sched.group(1).strip()
            raw_action = m_daily_sched.group(2).strip()

            # Parse action intent
            sub_parsed = self.parse_single(raw_action)
            action_intent = sub_parsed.get("intent")
            # Extract parameters
            action_params = {k: v for k, v in sub_parsed.items() if k not in ("intent", "raw")}

            # Normalize time to HH:MM 24h
            t_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", raw_time, re.IGNORECASE)
            time_hhmm = "09:00"
            if t_match:
                hr = int(t_match.group(1))
                mn = int(t_match.group(2) or 0)
                merid = t_match.group(3)
                if merid:
                    if merid.lower() == "pm" and hr < 12:
                        hr += 12
                    elif merid.lower() == "am" and hr == 12:
                        hr = 0
                time_hhmm = f"{hr:02d}:{mn:02d}"

            return {
                "intent": NovaIntent.SCHEDULE_TASK,
                "name": f"Daily at {time_hhmm}: {raw_action}",
                "target_intent": action_intent,
                "target_params": action_params,
                "schedule_type": "daily_at",
                "time_of_day": time_hhmm,
                "raw_action": raw_action,
            }

        # 4. Rename Item
        m_rename = re.match(
            r"^(?:rename|change\s+name\s+of)\s+(?:(file|folder|directory)\s+)?['\"]?([\w\s\.:\\/-]+?)['\"]?\s+(?:to|as)\s+['\"]?([\w\s\.:\\/-]+?)['\"]?$",
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
        # Supports "create folder tests there", "create a tests folder there", "make folder Demo in Project"
        m_folder_there = re.match(
            r"^(?:create|make|new)\s+(?:a\s+)?['\"]?([a-zA-Z0-9_\-\. ]+?)['\"]?\s+(?:folder|dir|directory)\s+there$",
            cleaned,
            re.IGNORECASE,
        ) or re.match(
            r"^(?:create|make|new)\s+(?:a\s+)?(?:folder|dir|directory)\s+['\"]?([a-zA-Z0-9_\-\. ]+?)['\"]?\s+there$",
            cleaned,
            re.IGNORECASE,
        )
        if m_folder_there:
            fname = m_folder_there.group(1).strip().strip("'\" ")
            return {"intent": NovaIntent.CREATE_FOLDER, "name": fname, "parent": "there"}

        m_folder_b = re.match(
            r"^(?:create|make|new)\s+(?:a\s+)?['\"]?([a-zA-Z0-9_\-\. ]+?)['\"]?\s+(?:folder|dir|directory)(?:\s+(?:inside|in(?:\s+specific\s+folder)?|in(?:\s+folder)?|in(?:\s+directory)?)\s+['\"]?([\w\s\.:\\/-]+?)['\"]?)?$",
            cleaned,
            re.IGNORECASE,
        )
        m_folder = re.match(
            r"^(?:create|make|new)\s+(?:a\s+)?(?:folder|dir|directory)\s+['\"]?([\w\s\.-]+?)['\"]?(?:\s+(?:inside|in(?:\s+specific\s+folder)?|in(?:\s+folder)?|in(?:\s+directory)?)\s+['\"]?([\w\s\.:\\/-]+?)['\"]?)?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_folder_b and m_folder_b.group(1).lower() not in ("folder", "dir", "directory", "a"):
            name = m_folder_b.group(1).strip().strip("'\" ")
            raw_p = m_folder_b.group(2)
            raw_parent = raw_p.strip().strip("'\" ") if raw_p else None
            parent = re.sub(r"\s+(folder|directory|dir)$", "", raw_parent, flags=re.IGNORECASE).strip("'\" ") if raw_parent else None
            return {"intent": NovaIntent.CREATE_FOLDER, "name": name, "parent": parent}
        elif m_folder:
            name = m_folder.group(1).strip().strip("'\" ")
            raw_p = m_folder.group(2)
            raw_parent = raw_p.strip().strip("'\" ") if raw_p else None
            parent = re.sub(r"\s+(folder|directory|dir)$", "", raw_parent, flags=re.IGNORECASE).strip("'\" ") if raw_parent else None
            return {"intent": NovaIntent.CREATE_FOLDER, "name": name, "parent": parent}

        # 6. Create File
        # Order A: with content before in folder / there
        m_file1 = re.match(
            r"^(?:create|make|new|write)\s+(?:a\s+)?file\s+['\"]?([\w\s\.-]+?)['\"]?(?:\s+with\s+content\s+['\"](.*?)['\"])?(?:\s+(?:inside|in(?:\s+specific\s+folder)?|in(?:\s+folder)?|in(?:\s+directory)?)\s+['\"]?([\w\s\.:\\/-]+?)['\"]?|\s+(there))?$",
            cleaned,
            re.IGNORECASE,
        )
        # Order B: in folder / there before with content
        m_file2 = re.match(
            r"^(?:create|make|new|write)\s+(?:a\s+)?file\s+['\"]?([\w\s\.-]+?)['\"]?(?:\s+(?:inside|in(?:\s+specific\s+folder)?|in(?:\s+folder)?|in(?:\s+directory)?)\s+['\"]?([\w\s\.:\\/-]+?)['\"]?|\s+(there))?(?:\s+with\s+content\s+['\"](.*?)['\"])?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_file2 and (m_file2.group(2) or m_file2.group(3) or m_file2.group(4)):
            name = m_file2.group(1).strip().strip("'\"")
            raw_p = m_file2.group(2) or m_file2.group(3)
            raw_parent = raw_p.strip().strip("'\"") if raw_p else None
            parent = re.sub(r"\s+(folder|directory|dir)$", "", raw_parent, flags=re.IGNORECASE).strip("'\"") if raw_parent else None
            content = m_file2.group(4) or ""
            return {"intent": NovaIntent.CREATE_FILE, "name": name, "content": content, "parent": parent}
        elif m_file1:
            name = m_file1.group(1).strip().strip("'\"")
            content = m_file1.group(2) or ""
            raw_p = m_file1.group(3) or m_file1.group(4)
            raw_parent = raw_p.strip().strip("'\"") if raw_p else None
            parent = re.sub(r"\s+(folder|directory|dir)$", "", raw_parent, flags=re.IGNORECASE).strip("'\"") if raw_parent else None
            return {"intent": NovaIntent.CREATE_FILE, "name": name, "content": content, "parent": parent}

        # 7. Copy Item
        m_copy = re.match(
            r"^copy\s+(?:file\s+|folder\s+)?['\"]?([\w\s\.:\\/-]+?)['\"]?\s+(?:to|into)\s+['\"]?([\w\s\.:\\/-]+?)['\"]?$",
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
            r"^move\s+(?:file\s+|folder\s+)?['\"]?([\w\s\.:\\/-]+?)['\"]?\s+(?:to|into)\s+['\"]?([\w\s\.:\\/-]+?)['\"]?$",
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
            r"^(?:delete|remove|trash|erase)\s+(?:(file|folder|directory)\s+)?['\"]?([\w\s\.:\\/-]+?)['\"]?(?:\s+(permanently))?$",
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

        # 9a. Organize Folder by File Type
        m_org = re.match(
            r"^(?:preview\s+)?organize\s+(?:my\s+)?(?:folder\s+)?['\"]?([a-zA-Z0-9_\-\.\:\\/ ]+?)['\"]?(?:\s+folder)?(?:\s+by\s+(?:file\s+)?type)?(?:\s+(preview))?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_org:
            target_f = m_org.group(1).strip().strip("'\" ")
            is_preview = bool(cleaned.lower().startswith("preview") or m_org.group(2))
            return {
                "intent": NovaIntent.ORGANIZE_FOLDER,
                "folder": target_f,
                "preview": is_preview,
            }

        # 9b. Find Duplicate Files
        m_dup = re.match(
            r"^(?:find|detect|search(?:\s+for)?|list)\s+duplicates?(?:\s+files?)?(?:\s+(?:in|inside|under)\s+(?:my\s+)?(?:folder\s+)?['\"]?([a-zA-Z0-9_\-\.\:\\/ ]+?)['\"]?(?:\s+folder)?)?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_dup:
            target_f = m_dup.group(1).strip().strip("'\" ") if m_dup.group(1) else None
            return {
                "intent": NovaIntent.FIND_DUPLICATES,
                "folder": target_f,
            }

        # 10. Find / Search (Basic & Advanced Natural Language Filters)
        if re.match(r"^(?:find|search(?:\s+for)?|locate|list\s+files?)\b", cleaned, re.IGNORECASE):
            parsed_find = self._parse_find_command(cleaned)
            if parsed_find:
                return parsed_find

        # 11. Open Project or File in specific Application
        # Examples: "open my NOVA project in VS Code", "open project Nova in code", "open report.pdf with chrome"
        m_open_in_app = re.match(
            r"^(?:open|launch|start)\s+(?:my\s+)?(?:project\s+|file\s+|folder\s+)?['\"]?([a-zA-Z0-9_\-\.\:\\/ ]+?)['\"]?\s+(?:project\s+)?(?:in|with|using)\s+['\"]?([a-zA-Z0-9_\-\. ]+?)['\"]?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_open_in_app:
            target = m_open_in_app.group(1).strip().strip("'\" ")
            app = m_open_in_app.group(2).strip().strip("'\" ")
            # If target has a file extension (and not .exe), it's OPEN_ITEM with app
            if "." in target and not target.lower().endswith((".exe", ".cmd", ".bat")):
                return {"intent": NovaIntent.OPEN_ITEM, "name": target, "app": app}
            # If "project" was in cleaned or app is an editor/IDE, it's OPEN_PROJECT
            lower_clean = cleaned.lower()
            if "project" in lower_clean or app.lower() in ("code", "vscode", "vs code", "visual studio code", "pycharm", "sublime", "sublime text", "cursor", "notepad++", "studio"):
                return {"intent": NovaIntent.OPEN_PROJECT, "project": target, "app": app}
            return {"intent": NovaIntent.OPEN_ITEM, "name": target, "app": app}

        # 12. Open Application in Project: e.g. "open VS Code in my NOVA project", "launch code in D:\Nova"
        m_app_in_proj = re.match(
            r"^(?:open|launch|start)\s+(?:app\s+)?['\"]?([a-zA-Z0-9_\-\. ]+?)['\"]?\s+(?:in|inside|for)\s+(?:my\s+)?(?:project\s+|folder\s+)?['\"]?([a-zA-Z0-9_\-\.\:\\/ ]+?)['\"]?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_app_in_proj:
            app = m_app_in_proj.group(1).strip().strip("'\" ")
            proj = m_app_in_proj.group(2).strip().strip("'\" ")
            if "project" in cleaned.lower() or app.lower() in ("code", "vscode", "vs code", "visual studio code", "pycharm", "sublime", "sublime text", "notepad", "terminal"):
                return {"intent": NovaIntent.OPEN_PROJECT, "project": proj, "app": app}

        # 13. Open Project directly: e.g. "open project Nova", "open my NOVA project"
        m_open_project = re.match(
            r"^(?:open|launch)\s+(?:(?:my\s+)?project\s+['\"]?([a-zA-Z0-9_\-\.\:\\/ ]+?)['\"]?|(?:my\s+)?['\"]?([a-zA-Z0-9_\-\.\:\\/ ]+?)['\"]?\s+project)$",
            cleaned,
            re.IGNORECASE,
        )
        if m_open_project:
            proj_name = (m_open_project.group(1) or m_open_project.group(2)).strip().strip("'\" ")
            return {
                "intent": NovaIntent.OPEN_PROJECT,
                "project": proj_name,
                "app": "Visual Studio Code",
            }

        # 14. Open Application explicitly: e.g. "open app spotify"
        m_open_app = re.match(
            r"^(?:open|launch|start|run)\s+(?:app|application)\s+['\"]?([a-zA-Z0-9_\-\. ]+?)['\"]?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_open_app:
            return {"intent": NovaIntent.OPEN_APP, "name": m_open_app.group(1).strip().strip("'\" ")}

        # 15. Open File or Folder explicitly: e.g. "open file budget.xlsx", "open folder Documents"
        m_open_file_folder = re.match(
            r"^(?:open)\s+(file|folder|directory)\s+['\"]?([a-zA-Z0-9_\-\.\:\\/ ]+?)['\"]?(?:\s+(?:in|with|using)\s+['\"]?([a-zA-Z0-9_\-\. ]+?)['\"]?)?$",
            cleaned,
            re.IGNORECASE,
        )
        if m_open_file_folder:
            res_dict = {
                "intent": NovaIntent.OPEN_ITEM,
                "name": m_open_file_folder.group(2).strip().strip("'\" "),
                "kind": m_open_file_folder.group(1),
            }
            if m_open_file_folder.group(3):
                res_dict["app"] = m_open_file_folder.group(3).strip().strip("'\" ")
            return res_dict

        # 16. Generic "Open <something>"
        m_open_generic = re.match(r"^(?:open|launch|start)\s+['\"]?([a-zA-Z0-9_\-\.\:\\/ ]+?)['\"]?$", cleaned, re.IGNORECASE)
        if m_open_generic:
            target = m_open_generic.group(1).strip().strip("'\" ")
            # Strip leading "the " e.g. "open the Q3 financial report"
            if target.lower().startswith("the "):
                target = target[4:].strip()
            if "." in target and not target.endswith(".exe"):
                return {"intent": NovaIntent.OPEN_ITEM, "name": target}
            return {"intent": NovaIntent.OPEN_APP, "name": target}

        # 14. Help
        if cleaned.lower() in ("help", "commands", "what can you do", "features"):
            return {"intent": NovaIntent.HELP}

        return {"intent": NovaIntent.UNKNOWN, "raw": raw_text}

    def _parse_find_command(self, text: str) -> Optional[Dict[str, Any]]:
        """Parses natural language search commands into structured search filters."""
        from nova.core.indexer import EXTENSION_CATEGORY_MAP, parse_size_str

        core = re.sub(r"^(?:find|search(?:\s+for)?|locate|list\s+files?)\s+", "", text, flags=re.IGNORECASE).strip()
        core = re.sub(r"^(?:all\s+)", "", core, flags=re.IGNORECASE).strip()

        # Check for simple app search: e.g. "find app chrome", "app notepad"
        m_app = re.match(r"^(?:app|application)\s+['\"]?([\w\s\.-]+?)['\"]?$", core, re.IGNORECASE)
        if m_app:
            return {"intent": NovaIntent.FIND_ITEM, "query": m_app.group(1).strip().strip("'\""), "kind": "app"}

        # Check for simple file or folder search: e.g. "find file run_nova.py", "find folder Documents"
        m_simple = re.match(r"^(file|folder|directory)\s+['\"]?([\w\s\.-]+?)['\"]?$", core, re.IGNORECASE)
        if m_simple:
            kind_str = m_simple.group(1).lower()
            kind_val = "folder" if kind_str in ("folder", "directory") else "file"
            target_name = m_simple.group(2).strip().strip("'\"")
            return {
                "intent": NovaIntent.FIND_ITEM,
                "query": target_name,
                "kind": kind_val,
                "extension": Path(target_name).suffix.lower() if "." in target_name else None,
                "directory": None,
                "modified_within_days": None,
                "min_size": None,
                "max_size": None,
            }

        # Check for single word filename query: e.g. "find run_nova.py"
        if len(core.strip().split()) == 1 and "." in core.strip() and not core.strip().startswith("."):
            clean_token = core.strip().strip("'\" ")
            return {
                "intent": NovaIntent.FIND_ITEM,
                "query": clean_token,
                "kind": "file",
                "extension": Path(clean_token).suffix.lower(),
                "directory": None,
                "modified_within_days": None,
                "min_size": None,
                "max_size": None,
            }

        # Extract modification date filter
        modified_within_days: Optional[float] = None
        m_mod = re.search(
            r"\b(?:modified|updated|changed)\s+(?:in\s+the\s+last|past|within)?\s*(\d+)?\s*(days?|hours?|weeks?|today|yesterday)\b",
            core,
            re.IGNORECASE,
        )
        if m_mod:
            num_str = m_mod.group(1)
            unit_str = m_mod.group(2).lower()
            if unit_str.startswith("today"):
                modified_within_days = 1.0
            elif unit_str.startswith("yesterday"):
                modified_within_days = 2.0
            elif num_str:
                num = float(num_str)
                if unit_str.startswith("hour"):
                    modified_within_days = max(num / 24.0, 0.04)
                elif unit_str.startswith("week"):
                    modified_within_days = num * 7.0
                else:
                    modified_within_days = num
            core = core[:m_mod.start()] + " " + core[m_mod.end():]

        # Extract size filter
        min_size: Optional[int] = None
        max_size: Optional[int] = None
        m_size_gt = re.search(r"\b(?:larger|bigger|greater)\s+than\s+([0-9\.]+\s*[a-zA-Z]+)\b", core, re.IGNORECASE)
        if m_size_gt:
            min_size = parse_size_str(m_size_gt.group(1))
            core = core[:m_size_gt.start()] + " " + core[m_size_gt.end():]
        m_size_lt = re.search(r"\b(?:smaller|less)\s+than\s+([0-9\.]+\s*[a-zA-Z]+)\b", core, re.IGNORECASE)
        if m_size_lt:
            max_size = parse_size_str(m_size_lt.group(1))
            core = core[:m_size_lt.start()] + " " + core[m_size_lt.end():]

        # Extract directory filter
        directory: Optional[str] = None
        m_dir = re.search(
            r"\b(?:in|inside|under)\s+(?:my\s+)?(?:project\s+)?['\"]?([a-zA-Z]:?[\\/\w\.-]*?)['\"]?(?:\s+(?:project|folder|directory|dir|drive))?(?:\s|$)",
            core,
            re.IGNORECASE,
        )
        if m_dir:
            cand_dir = m_dir.group(1).strip()
            if cand_dir.lower() not in ("python", "pdf", "java", "code", "image", "video", "text"):
                directory = cand_dir
                core = core[:m_dir.start()] + " " + core[m_dir.end():]

        # Extract extension or file category
        extension: Optional[str] = None
        for cat in EXTENSION_CATEGORY_MAP.keys():
            m_cat = re.search(rf"\b{cat}(?:\s+files?|\s+documents?|\s+scripts?)?\b", core, re.IGNORECASE)
            if m_cat:
                extension = cat
                core = core[:m_cat.start()] + " " + core[m_cat.end():]
                break

        if not extension:
            m_ext = re.search(r"\b\*?\.([a-zA-Z0-9]+)\b", core)
            if m_ext:
                extension = f".{m_ext.group(1).lower()}"
                core = core[:m_ext.start()] + " " + core[m_ext.end():]

        # Extract kind
        kind = "any"
        if re.search(r"\b(?:folders?|directory|directories)\b", core, re.IGNORECASE):
            kind = "folder"
            core = re.sub(r"\b(?:folders?|directory|directories)\b", "", core, flags=re.IGNORECASE)
        elif re.search(r"\b(?:files?|documents?)\b", core, re.IGNORECASE) or extension:
            kind = "file"
            core = re.sub(r"\b(?:files?|documents?)\b", "", core, flags=re.IGNORECASE)

        # Remaining core text is the query
        query = re.sub(r"\s+", " ", core).strip().strip("'\" ")
        query = re.sub(r"^(?:named|called|with\s+name)\s+", "", query, flags=re.IGNORECASE).strip()

        return {
            "intent": NovaIntent.FIND_ITEM,
            "query": query,
            "kind": kind,
            "extension": extension,
            "directory": directory,
            "modified_within_days": modified_within_days,
            "min_size": min_size,
            "max_size": max_size,
        }
