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
    for test_dir in ["JarvisVault", "SecondaryVault", "DualTarget", "ConflictDirA", "ConflictDirB", "Project", "TestSuite", "SummaryVault"]:
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

        # Checkpoint G: Complex & Compound Command Execution (Multi-Step Intent Understanding)
        ("Checkpoint G: Complex & Compound Command Execution (Goal a)", [
            ("Make a folder 'Demo' in Project folder and create a file 'xyz.txt'", NovaIntent.COMPLEX_COMMAND),
            ("create folder TestSuite in D: drive and create file results.txt with content 'Project Nova verification complete' inside TestSuite", NovaIntent.COMPLEX_COMMAND),
        ]),

        # Checkpoint H: Summarization (Text, File, Context - Zero API Keys, Local Ollama / Offline)
        ("Checkpoint H: Summarization Capabilities (Goal b - Local / Offline)", [
            ("summarize this text: Quantum computing uses qubits in superposition to calculate exponentially faster than classical computers.", NovaIntent.SUMMARIZE),
            ("summarize file results.txt", NovaIntent.SUMMARIZE),
            ("summarize context", NovaIntent.SUMMARIZE),
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

    # Explicit Validation for Goal a (Complex Compound Multi-Step Execution)
    total_commands += 1
    demo_file = DEFAULT_WORKSPACE / "Project" / "Demo" / "xyz.txt"
    suite_file = DEFAULT_WORKSPACE / "TestSuite" / "results.txt"
    if demo_file.exists() and suite_file.exists():
        print(f"[PASS] Goal a Multi-Step Verification: '{demo_file}' and '{suite_file}' confirmed created on disk.")
        passed_commands += 1
    else:
        print(f"[FAIL] Goal a Multi-Step Verification: Expected files not found on disk. demo={demo_file.exists()}, suite={suite_file.exists()}")
        all_passed = False

    # Phase 3 Checkpoints: Persistent Memory, Action History, Recovery & Rollback
    print("\n--- PHASE 3: PERSISTENT MEMORY, ACTION AUDIT & SAFE ROLLBACK ---")
    phase3_dir = DEFAULT_WORKSPACE / "Phase3Sandbox"
    phase3_dir.mkdir(parents=True, exist_ok=True)

    # Checkpoint 3.1: Persistent User Memory - Remember project location
    total_commands += 1
    rem_res = brain.process(f"Remember that my NOVA project is in {phase3_dir}")
    if rem_res.get("success") and brain.memory.get_project_location("nova"):
        print(f"[PASS] Phase 3.1: Stored persistent project location -> {phase3_dir}")
        passed_commands += 1
    else:
        print("[FAIL] Phase 3.1: Failed to store persistent project location.")
        all_passed = False

    # Checkpoint 3.2: Recall memory
    total_commands += 1
    rec_res = brain.process("what do you remember")
    if rec_res.get("success") and "nova" in rec_res.get("response", "").lower():
        print("[PASS] Phase 3.2: Successfully recalled memories from SQLite store.")
        passed_commands += 1
    else:
        print("[FAIL] Phase 3.2: Failed to recall stored memories.")
        all_passed = False

    # Checkpoint 3.3: Context-aware resolution ("there" resolves to remembered project)
    total_commands += 1
    ctx_res = brain.process("Create folder tests there")
    if ctx_res.get("success") and (phase3_dir / "tests").exists():
        print(f"[PASS] Phase 3.3: Context resolution -> Created 'tests' inside {phase3_dir}")
        passed_commands += 1
    else:
        print("[FAIL] Phase 3.3: Failed context-aware folder creation.")
        all_passed = False

    # Checkpoint 3.4: Action History - Record and query actions today
    total_commands += 1
    test_move_file = phase3_dir / "audit_item.txt"
    test_move_file.write_text("Audit trace content", encoding="utf-8")
    move_dest_dir = phase3_dir / "tests"
    move_res = brain.process(f"move {test_move_file} to {move_dest_dir}")
    today_hist_res = brain.process("What files did you move today?")
    if today_hist_res.get("success") and "audit_item.txt" in today_hist_res.get("response", ""):
        print("[PASS] Phase 3.4: Action history recorded and retrieved today's file move.")
        passed_commands += 1
    else:
        print(f"[FAIL] Phase 3.4: Failed action history retrieval: {today_hist_res}")
        all_passed = False

    # Checkpoint 3.5: Safe Rollback & Undo
    total_commands += 1
    undo_res = brain.process("Undo the last file move")
    if undo_res.get("success") and test_move_file.exists() and not (move_dest_dir / "audit_item.txt").exists():
        print("[PASS] Phase 3.5: Successfully validated and restored moved file to original location.")
        passed_commands += 1
    else:
        print(f"[FAIL] Phase 3.5: Undo operation failed: {undo_res}")
        all_passed = False

    # Checkpoint 3.6: Rollback Collision Prevention
    total_commands += 1
    brain.process(f"move {test_move_file} to {move_dest_dir}")
    test_move_file.write_text("Conflicting new file", encoding="utf-8")
    blocked_undo = brain.process("undo")
    if not blocked_undo.get("success") and "already exists" in blocked_undo.get("response", "").lower():
        print("[PASS] Phase 3.6: Pre-flight collision prevention correctly rejected unsafe undo.")
        passed_commands += 1
    else:
        print(f"[FAIL] Phase 3.6: Collision guard failed to reject overwrite: {blocked_undo}")
        all_passed = False

    # Checkpoint 3.7: Memory Management & Privacy - Forget
    total_commands += 1
    forget_res = brain.process("Forget my NOVA project")
    if forget_res.get("success") and brain.memory.get_project_location("nova") is None and phase3_dir.exists():
        print("[PASS] Phase 3.7: Successfully removed memory preference while preserving physical filesystem.")
        passed_commands += 1
    else:
        print("[FAIL] Phase 3.7: Forget preference failed.")
        all_passed = False

    # Cleanup temporary test items
    brain.process("delete file DualTarget.txt permanently")
    brain.process("delete folder DualTarget permanently")
    brain.process("delete file clash_item.txt permanently")
    brain.process("delete folder ConflictDirA permanently")
    brain.process("delete folder ConflictDirB permanently")
    for test_dir in ["Project", "TestSuite", "SummaryVault", "Phase3Sandbox"]:
        p = DEFAULT_WORKSPACE / test_dir
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
            brain.indexer.remove_item(p)

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
