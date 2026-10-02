"""
Nova Verification Suite
Executes and validates all user checkpoints in a live simulation,
including D: drive default creation, specific folder resolution, rename, and all-drive search.
"""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.agent.brain import NovaBrain
from nova.agent.intent_parser import NovaIntent


def run_verification():
    print("=" * 65)
    print(" NOVA JARVIS ASSISTANT - COMPREHENSIVE VERIFICATION")
    print("=" * 65)

    brain = NovaBrain(dry_run_power=True)
    brain.initialize()

    # Pre-test cleanup of test artifacts from previous runs
    import shutil
    from nova.config import DEFAULT_WORKSPACE
    for test_dir in ["JarvisVault", "SecondaryVault", "DualTarget", "ConflictDirA", "ConflictDirB"]:
        p = DEFAULT_WORKSPACE / test_dir
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
            brain.indexer.remove_item(p)
    for test_file in ["DualTarget.txt", "mission_brief.txt", "operation_brief.txt", "clash_item.txt"]:
        p = DEFAULT_WORKSPACE / test_file
        if p.exists():
            try:
                p.unlink()
                brain.indexer.remove_item(p)
            except OSError:
                pass

    checkpoints = [
        # Checkpoint A: Open application
        ("Checkpoint A: Application Opening", [
            ("open calculator", NovaIntent.OPEN_APP),
            ("launch notepad", NovaIntent.OPEN_APP),
            ("open settings", NovaIntent.OPEN_APP),
        ]),

        # Checkpoint B: Creation in D: drive (default) & specific folder
        ("Checkpoint B: Folder & File Creation (D: drive default & specific folder)", [
            ("create folder JarvisVault", NovaIntent.CREATE_FOLDER),
            ("create folder DeepArchive inside JarvisVault", NovaIntent.CREATE_FOLDER),
            ("create file mission_brief.txt with content 'Project Nova is online' inside DeepArchive", NovaIntent.CREATE_FILE),
        ]),

        # Checkpoint C: Rename Option for Files & Folders
        ("Checkpoint C: Rename Option (Files & Folders)", [
            ("rename file mission_brief.txt to operation_brief.txt", NovaIntent.RENAME_ITEM),
            ("rename folder DeepArchive to ClassifiedArchive", NovaIntent.RENAME_ITEM),
        ]),

        # Checkpoint D: Zero-path File & Folder Management (Copy, Move, Delete)
        ("Checkpoint D: Zero-path File & Folder Management", [
            ("copy file operation_brief.txt to JarvisVault", NovaIntent.COPY_ITEM),
            ("create folder SecondaryVault", NovaIntent.CREATE_FOLDER),
            ("move file operation_brief.txt to SecondaryVault", NovaIntent.MOVE_ITEM),
            ("delete file operation_brief.txt permanently", NovaIntent.DELETE_ITEM),
            ("delete folder ClassifiedArchive permanently", NovaIntent.DELETE_ITEM),
            ("delete folder SecondaryVault permanently", NovaIntent.DELETE_ITEM),
            ("delete folder JarvisVault permanently", NovaIntent.DELETE_ITEM),
        ]),

        # Checkpoint D2: Same-name Disambiguation for Deletion and Opening
        ("Checkpoint D2: Duplicate Name Disambiguation (Open & Delete)", [
            ("create folder DualTarget", NovaIntent.CREATE_FOLDER),
            ("create file DualTarget.txt with content 'Same name content' in D: drive", NovaIntent.CREATE_FILE),
            ("create folder ConflictDirA", NovaIntent.CREATE_FOLDER),
            ("create folder ConflictDirB", NovaIntent.CREATE_FOLDER),
            ("create file clash_item.txt with content 'Item A' inside ConflictDirA", NovaIntent.CREATE_FILE),
            ("create file clash_item.txt with content 'Item B' inside ConflictDirB", NovaIntent.CREATE_FILE),
        ]),

        # Checkpoint E: Universal Search across File Explorer (Files, Folders, Apps)
        ("Checkpoint E: Universal Search across File Explorer (Files, Folders, Apps)", [
            ("find app chrome", NovaIntent.FIND_ITEM),
            ("find app notepad", NovaIntent.FIND_ITEM),
            ("find folder Documents", NovaIntent.FIND_ITEM),
            ("find file run_nova.py", NovaIntent.FIND_ITEM),
        ]),

        # Checkpoint F: Power & Session Operations (Dry Run Mode)
        ("Checkpoint F: Power & Session Operations (Dry Run Mode)", [
            ("lock laptop", NovaIntent.LOCK_SYSTEM),
            ("put laptop to sleep", NovaIntent.SLEEP_SYSTEM),
            ("restart laptop in 60 seconds", NovaIntent.RESTART_SYSTEM),
            ("shutdown laptop in 90 seconds", NovaIntent.SHUTDOWN_SYSTEM),
            ("cancel shutdown", NovaIntent.ABORT_POWER),
            ("battery status", NovaIntent.BATTERY_STATUS),
        ]),

        # Memory Check: Language Architecture Chart
        ("Memory Check: JARVIS Component Language Architecture Chart", [
            ("show language chart", NovaIntent.LANGUAGE_CHART),
        ]),
    ]

    all_passed = True
    total_commands = 0
    passed_commands = 0

    for section_title, commands in checkpoints:
        print(f"\n--- {section_title} ---")
        for utterance, expected_intent in commands:
            total_commands += 1
            result = brain.process(utterance)
            actual_intent = result.get("intent")
            success = result.get("success", False)

            status = "PASS" if (success and actual_intent == expected_intent) else "FAIL"
            if status == "FAIL":
                all_passed = False
            else:
                passed_commands += 1

            print(f"[{status}] Command: '{utterance}'")
            print(f"       Intent:  {actual_intent}")
            print(f"       Outcome: {result.get('response')}")
            if "results" in result and result["results"]:
                top = result["results"][0]
                print(f"       Top Match: {top.get('name')} ({top.get('kind', 'item')})")

    # Explicit Disambiguation Logic Validation
    print("\n--- Live Disambiguation Multi-Candidate Checks ---")
    
    # 1. Open Disambiguation Check
    total_commands += 1
    open_prep = brain.prepare_open("DualTarget")
    if open_prep["status"] == "multiple" and len(open_prep["candidates"]) >= 2:
        print("[PASS] Open Disambiguation: Identified folder & file candidates for 'DualTarget':")
        for c in open_prep["candidates"]:
            print(f"       • {c.kind.capitalize()}: {c.path}")
        passed_commands += 1
    else:
        print(f"[FAIL] Open Disambiguation: Expected multiple candidates, got {open_prep}")
        all_passed = False

    # 2. Deletion Disambiguation Check
    total_commands += 1
    del_prep = brain.prepare_deletion("clash_item.txt")
    if del_prep["status"] == "multiple" and len(del_prep["candidates"]) == 2:
        print("[PASS] Deletion Disambiguation: Identified duplicate paths for 'clash_item.txt':")
        for c in del_prep["candidates"]:
            print(f"       • Path: {c}")
        passed_commands += 1
        # Execute selective deletion
        brain.execute_deletion(del_prep["candidates"][0], permanent=True)
        # Verify second still exists
        total_commands += 1
        if del_prep["candidates"][1].exists():
            print("[PASS] Verified selective deletion: Candidate 1 deleted, Candidate 2 preserved.")
            passed_commands += 1
        else:
            print("[FAIL] Both candidates were deleted unexpectedly.")
            all_passed = False
    else:
        print(f"[FAIL] Deletion Disambiguation: Expected 2 candidates, got {del_prep}")
        all_passed = False

    # Cleanup temporary test items
    brain.process("delete file DualTarget.txt permanently")
    brain.process("delete folder DualTarget permanently")
    brain.process("delete file clash_item.txt permanently")
    brain.process("delete folder ConflictDirA permanently")
    brain.process("delete folder ConflictDirB permanently")

    # Cleanup any test notepad / calculator windows
    import psutil
    for p in psutil.process_iter(['name']):
        try:
            pname = (p.info['name'] or '').lower()
            if any(x in pname for x in ['notepad.exe', 'calculator.exe', 'calculatorapp.exe']):
                p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    print("\n" + "=" * 65)
    print(f"VERIFICATION SUMMARY: {passed_commands}/{total_commands} passed.")
    print("STATUS: " + ("ALL CHECKPOINTS SATISFIED PROPERLY" if all_passed else "CHECKPOINTS FAILED"))
    print("=" * 65)

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    run_verification()
