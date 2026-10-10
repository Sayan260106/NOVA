"""
Nova Standardized Tool Results
Establishes a unified, machine-readable result format across all tools,
managers, and executors in Nova.
"""

from typing import Dict, Any, Optional


class ToolResult(dict):
    """
    Standardized result structure for all NOVA tools, managers, and executors.
    Contains:
    - success: bool
    - message: str
    - data: Dict[str, Any]
    - error: Optional[str]
    - undo_info: Optional[Dict[str, Any]]

    Inherits from dict to ensure 100% backward compatibility with all existing
    callers, tests, and serializers expecting dictionary mapping behavior.
    """

    def __init__(
        self,
        success: bool,
        message: str = "",
        data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        undo_info: Optional[Dict[str, Any]] = None,
        **extra_data: Any,
    ):
        clean_data = dict(data or {})
        clean_data.update(extra_data)

        # Initialize dict with standard contract fields and flattened data fields
        super().__init__(
            success=success,
            message=message,
            data=clean_data,
            error=error,
            undo_info=undo_info,
            **clean_data,
        )
        self.success = success
        self.message = message
        self.data = clean_data
        self.error = error
        self.undo_info = undo_info

    @classmethod
    def ok(
        cls,
        message: str = "",
        data: Optional[Dict[str, Any]] = None,
        undo_info: Optional[Dict[str, Any]] = None,
        **extra: Any,
    ) -> "ToolResult":
        """Factory for successful tool outcomes."""
        return cls(
            success=True,
            message=message,
            data=data,
            error=None,
            undo_info=undo_info,
            **extra,
        )

    @classmethod
    def fail(
        cls,
        error: str,
        message: str = "",
        data: Optional[Dict[str, Any]] = None,
        **extra: Any,
    ) -> "ToolResult":
        """Factory for failed tool outcomes."""
        msg = message or error
        return cls(
            success=False,
            message=msg,
            data=data,
            error=error,
            undo_info=None,
            **extra,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Returns standard dictionary representation."""
        return dict(self)

    def __repr__(self) -> str:
        status = "OK" if self.success else "FAIL"
        err_str = f", error={self.error!r}" if self.error else ""
        return f"<ToolResult [{status}]: {self.message!r}{err_str}>"
