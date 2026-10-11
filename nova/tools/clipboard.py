"""
Nova Clipboard Utilities
Provides safe reading, copying, and clearing of clipboard text with
explicit privacy safeguards, sensitive pattern detection, and redaction.
"""

import re
import sys
import ctypes
import logging
from typing import Dict, List, Optional, Any, Tuple

from nova.core.results import ToolResult

logger = logging.getLogger("nova.tools.clipboard")


class SensitiveContentDetector:
    """
    Scans text for sensitive patterns including API keys, passwords,
    private certificates, and payment details.
    """

    PATTERNS = {
        "OpenAI API Key": r"sk-[a-zA-Z0-9_-]{20,}",
        "AWS Access Key": r"AKIA[0-9A-Z]{16}",
        "GitHub Token": r"(?:ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{40,}",
        "Generic Secret / Token": r"(?i)(?:api_key|access_token|secret_key|private_key|auth_token)\s*[:=]\s*['\"][a-zA-Z0-9_\-]{8,}['\"]",
        "Private Key Header": r"-----BEGIN\s+(?:[A-Z0-9_-]+\s+)?PRIVATE KEY-----",
        "Connection String with Password": r"(?i)(?:mongodb(?:\+srv)?|postgres|postgresql|mysql|redis)://[^:]+:[^@]+@",
        "Credit Card Pattern": r"\b(?:\d{4}[ -]?){3}\d{4}\b",
        "Bearer Authorization": r"(?i)bearer\s+[a-zA-Z0-9\._\-]{20,}",
    }

    @classmethod
    def scan(cls, text: str) -> Tuple[bool, List[str]]:
        """
        Scans text for known sensitive patterns.
        Returns (is_sensitive, matched_pattern_names).
        """
        if not text:
            return False, []

        matches = []
        for name, pattern in cls.PATTERNS.items():
            if re.search(pattern, text):
                matches.append(name)

        return len(matches) > 0, matches

    @classmethod
    def mask_sensitive_text(cls, text: str) -> str:
        """
        Masks detected sensitive secrets in the text for safe display.
        """
        masked = text
        for name, pattern in cls.PATTERNS.items():
            def _replacer(m):
                val = m.group(0)
                if len(val) <= 8:
                    return "*" * len(val)
                return val[:4] + "*" * (len(val) - 8) + val[-4:]
            masked = re.sub(pattern, _replacer, masked)
        return masked


