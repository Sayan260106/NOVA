"""
Unit tests for Nova System Diagnostics (Phase 4).
Validates CPU, memory, disk, battery metrics, top resource consumers,
and slow computer analysis without terminating processes.
"""

import unittest
from unittest.mock import MagicMock

from nova.tools.system_diagnostics import SystemDiagnostics


class TestSystemDiagnostics(unittest.TestCase):
    def setUp(self):
        self.diagnostics = SystemDiagnostics()

    def test_cpu_metrics(self):
        cpu = self.diagnostics.get_cpu_info()
        self.assertIn("percent", cpu)
        self.assertIsInstance(cpu["percent"], (int, float))
        self.assertGreaterEqual(cpu["percent"], 0.0)

    def test_memory_metrics(self):
        mem = self.diagnostics.get_memory_info()
        self.assertIn("percent", mem)
        self.assertIn("total", mem)
        self.assertIn("available", mem)
        self.assertGreater(mem["total"], 0)

    def test_disk_metrics(self):
        disks = self.diagnostics.get_disk_info()
        self.assertIsInstance(disks, list)
        if disks:
            d0 = disks[0]
            self.assertIn("mount", d0)
            self.assertIn("percent", d0)

    def test_top_processes(self):
        top_cpu = self.diagnostics.get_top_processes(limit=3, sort_by="cpu")
        self.assertIsInstance(top_cpu, list)
        self.assertLessEqual(len(top_cpu), 3)
        if top_cpu:
            self.assertIn("name", top_cpu[0])
            self.assertIn("pid", top_cpu[0])
            self.assertIn("cpu_percent", top_cpu[0])

        top_mem = self.diagnostics.get_top_processes(limit=3, sort_by="memory")
        self.assertIsInstance(top_mem, list)
        self.assertLessEqual(len(top_mem), 3)

    def test_run_full_diagnostics(self):
        res = self.diagnostics.run_full_diagnostics()
        self.assertTrue(res.success)
        self.assertIn("NOVA SYSTEM DIAGNOSTICS REPORT", res.message)
        self.assertIn("cpu", res.data)
        self.assertIn("memory", res.data)

    def test_diagnose_performance_without_termination(self):
        # Must analyze performance bottlenecks and explain to user WITHOUT terminating anything
        res = self.diagnostics.diagnose_performance()
        self.assertTrue(res.success)
        self.assertIn("NOVA Performance Analysis", res.message)
        self.assertIn("No processes terminated", res.message)
        self.assertIn("Recommendation", res.message)


if __name__ == "__main__":
    unittest.main()
