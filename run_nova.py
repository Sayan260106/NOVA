"""
Nova Entry Point
Run this script to start the interactive Nova Assistant CLI:
  python run_nova.py
Or with live power commands enabled:
  python run_nova.py --live-power
"""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from nova.cli import main

if __name__ == "__main__":
    main()