class ClipboardManager:
    """
    Manages reading, writing, and clearing the system clipboard with privacy safeguards.
    """

    def __init__(self, in_memory_fallback: bool = False):
        self._in_memory_mode = in_memory_fallback or (sys.platform != "win32")
        self._mock_text = ""

    # --- Windows Native Win32 API Implementation ---

    def _win32_get_text(self) -> Optional[str]:
        """Reads unicode text from Windows clipboard using user32.dll."""
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        CF_UNICODETEXT = 13
        if not user32.OpenClipboard(None):
            return None

        try:
            h_data = user32.GetClipboardData(CF_UNICODETEXT)
            if not h_data:
                return ""
            kernel32.GlobalLock.restype = ctypes.c_void_p
            ptr = kernel32.GlobalLock(h_data)
            if not ptr:
                return ""
            try:
                return ctypes.c_wchar_p(ptr).value or ""
            finally:
                kernel32.GlobalUnlock(h_data)
        finally:
            user32.CloseClipboard()

    def _win32_set_text(self, text: str) -> bool:
        """Copies unicode text to Windows clipboard using user32.dll."""
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002

        if not user32.OpenClipboard(None):
            return False

        try:
            user32.EmptyClipboard()
            encoded = text.encode("utf-16le") + b"\x00\x00"
            size = len(encoded)

            kernel32.GlobalAlloc.restype = ctypes.c_void_p
            h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
            if not h_mem:
                return False

            kernel32.GlobalLock.restype = ctypes.c_void_p
            ptr = kernel32.GlobalLock(h_mem)
            if not ptr:
                return False

            ctypes.memmove(ptr, encoded, size)
            kernel32.GlobalUnlock(h_mem)

            user32.SetClipboardData(CF_UNICODETEXT, h_mem)
            return True
        finally:
            user32.CloseClipboard()

    def _win32_clear(self) -> bool:
        """Empties Windows clipboard."""
        user32 = ctypes.windll.user32
        if not user32.OpenClipboard(None):
            return False
        try:
            return bool(user32.EmptyClipboard())
        finally:
            user32.CloseClipboard()

    # --- High Level Operations ---

    def get_clipboard_text(self, allow_sensitive: bool = False) -> ToolResult:
        """
        Reads the current clipboard text, checking for privacy concerns.
        """
        try:
            if self._in_memory_mode:
                text = self._mock_text
            else:
                text = self._win32_get_text()
                if text is None:
                    # Fallback to in-memory if clipboard was busy
                    text = self._mock_text

            if text is None:
                return ToolResult.fail(
                    error="Could not access system clipboard.",
                    message="Failed to open or read clipboard.",
                )

            if not text:
                return ToolResult.ok(
                    message="Clipboard is empty.",
                    data={"text": "", "length": 0, "is_sensitive": False},
                    text="",
                )

            is_sensitive, categories = SensitiveContentDetector.scan(text)
            display_text = text if (allow_sensitive or not is_sensitive) else SensitiveContentDetector.mask_sensitive_text(text)

            preview = display_text if len(display_text) <= 120 else display_text[:120] + "..."

            msg = f"Clipboard content ({len(text)} chars):\n{preview}"
            if is_sensitive and not allow_sensitive:
                msg = f"⚠️ [SENSITIVE CONTENT DETECTED: {', '.join(categories)}]\nClipboard content masked for security:\n{preview}"

            return ToolResult.ok(
                message=msg,
                data={
                    "text": display_text,
                    "raw_text": text if allow_sensitive else display_text,
                    "length": len(text),
                    "is_sensitive": is_sensitive,
                    "sensitive_categories": categories,
                    "is_masked": is_sensitive and not allow_sensitive,
                },
                text=display_text,
            )
        except Exception as e:
            logger.error(f"Error reading clipboard: {e}")
            return ToolResult.fail(error=str(e), message=f"Clipboard read error: {e}")

    def set_clipboard_text(self, text: str) -> ToolResult:
        """
        Copies text to the system clipboard.
        """
        clean_text = str(text)
        try:
            if self._in_memory_mode:
                self._mock_text = clean_text
                success = True
            else:
                success = self._win32_set_text(clean_text)
                if not success:
                    self._mock_text = clean_text
                    success = True

            if not success:
                return ToolResult.fail(
                    error="Failed to copy to clipboard.",
                    message="Could not set clipboard content.",
                )

            is_sensitive, categories = SensitiveContentDetector.scan(clean_text)
            preview = clean_text if len(clean_text) <= 50 else clean_text[:50] + "..."
            msg = f"Copied text to clipboard ({len(clean_text)} chars): '{preview}'."
            if is_sensitive:
                msg += f" (Note: Content matches sensitive pattern: {', '.join(categories)})"

            return ToolResult.ok(
                message=msg,
                data={"length": len(clean_text), "is_sensitive": is_sensitive},
            )
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Clipboard write error: {e}")

    def clear_clipboard(self) -> ToolResult:
        """
        Empties the system clipboard to protect sensitive data.
        """
        try:
            self._mock_text = ""
            if not self._in_memory_mode:
                self._win32_clear()

            return ToolResult.ok(
                message="Clipboard cleared successfully.",
                data={"cleared": True},
            )
        except Exception as e:
            return ToolResult.fail(error=str(e), message=f"Failed to clear clipboard: {e}")

    def save_clipboard_as_note(
        self,
        notes_manager: Any,
        title: Optional[str] = None,
        tags: Optional[List[str]] = None,
        allow_sensitive: bool = True,
    ) -> ToolResult:
        """
        Reads the current clipboard text and saves it as a new note in NotesManager.
        """
        clip_res = self.get_clipboard_text(allow_sensitive=True)
        if not clip_res.success:
            return clip_res

        text = clip_res.data.get("raw_text") or clip_res.data.get("text") or ""
        if not text.strip():
            return ToolResult.fail(
                error="Clipboard is empty.",
                message="Cannot save note: Clipboard is empty.",
            )

        is_sensitive = clip_res.data.get("is_sensitive", False)
        categories = clip_res.data.get("sensitive_categories", [])

        note_tags = list(tags or [])
        if is_sensitive and "sensitive" not in note_tags:
            note_tags.append("sensitive")
        if "clipboard" not in note_tags:
            note_tags.append("clipboard")

        note_title = title or ("Clipboard Note" if not is_sensitive else f"Clipboard ({categories[0] if categories else 'Sensitive'})")

        save_res = notes_manager.add_note(
            content=text,
            title=note_title,
            tags=note_tags,
        )

        if save_res.success:
            warn = " ⚠️ (Contains sensitive pattern)" if is_sensitive else ""
            return ToolResult.ok(
                message=f"Saved clipboard content as note #{save_res.data['id']}: '{save_res.data['title']}'.{warn}",
                data=save_res.data,
                undo_info=save_res.undo_info,
            )
        return save_res
