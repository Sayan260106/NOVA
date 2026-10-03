"""
Nova Interactive CLI Interface
Provides a rich command-line experience for interacting with Nova virtual assistant.
"""

import sys
import os
import argparse
from typing import Optional

from nova.agent.brain import NovaBrain
from nova.agent.intent_parser import NovaIntent
from nova.config import LANGUAGE_CHART

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


BANNER = r"""
==========================================================================
    _   ______  _    _____    __    _       _____  ___  ______
   / | / / __ \/ |  / /   |  / /   (_)     / /   |/ _ \/  ___/
  /  |/ / / / / /| / / /| | / /   / / __  / / /| / //_/\__ \ 
 / /|  / /_/ / ___/ / ___ |/ /___/ / /_/ / / ___/ _  \ ___/ / 
/_/ |_/\____/_/  /_/_/  |_/_____/_/\____/_/_/  |_\___//____/  
==========================================================================
              JARVIS-Class Virtual Assistant System
"""


def format_search_results(results):
    if not results:
        return "  No matching items found."
    lines = []
    for idx, r in enumerate(results, 1):
        kind = r.get("kind", "item")
        name = r.get("name", "unknown")
        if kind == "application":
            source = r.get("source", "system")
            conf = r.get("confidence", 1.0)
            lines.append(f"  [{idx}] 🖥️  App: {name:<25} (Source: {source}, Confidence: {conf})")
        elif kind == "folder":
            path = r.get("path", "")
            lines.append(f"  [{idx}] 📁 Folder: {name:<22} -> {path}")
        else:
            path = r.get("path", "")
            size = r.get("size", 0)
            size_kb = f"{size / 1024:.1f} KB" if size > 1024 else f"{size} B"
            lines.append(f"  [{idx}] 📄 File: {name:<24} ({size_kb}) -> {path}")
    return "\n".join(lines)


