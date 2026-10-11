"""
Nova System Diagnostics
Reports CPU, memory, disk usage, battery health, running processes,
and analyzes why the system might be running slowly without terminating processes.
"""

import sys
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

from nova.core.results import ToolResult
from nova.config import AVAILABLE_DRIVES

logger = logging.getLogger("nova.tools.diagnostics")


class SystemDiagnostics:
    """
    Inspects hardware resources, running tasks, and provides intelligent performance diagnostics.
    """

    def __init__(self, power_manager: Optional[Any] = None):
        self.power_manager = power_manager

    def _format_bytes(self, num_bytes: float) -> str:
        """Formats byte quantities into human-readable strings."""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if abs(num_bytes) < 1024.0:
                return f"{num_bytes:.1f} {unit}"
            num_bytes /= 1024.0
        return f"{num_bytes:.1f} PB"

    def get_cpu_info(self) -> Dict[str, Any]:
        """Collects CPU metrics."""
        if not psutil:
            return {"error": "psutil library not available"}
        try:
            percent = psutil.cpu_percent(interval=0.1)
            cores = psutil.cpu_count(logical=False) or 1
            logical = psutil.cpu_count(logical=True) or 1
            return {
                "percent": percent,
                "physical_cores": cores,
                "logical_cores": logical,
            }
        except Exception as e:
            return {"error": str(e), "percent": 0.0}

    def get_memory_info(self) -> Dict[str, Any]:
        """Collects RAM memory metrics."""
        if not psutil:
            return {"error": "psutil library not available"}
        try:
            vm = psutil.virtual_memory()
            return {
                "total": vm.total,
                "total_str": self._format_bytes(vm.total),
                "available": vm.available,
                "available_str": self._format_bytes(vm.available),
                "used": vm.used,
                "used_str": self._format_bytes(vm.used),
                "percent": vm.percent,
            }
        except Exception as e:
            return {"error": str(e), "percent": 0.0}

    def get_disk_info(self) -> List[Dict[str, Any]]:
        """Collects disk usage across existing drives."""
        disks = []
        if not psutil:
            return disks
        try:
            partitions = psutil.disk_partitions(all=False)
            seen_mounts = set()
            for part in partitions:
                mount = part.mountpoint
                if mount in seen_mounts or "cdrom" in part.opts:
                    continue
                seen_mounts.add(mount)
                try:
                    usage = psutil.disk_usage(mount)
                    disks.append({
                        "device": part.device,
                        "mount": mount,
                        "fstype": part.fstype,
                        "total": usage.total,
                        "total_str": self._format_bytes(usage.total),
                        "used": usage.used,
                        "used_str": self._format_bytes(usage.used),
                        "free": usage.free,
                        "free_str": self._format_bytes(usage.free),
                        "percent": usage.percent,
                    })
                except (PermissionError, OSError):
                    pass
        except Exception as e:
            logger.debug(f"Error querying disk info: {e}")
        return disks

    def get_battery_info(self) -> Dict[str, Any]:
        """Collects battery metrics."""
        if self.power_manager:
            return self.power_manager.get_battery_status()
        if not psutil:
            return {"has_battery": False, "message": "psutil not available"}
        try:
            batt = psutil.sensors_battery()
            if not batt:
                return {"has_battery": False, "message": "Desktop system / No battery detected"}
            return {
                "has_battery": True,
                "percent": batt.percent,
                "charging": batt.power_plugged,
                "seconds_left": batt.secsleft if batt.secsleft > 0 else None,
            }
        except Exception as e:
            return {"has_battery": False, "error": str(e)}

    def get_top_processes(self, limit: int = 5, sort_by: str = "cpu") -> List[Dict[str, Any]]:
        """
        Retrieves top processes sorted by CPU or memory usage.
        """
        if not psutil:
            return []

        procs = []
        # Query active processes
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "memory_percent"]):
            try:
                info = p.info
                name = info.get("name") or "Unknown"
                # Exclude System Idle Process from top CPU consumer list
                if "idle" in name.lower():
                    continue
                mem_rss = info.get("memory_info").rss if info.get("memory_info") else 0
                procs.append({
                    "pid": info["pid"],
                    "name": name,
                    "cpu_percent": info.get("cpu_percent") or 0.0,
                    "memory_bytes": mem_rss,
                    "memory_str": self._format_bytes(mem_rss),
                    "memory_percent": round(info.get("memory_percent") or 0.0, 1),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if sort_by == "memory":
            procs.sort(key=lambda x: x["memory_bytes"], reverse=True)
        else:
            procs.sort(key=lambda x: x["cpu_percent"], reverse=True)

        return procs[:limit]

    def run_full_diagnostics(self) -> ToolResult:
        """Runs a comprehensive diagnostic overview."""
        cpu = self.get_cpu_info()
        mem = self.get_memory_info()
        disks = self.get_disk_info()
        battery = self.get_battery_info()
        top_cpu = self.get_top_processes(limit=5, sort_by="cpu")
        top_mem = self.get_top_processes(limit=5, sort_by="memory")

        lines = ["=================================================="]
        lines.append("        NOVA SYSTEM DIAGNOSTICS REPORT")
        lines.append("==================================================")
        lines.append(f" • CPU Usage:    {cpu.get('percent', 0.0)}% ({cpu.get('logical_cores', 1)} cores)")
        lines.append(f" • RAM Usage:    {mem.get('percent', 0.0)}% ({mem.get('used_str', '0 B')} / {mem.get('total_str', '0 B')})")

        if battery.get("has_battery"):
            state = "Charging" if battery.get("charging") else "Discharging"
            lines.append(f" • Battery:      {battery.get('percent')}% ({state})")

        lines.append("\n[Storage Usage]:")
        for d in disks:
            lines.append(f" • {d['mount']} ({d['device']}): {d['percent']}% used ({d['free_str']} free of {d['total_str']})")

        lines.append("\n[Top Processes by CPU]:")
        for p in top_cpu:
            lines.append(f" • {p['name']} (PID: {p['pid']}): {p['cpu_percent']}% CPU, {p['memory_str']} RAM")

        lines.append("\n[Top Processes by Memory]:")
        for p in top_mem:
            lines.append(f" • {p['name']} (PID: {p['pid']}): {p['memory_str']} ({p['memory_percent']}%)")

        return ToolResult.ok(
            message="\n".join(lines),
            data={
                "cpu": cpu,
                "memory": mem,
                "disks": disks,
                "battery": battery,
                "top_cpu_processes": top_cpu,
                "top_memory_processes": top_mem,
            },
        )

    def diagnose_performance(self) -> ToolResult:
        """
        Specialized analysis for 'Check why my computer is running slowly'.
        Analyzes CPU, RAM, disk bottlenecks, and lists significant consumers
        without terminating any process.
        """
        cpu = self.get_cpu_info()
        mem = self.get_memory_info()
        disks = self.get_disk_info()
        top_cpu = self.get_top_processes(limit=5, sort_by="cpu")
        top_mem = self.get_top_processes(limit=5, sort_by="memory")

        bottlenecks = []
        cpu_pct = cpu.get("percent", 0.0)
        mem_pct = mem.get("percent", 0.0)

        if cpu_pct > 80.0:
            bottlenecks.append(f"High CPU utilization ({cpu_pct}%)")
        if mem_pct > 85.0:
            bottlenecks.append(f"High Memory pressure ({mem_pct}% used)")

        for d in disks:
            if d["percent"] > 90.0:
                bottlenecks.append(f"Drive {d['mount']} is nearly full ({d['percent']}%)")

        lines = ["NOVA Performance Analysis:"]
        if not bottlenecks:
            lines.append("✓ System resource utilization is within healthy, normal ranges.")
            lines.append(f"  Current Load: CPU at {cpu_pct}%, Memory at {mem_pct}%.")
        else:
            lines.append("⚠️ Detected potential system performance bottlenecks:")
            for b in bottlenecks:
                lines.append(f"  - {b}")

        lines.append("\nKey Resource Consumers (Informational - No processes terminated):")

        # Significant consumers
        significant = []
        for p in top_cpu:
            if p["cpu_percent"] >= 5.0:
                significant.append(f" • {p['name']} (PID: {p['pid']}): {p['cpu_percent']}% CPU")
        for p in top_mem:
            # Memory > 400 MB
            if p["memory_bytes"] >= 400 * 1024 * 1024 and not any(str(p["pid"]) in s for s in significant):
                significant.append(f" • {p['name']} (PID: {p['pid']}): {p['memory_str']} RAM")

        if significant:
            lines.extend(significant)
        else:
            lines.append(" • All active processes are consuming modest resources.")

        lines.append("\nRecommendation:")
        if cpu_pct > 80.0:
            lines.append(" Consider closing background intensive apps or browser tabs with heavy scripts.")
        elif mem_pct > 85.0:
            lines.append(" Closing unused applications will free up physical memory and reduce paging.")
        else:
            lines.append(" System is operating normally. If a specific app feels slow, check its responsiveness.")

        return ToolResult.ok(
            message="\n".join(lines),
            data={
                "cpu_percent": cpu_pct,
                "memory_percent": mem_pct,
                "bottlenecks": bottlenecks,
                "top_cpu": top_cpu,
                "top_memory": top_mem,
            },
        )
