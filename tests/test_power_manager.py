"""
Tests for Nova PowerManager
"""

import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.system.power_manager import PowerManager


class TestPowerManager(unittest.TestCase):
    def setUp(self):
        self.pm = PowerManager()

    def test_lock_capability(self):
        """Test lock workstation capability in dry run."""
        res = self.pm.lock(dry_run=True)
        self.assertTrue(res["success"])
        self.assertTrue(res["dry_run"])
        print(f"\n[TestPowerManager] Lock validation: {res['message']}")

    def test_sleep_capability(self):
        """Test sleep capability in dry run."""
        res = self.pm.sleep(dry_run=True)
        self.assertTrue(res["success"])
        self.assertTrue(res["dry_run"])
        print(f"[TestPowerManager] Sleep validation: {res['message']}")

    def test_restart_dry_run(self):
        """Test restart command generation and parameter validation without rebooting."""
        res = self.pm.restart(delay_seconds=30, message="Nova maintenance reboot", dry_run=True)
        self.assertTrue(res["success"])
        self.assertIn("shutdown /r", res["command"])
        self.assertIn("/t 30", res["command"])
        self.assertIn("Nova maintenance reboot", res["command"])
        print(f"[TestPowerManager] Restart dry run: {res['message']}")

    def test_shutdown_dry_run(self):
        """Test shutdown command generation and parameter validation without powering down."""
        res = self.pm.shutdown(delay_seconds=60, message="Nova scheduled shutdown", dry_run=True)
        self.assertTrue(res["success"])
        self.assertIn("shutdown /s", res["command"])
        self.assertIn("/t 60", res["command"])
        self.assertIn("Nova scheduled shutdown", res["command"])
        print(f"[TestPowerManager] Shutdown dry run: {res['message']}")

    def test_abort_dry_run(self):
        """Test abort shutdown command."""
        res = self.pm.abort_shutdown(dry_run=True)
        self.assertTrue(res["success"])
        self.assertIn("shutdown /a", res["command"])
        print(f"[TestPowerManager] Abort dry run: {res['message']}")

    def test_battery_status(self):
        """Test reading battery status."""
        status = self.pm.get_battery_status()
        self.assertIn("has_battery", status)
        if status["has_battery"]:
            print(f"[TestPowerManager] Battery: {status['percent']}% ({status['status']}, {status['time_remaining']})")
        else:
            print(f"[TestPowerManager] Battery sensor: {status['message']}")


if __name__ == "__main__":
    unittest.main()