def run_cli(dry_run_power: bool = True):
    print(BANNER)
    print("Initializing Nova Core systems... Please wait.")
    brain = NovaBrain(dry_run_power=dry_run_power)
    brain.initialize()

    # Preload status
    app_count = len(brain.app_manager._apps)
    batt = brain.power_manager.get_battery_status()
    batt_str = f"{batt['percent']}% ({batt['status']})" if batt.get("has_battery") else "N/A"

    print(f"\n[Nova Online]")
    print(f" • Installed Applications Cataloged: {app_count}")
    print(f" • Power / Battery Status: {batt_str}")
    print(f" • Local Brain Intelligence (Ollama): {'Active (' + brain.ollama.model_name + ')' if brain.ollama.is_available() else 'Offline (Rule Engine Active)'}")
    print(f" • Power Operations Mode: {'DRY RUN (Safe)' if dry_run_power else 'ACTIVE SYSTEM EXECUTION'}")
    print(f" • Type 'help' for examples or 'exit' to quit.\n")

    while True:
        try:
            user_input = input("Nova ❯ ").strip()
            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "bye", "shutdown nova"):
                print("\nNova: Shutting down virtual assistant systems. Goodbye, sir.\n")
                break

            # Confirm real restart or shutdown if not in dry-run mode
            lower_input = user_input.lower()
            if not dry_run_power and any(w in lower_input for w in ["shutdown", "shut down", "restart", "reboot"]):
                confirm = input(f"Nova: Confirmation required for power action: '{user_input}'. Proceed? [y/N]: ").strip().lower()
                if confirm not in ("y", "yes"):
                    print("Nova: Power operation canceled.")
                    continue

            parsed = brain.intent_parser.parse(user_input)
            intent = parsed.get("intent")

            # Handle interactive deletion with duplicate disambiguation and confirmation
            if intent == NovaIntent.DELETE_ITEM:
                target_name = parsed["name"]
                is_dir = parsed.get("is_dir")
                permanent = parsed.get("permanent", False)

                prep = brain.prepare_deletion(target_name, is_dir=is_dir)
                if prep["status"] == "not_found":
                    print(f"Nova: {prep['message']}\n")
                    continue

                candidates = prep["candidates"]
                selected_target = None

                if len(candidates) > 1:
                    print(f"\nNova: Found {len(candidates)} items with the name '{target_name}':")
                    for idx, c in enumerate(candidates, 1):
                        ctype = "📁 Folder" if c.is_dir() else "📄 File"
                        try:
                            stat = c.stat()
                            size_str = f"{stat.st_size} bytes" if not c.is_dir() else "directory"
                        except OSError:
                            size_str = ""
                        print(f"  [{idx}] {ctype}: {c} ({size_str})")

                    sel = input(f"\nNova: Which one would you like to delete? [1-{len(candidates)}] (or 'c' to cancel): ").strip()
                    if sel.lower() in ("c", "cancel", "no", "n"):
                        print("Nova: Deletion canceled.\n")
                        continue
                    try:
                        chosen_idx = int(sel) - 1
                        if 0 <= chosen_idx < len(candidates):
                            selected_target = candidates[chosen_idx]
                        else:
                            print("Nova: Invalid selection. Deletion canceled.\n")
                            continue
                    except ValueError:
                        print("Nova: Invalid input. Deletion canceled.\n")
                        continue
                else:
                    selected_target = candidates[0]

                # Confirmation prompt
                target_type = "folder" if selected_target.is_dir() else "file"
                confirm = input(f"Nova: Are you sure you want to delete {target_type} '{selected_target.name}' at '{selected_target}'? [y/N]: ").strip().lower()
                if confirm in ("y", "yes"):
                    del_res = brain.execute_deletion(selected_target, permanent=permanent)
                    print(f"Nova: {del_res.get('message', 'Item deleted.')}\n")
                else:
                    print("Nova: Deletion canceled.\n")
                continue

            # Handle interactive open with duplicate disambiguation and confirmation
            if intent in (NovaIntent.OPEN_APP, NovaIntent.OPEN_ITEM):
                target_name = parsed["name"]
                kind = parsed.get("kind")
                is_dir = True if kind in ("folder", "directory") else (False if kind == "file" else None)

                prep = brain.prepare_open(target_name, is_dir=is_dir, kind=kind)
                if prep["status"] == "not_found":
                    print(f"Nova: {prep['message']}\n")
                    continue

                candidates = prep["candidates"]
                selected_candidate = None

                if len(candidates) > 1:
                    print(f"\nNova: Found {len(candidates)} items with the name '{target_name}':")
                    for idx, c in enumerate(candidates, 1):
                        if c.is_dir():
                            ctype = "📁 Folder"
                        elif c.is_file():
                            ctype = "📄 File"
                        else:
                            ctype = "🖥️  App"
                        try:
                            stat = c.stat()
                            size_str = f" ({stat.st_size} bytes)" if c.is_file() else ""
                        except (OSError, AttributeError):
                            size_str = ""
                        print(f"  [{idx}] {ctype}: {c.name} -> {c.path}{size_str}")

                    sel = input(f"\nNova: Which one would you like to open? [1-{len(candidates)}] (or 'c' to cancel): ").strip()
                    if sel.lower() in ("c", "cancel", "no", "n"):
                        print("Nova: Open operation canceled.\n")
                        continue
                    try:
                        chosen_idx = int(sel) - 1
                        if 0 <= chosen_idx < len(candidates):
                            selected_candidate = candidates[chosen_idx]
                        else:
                            print("Nova: Invalid selection. Open operation canceled.\n")
                            continue
                    except ValueError:
                        print("Nova: Invalid input. Open operation canceled.\n")
                        continue
                else:
                    selected_candidate = candidates[0]

                # Confirmation prompt
                ctype_name = "folder" if selected_candidate.is_dir() else ("file" if selected_candidate.is_file() else "application")
                confirm = input(f"Nova: Confirm opening {ctype_name} '{selected_candidate.name}' at '{selected_candidate.path}'? [Y/n]: ").strip().lower()
                if confirm in ("", "y", "yes"):
                    open_res = brain.execute_open(selected_candidate)
                    if open_res.get("success"):
                        print(f"Nova: {open_res.get('message', f'Opened {selected_candidate.name}.')}\n")
                    else:
                        print(f"Nova: Failed to open: {open_res.get('error', 'Unknown error')}\n")
                else:
                    print("Nova: Open operation canceled.\n")
                continue

            result = brain.process(user_input)

            # Display response
            intent = result.get("intent")
            if intent == NovaIntent.FIND_ITEM:
                print(f"\nNova: {result['response']}")
                print(format_search_results(result.get("results", [])))
                print()
            elif intent == NovaIntent.LANGUAGE_CHART:
                print(f"\nNova:\n{result['response']}\n")
            elif intent == NovaIntent.HELP:
                print(f"\n{result['response']}\n")
            elif intent == NovaIntent.SUMMARIZE:
                print(f"\nNova: {result['response']}\n")
            elif intent == NovaIntent.COMPLEX_COMMAND:
                print(f"\nNova: Executed multi-step command:\n{result['response']}\n")
            else:
                resp = result.get("response", "Done.")
                prefix = "Nova: "
                print(f"{prefix}{resp}\n")

        except KeyboardInterrupt:
            print("\nNova: Session interrupted. Exiting.")
            break
        except Exception as e:
            print(f"Nova Error: {str(e)}\n")


def main():
    parser = argparse.ArgumentParser(description="Nova JARVIS-like Virtual Assistant")
    parser.add_argument(
        "--live-power",
        action="store_true",
        help="Enable live system power operations (lock, sleep, restart, shutdown). Default is safe dry-run mode.",
    )
    args = parser.parse_args()
    run_cli(dry_run_power=not args.live_power)


if __name__ == "__main__":
    main()
