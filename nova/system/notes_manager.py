"""
Nova Notes Manager Re-export
Exposes NotesManager under nova.system for backward-compatibility and alternative imports.
"""

from nova.tools.notes import NotesManager

__all__ = ["NotesManager"]
