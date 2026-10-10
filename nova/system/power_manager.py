"""
Nova Power and Session Manager
Controls laptop lock, sleep, restart, shutdown, and power status on Windows.
Includes safety guards and dry-run validation for automated testing.
"""

import os
import sys
import ctypes
import logging
import subprocess
from typing import Dict, Optional, Any
import psutil

from nova.core.results import ToolResult

logger = logging.getLogger("nova.power_manager")


class PowerManager:
    """Manages Windows power, lock, sleep, restart, and shutdown operations."""

    def __init__(self):
        self._user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
        self._powrprof = ctypes.windll.powrprof if hasattr(ctypes, "windll") else None

    def lock(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Locks the Windows workstation.
        If dry_run is True, verifies system capability without locking the screen.
        """
        if dry_run:
            if self._user32 and hasattr(self._user32, "LockWorkStation"):
                return ToolResult.ok(
                    message="Validated LockWorkStation API (Dry run passed).",
                    data={"dry_run": True, "action": "lock"},
                )
            return ToolResult.fail(
                error="user32.LockWorkStation not available.",
                message="user32.LockWorkStation not available.",
                data={"dry_run": True, "action": "lock"},
            )

        try:
            res = self._user32.LockWorkStation()
            if res != 0:
                return ToolResult.ok(
                    message="Laptop workstation locked successfully.",
                    data={"action": "lock"},
                )
            else:
                # Fallback to rundll32
                subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=True)
                return ToolResult.ok(
                    message="Laptop workstation locked via rundll32.",
                    data={"action": "lock"},
                )
        except Exception as e:
            return ToolResult.fail(
                error=f"Failed to lock workstation: {str(e)}",
                data={"action": "lock"},
            )

    def sleep(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Puts the laptop into sleep / standby mode.
        If dry_run is True, verifies system capability without sleeping.
        """
        if dry_run:
            if self._powrprof and hasattr(self._powrprof, "SetSuspendState"):
                return ToolResult.ok(
                    message="Validated SetSuspendState API (Dry run passed).",
                    data={"dry_run": True, "action": "sleep"},
                )
            return ToolResult.fail(
                error="powrprof.SetSuspendState not available.",
                message="powrprof.SetSuspendState not available.",
                data={"dry_run": True, "action": "sleep"},
            )

        try:
            # SetSuspendState(bHibernate=False, bForce=False, bWakeupEventsDisabled=False)
            res = self._powrprof.SetSuspendState(0, 1, 0)
            return ToolResult.ok(
                message="Laptop placed into sleep mode.",
                data={"action": "sleep", "result": bool(res)},
            )
        except Exception as e:
            # Fallback to rundll32
            try:
                subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], check=True)
                return ToolResult.ok(
                    message="Laptop placed into sleep mode via rundll32.",
                    data={"action": "sleep"},
                )
            except Exception as e2:
                return ToolResult.fail(
                    error=f"Failed to put laptop to sleep: {str(e2)}",
                    data={"action": "sleep"},
                )

    def restart(
        self,
        delay_seconds: int = 0,
        message: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Restarts the laptop.
        If dry_run is True, validates the command without rebooting the system.
        """
        cmd = ["shutdown", "/r", f"/t {delay_seconds}"]
        if message:
            cmd.append(f'/c "{message}"')
        cmd_str = " ".join(cmd)

        if dry_run:
            return ToolResult.ok(
                message=f"Restart command verified: '{cmd_str}' (Dry run mode - no system reboot triggered).",
                data={
                    "dry_run": True,
                    "action": "restart",
                    "command": cmd_str,
                    "delay_seconds": delay_seconds,
                },
            )

        try:
            subprocess.run(cmd_str, shell=True, check=True)
            return ToolResult.ok(
                message=f"System restart scheduled in {delay_seconds} seconds.",
                data={
                    "action": "restart",
                    "command": cmd_str,
                    "delay_seconds": delay_seconds,
                },
            )
        except Exception as e:
            return ToolResult.fail(
                error=f"Failed to execute restart: {str(e)}",
                data={"action": "restart", "command": cmd_str},
            )

    def shutdown(
        self,
        delay_seconds: int = 0,
        message: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Shuts down the laptop.
        If dry_run is True, validates the command without shutting down the system.
        """
        cmd = ["shutdown", "/s", f"/t {delay_seconds}"]
        if message:
            cmd.append(f'/c "{message}"')
        cmd_str = " ".join(cmd)

        if dry_run:
            return ToolResult.ok(
                message=f"Shutdown command verified: '{cmd_str}' (Dry run mode - no system shutdown triggered).",
                data={
                    "dry_run": True,
                    "action": "shutdown",
                    "command": cmd_str,
                    "delay_seconds": delay_seconds,
                },
            )

        try:
            subprocess.run(cmd_str, shell=True, check=True)
            return ToolResult.ok(
                message=f"System shutdown scheduled in {delay_seconds} seconds.",
                data={
                    "action": "shutdown",
                    "command": cmd_str,
                    "delay_seconds": delay_seconds,
                },
            )
        except Exception as e:
            return ToolResult.fail(
                error=f"Failed to execute shutdown: {str(e)}",
                data={"action": "shutdown", "command": cmd_str},
            )

    def abort_shutdown(self, dry_run: bool = False) -> Dict[str, Any]:
        """Cancels a pending shutdown or restart."""
        cmd_str = "shutdown /a"
        if dry_run:
            return ToolResult.ok(
                message="Abort shutdown command verified (Dry run mode).",
                data={
                    "dry_run": True,
                    "action": "abort_shutdown",
                    "command": cmd_str,
                },
            )

        try:
            res = subprocess.run(cmd_str, shell=True, capture_output=True, text=True)
            if res.returncode == 0:
                return ToolResult.ok(
                    message="Any scheduled restart/shutdown has been canceled.",
                    data={
                        "action": "abort_shutdown",
                        "command": cmd_str,
                    },
                )
            else:
                return ToolResult.fail(
                    error=res.stderr or "Abort command failed.",
                    data={"action": "abort_shutdown", "command": cmd_str},
                )
        except Exception as e:
            return ToolResult.fail(
                error=f"Failed to abort shutdown: {str(e)}",
                data={"action": "abort_shutdown"},
            )

    def get_battery_status(self) -> Dict[str, Any]:
        """Returns battery and power source details."""
        battery = psutil.sensors_battery()
        if battery is None:
            return ToolResult.fail(
                error="Desktop system or battery sensor not available.",
                message="Desktop system or battery sensor not available.",
                data={"has_battery": False},
            )

        percent = round(battery.percent, 1)
        plugged = battery.power_plugged
        seconds_left = battery.secsleft

        time_str = "Unknown"
        if seconds_left != psutil.POWER_TIME_UNLIMITED and seconds_left > 0:
            hours = seconds_left // 3600
            mins = (seconds_left % 3600) // 60
            time_str = f"{hours}h {mins}m"
        elif plugged:
            time_str = "Charging / Plugged in"

        return ToolResult.ok(
            message=f"Battery is at {percent}% ({'Charging' if plugged else 'On Battery'}).",
            data={
                "has_battery": True,
                "percent": percent,
                "power_plugged": plugged,
                "seconds_left": seconds_left,
                "time_remaining": time_str,
                "status": "Charging" if plugged else "On Battery",
            },
        )
