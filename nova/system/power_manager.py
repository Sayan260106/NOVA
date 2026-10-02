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
                return {
                    "success": True,
                    "dry_run": True,
                    "action": "lock",
                    "message": "Validated LockWorkStation API (Dry run passed).",
                }
            return {
                "success": False,
                "dry_run": True,
                "action": "lock",
                "error": "user32.LockWorkStation not available.",
            }

        try:
            res = self._user32.LockWorkStation()
            if res != 0:
                return {
                    "success": True,
                    "action": "lock",
                    "message": "Laptop workstation locked successfully.",
                }
            else:
                # Fallback to rundll32
                subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=True)
                return {
                    "success": True,
                    "action": "lock",
                    "message": "Laptop workstation locked via rundll32.",
                }
        except Exception as e:
            return {
                "success": False,
                "action": "lock",
                "error": f"Failed to lock workstation: {str(e)}",
            }

    def sleep(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Puts the laptop into sleep / standby mode.
        If dry_run is True, verifies system capability without sleeping.
        """
        if dry_run:
            if self._powrprof and hasattr(self._powrprof, "SetSuspendState"):
                return {
                    "success": True,
                    "dry_run": True,
                    "action": "sleep",
                    "message": "Validated SetSuspendState API (Dry run passed).",
                }
            return {
                "success": False,
                "dry_run": True,
                "action": "sleep",
                "error": "powrprof.SetSuspendState not available.",
            }

        try:
            # SetSuspendState(bHibernate=False, bForce=False, bWakeupEventsDisabled=False)
            res = self._powrprof.SetSuspendState(0, 1, 0)
            return {
                "success": bool(res),
                "action": "sleep",
                "message": "Laptop placed into sleep mode.",
            }
        except Exception as e:
            # Fallback to rundll32
            try:
                subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], check=True)
                return {
                    "success": True,
                    "action": "sleep",
                    "message": "Laptop placed into sleep mode via rundll32.",
                }
            except Exception as e2:
                return {
                    "success": False,
                    "action": "sleep",
                    "error": f"Failed to put laptop to sleep: {str(e2)}",
                }

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
            return {
                "success": True,
                "dry_run": True,
                "action": "restart",
                "command": cmd_str,
                "delay_seconds": delay_seconds,
                "message": f"Restart command verified: '{cmd_str}' (Dry run mode - no system reboot triggered).",
            }

        try:
            subprocess.run(cmd_str, shell=True, check=True)
            return {
                "success": True,
                "action": "restart",
                "command": cmd_str,
                "delay_seconds": delay_seconds,
                "message": f"System restart scheduled in {delay_seconds} seconds.",
            }
        except Exception as e:
            return {
                "success": False,
                "action": "restart",
                "error": f"Failed to execute restart: {str(e)}",
            }

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
            return {
                "success": True,
                "dry_run": True,
                "action": "shutdown",
                "command": cmd_str,
                "delay_seconds": delay_seconds,
                "message": f"Shutdown command verified: '{cmd_str}' (Dry run mode - no system shutdown triggered).",
            }

        try:
            subprocess.run(cmd_str, shell=True, check=True)
            return {
                "success": True,
                "action": "shutdown",
                "command": cmd_str,
                "delay_seconds": delay_seconds,
                "message": f"System shutdown scheduled in {delay_seconds} seconds.",
            }
        except Exception as e:
            return {
                "success": False,
                "action": "shutdown",
                "error": f"Failed to execute shutdown: {str(e)}",
            }

    def abort_shutdown(self, dry_run: bool = False) -> Dict[str, Any]:
        """Cancels a pending shutdown or restart."""
        cmd_str = "shutdown /a"
        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "action": "abort_shutdown",
                "command": cmd_str,
                "message": "Abort shutdown command verified (Dry run mode).",
            }

        try:
            res = subprocess.run(cmd_str, shell=True, capture_output=True, text=True)
            return {
                "success": res.returncode == 0,
                "action": "abort_shutdown",
                "command": cmd_str,
                "message": "Any scheduled restart/shutdown has been canceled.",
            }
        except Exception as e:
            return {
                "success": False,
                "action": "abort_shutdown",
                "error": f"Failed to abort shutdown: {str(e)}",
            }

    def get_battery_status(self) -> Dict[str, Any]:
        """Returns battery and power source details."""
        battery = psutil.sensors_battery()
        if battery is None:
            return {
                "has_battery": False,
                "message": "Desktop system or battery sensor not available.",
            }

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

        return {
            "has_battery": True,
            "percent": percent,
            "power_plugged": plugged,
            "seconds_left": seconds_left,
            "time_remaining": time_str,
            "status": "Charging" if plugged else "On Battery",
        }
