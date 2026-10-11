# Project Nova — JARVIS-Class Virtual Assistant

Nova is an intelligent, modular, agentic virtual assistant built for Windows OS automation, system control, zero-path file intelligence, application management, multi-step compound command execution, privacy-first local summarization, persistent user memory, and daily productivity workflows.

---

## 🌟 Architecture & Implementation Roadmap

Nova is engineered as a robust, layered agentic system:

```
 User Voice / CLI Command
           │
           ▼
   [Intent Parser] ──► (Natural Language, Regex Rules, Ollama Decomposition)
           │
           ▼
    [Nova Planner] ──► (Ordered PlanSteps, Dependency Resolution, Safety Flags)
           │
           ▼
    [Nova Policy]  ──► (Protected Directories, Whitelist, Ambiguity Gates)
           │
           ▼
   [Nova Executor] ──► (Unified Multi-Manager Execution, Audit Logs & Undo Stack)
     ├── File Manager (`nova.system.file_manager`)
     ├── App Manager (`nova.system.app_manager`)
     ├── Power Manager (`nova.system.power_manager`)
     ├── Persistent Memory (`nova.core.memory`)
     ├── Action History (`nova.core.action_history`)
     ├── Notes Manager (`nova.tools.notes`)
     ├── Reminder Manager (`nova.tools.reminders`)
     ├── Clipboard Manager (`nova.tools.clipboard`)
     ├── System Diagnostics (`nova.tools.system_diagnostics`)
     └── Task Scheduler (`nova.tools.scheduler`)
```

- **Phase 1: Safe Execution & Pipeline Foundation**  
  Standardized `ToolResult` contracts, dependency-aware `NovaPlanner`, safety-gated `NovaPolicy`, pre/post-execution verification in `NovaExecutor`.
- **Phase 2: OS Automation & File Intelligence**  
  Start Menu and UWP application discovery, zero-path D: drive file/folder CRUD, duplicate name disambiguation, Windows power states.
- **Phase 3: Persistent Memory & Action History**  
  SQLite user preferences (`nova_memory.db`), audit logging (`nova_history.db`), pre-flight collision-checked rollback and undo.
- **Phase 4: Practical Daily Productivity Assistant**  
  Quick notes scratchpad, natural language reminders, privacy-safe clipboard utilities, non-terminating system diagnostics, persistent task scheduler.

---

## 🚀 Capabilities Implemented

### 1. 📝 Quick Notes & Personal Scratchpad (Phase 4)
- **SQLite Persistence**: Stores notes in `~/.nova/nova_notes.db` across sessions with WAL journal mode and timestamp indexing.
- **Auto-Titled & Tagged**: Automatically generates concise titles from content when omitted and supports multi-tag filtering.
- **Full-Text Search**: Fast keyword searching across titles, body content, and tags.
- **Reversible Deletions**: Note deletion produces structured `undo_info` allowing restoration.

### 2. ⏰ Reminders & Task Tracking (Phase 4)
- **Natural Language Parsing**: Handles relative times (`in 10 minutes`, `in 2 hours`), 12-hour/24-hour absolute times (`at 8 PM`, `at 20:00`), and day markers (`tomorrow at 9 AM`).
- **Validation & Duplicate Prevention**: Rejects invalid dates/times with helpful feedback and blocks duplicate pending reminders.
- **Recurrence Support**: Supports recurring schedules (`daily`, `weekly`, `hourly`, `workdays`).
- **Non-Blocking Background Monitor**: A background daemon monitors due reminders without blocking the interactive CLI loop.

### 3. 📋 Clipboard Utilities & Privacy Safeguards (Phase 4)
- **Native Windows API**: Leverages Win32 user32 clipboard APIs without heavy third-party dependencies.
- **Sensitive Secret Detection**: Scans clipboard text for API keys (OpenAI, AWS, GitHub), private key blocks, Bearer tokens, connection strings, and payment card numbers.
- **Safe Masking & Note Conversion**: Automatically masks sensitive credentials (`sk-****...`) in terminal output and allows saving clipboard text directly to persistent notes.

### 4. 🩺 System Diagnostics & Resource Profiling (Phase 4)
- **Hardware Telemetry**: Inspects CPU utilization, logical core counts, RAM memory usage, drive capacities, and battery states.
- **Top Process Consumers**: Identifies top processes by CPU and memory consumption.
- **Performance Diagnostics**: Analyzes system bottlenecks and explains why a PC may feel slow **without terminating any processes automatically**.

### 5. ⏱️ Scheduled Tasks & Automation (Phase 4)
- **Persistent Job Queue**: Backed by `~/.nova/nova_schedules.db`. Pending and recurring tasks are recovered and rescheduled across application restarts.
- **Security Policy Enforcement**: Allows **only approved, policy-validated NOVA actions** (`OPEN_PROJECT`, `OPEN_APP`, `OPEN_ITEM`, `SUMMARIZE`, `BATTERY_STATUS`, `CREATE_FILE`, `CREATE_FOLDER`, `SYSTEM_DIAGNOSTICS`). Rejects arbitrary shell scripts and destructive commands (`DELETE_ITEM`, `SHUTDOWN_SYSTEM`, `RESTART_SYSTEM`).
- **Non-Blocking Background Execution**: Background daemon safely dispatches due tasks without freezing user interactions.

### 6. 🧠 Persistent Memory & Custom Aliases (Phase 3)
- Stores project locations, user preferences, custom application aliases, and common folders across restarts in SQLite (`~/.nova/nova_memory.db`).
- Allows dynamic inspection and selective clearing via conversational commands.

### 7. 📜 Action History & Safe Undo (Phase 3)
- Audit log tracking all executed operations in `~/.nova/nova_history.db`.
- Pre-flight rollback validation verifies source item presence and destination safety before executing undo restorations.

### 8. 📁 Zero-Path File & Folder Intelligence (Phase 2)
- **D: Drive Default**: Defaults to `D:\` if no parent directory is specified.
- **Smart Resolution**: Resolves target directories anywhere on the computer without explicit absolute paths.
- **Duplicate Disambiguation & Confirmation**: Identifies duplicate names across all drives, prompting interactive disambiguation and safety confirmation before deletion or opening.

### 9. 🚀 Application Discovery & Launching (Phase 2)
- Discovers Modern UWP Store apps (`shell:AppsFolder`), Start Menu programs, Windows Registry paths, and PATH executables.
- Supports fuzzy matching and custom aliases (e.g., `calc`, `chrome`, `notes`, `terminal`, `code`).

### 10. ⚡ Power & System Session Management (Phase 2)
- Workstation lock (`user32.dll`), standby sleep (`powrprof.dll`), scheduled restart, shutdown countdown timers, and cancellation.
- Safe dry-run mode enabled by default; requires `--live-power` for actual system execution.

### 11. 🤖 Offline Local Summarization (Zero API Keys)
- Summarizes arbitrary text, local documents, or conversation history using local Ollama models (`localhost:11434`) or a 100% offline heuristic fallback.

---

## 📖 Complete Nova Commands Reference

Nova supports natural conversational phrasing, explicit instructions, and compound multi-step commands.

### 1. 📝 Quick Notes & Scratchpad
| Command / Syntax | Example | Description |
| :--- | :--- | :--- |
| `save note <content>` | `save a note that I need to revise operating systems tonight` | Saves note with auto-derived title |
| `take note: <content>` | `take a note: Meeting with mentor at 4 PM` | Scratchpad note entry |
| `note titled <title> with content <text>` | `note titled Exams with content OS paper on Friday` | Saves note with custom title |
| `list notes [with tag <tag>]` | `list notes` or `list notes with tag study` | Displays saved notes with tags |
| `search notes for <query>` | `search notes for operating systems` | Searches across title, content, and tags |
| `read note <id>` / `view note <id>` | `read note 1` | Displays full note details |
| `update note <id> with <content>` | `update note 1 with Chapter 1 to 5` | Updates existing note |
| `append to note <id>: <content>` | `append to note 1: Also read paging` | Appends text to existing note |
| `delete note <id>` | `delete note 1` | Removes note (reversible via undo) |

---

### 2. ⏰ Reminders & Task Tracking
| Command / Syntax | Example | Description |
| :--- | :--- | :--- |
| `remind me at <time> to <action>` | `remind me at 8 PM to revise operating systems` | Absolute time reminder |
| `remind me to <action> at <time>` | `remind me to call Mom at 7:30 PM` | Natural word order syntax |
| `remind me in <duration> to <action>` | `remind me in 15 minutes to take a break` | Relative duration reminder |
| `remind me tomorrow at <time> to ...` | `remind me tomorrow at 9 AM to submit assignment` | Next-day reminder |
| `every day at <time> remind me to ...` | `daily at 8 PM remind me to take medicine` | Recurring daily reminder |
| `list reminders` / `show reminders` | `what are my reminders` | Lists all active pending reminders |
| `complete reminder <id>` | `complete reminder 1` | Marks reminder as completed |
| `dismiss reminder <id>` | `dismiss reminder 1` | Dismisses active alert |
| `clear completed reminders` | `clear completed reminders` | Removes finished/dismissed reminders |

---

### 3. 📋 Clipboard Utilities & Privacy Safeguards
| Command / Syntax | Example | Description |
| :--- | :--- | :--- |
| `read clipboard` / `show clipboard` | `what's in my clipboard` | Reads clipboard with sensitive pattern masking |
| `copy <text> to clipboard` | `copy 'Hello World' to clipboard` | Copies text to system clipboard |
| `clear clipboard` | `clear clipboard` | Securely clears clipboard data |
| `save clipboard as note` | `save the current clipboard text as a note` | Stores clipboard text in notes with tags |

---

### 4. 🩺 System Diagnostics & Health
| Command / Syntax | Example | Description |
| :--- | :--- | :--- |
| `check why computer is running slowly` | `why is my pc running slow?` | Diagnoses CPU/RAM/disk bottlenecks without killing processes |
| `system diagnostics` | `check system health` | Complete CPU, RAM, disk, and process overview |
| `cpu usage` / `memory usage` | `cpu usage` | Quick hardware resource status |

---

### 5. ⏱️ Scheduled Tasks & Automation
| Command / Syntax | Example | Description |
| :--- | :--- | :--- |
| `every day at <time>, <action>` | `Every day at 9 AM, open my college project` | Schedules recurring daily validated task |
| `daily at <time>: <action>` | `daily at 8 PM: check system health` | Schedules recurring diagnostic check |
| `list scheduled tasks` | `show schedules` | Lists active persistent automation jobs |
| `cancel schedule <id>` | `cancel schedule 1` | Cancels and removes scheduled task |

---

### 6. 🧠 Persistent User Memory & Preferences
| Command / Syntax | Example | Description |
| :--- | :--- | :--- |
| `remember that my <name> project is in <path>` | `remember that my NOVA project is in D:\Nova` | Stores project location across restarts |
| `remember that alias <name> is <app>` | `remember that alias browser is Google Chrome` | Stores custom app alias |
| `remember that <key> is <value>` | `remember that editor is VS Code` | Stores user preference |
| `what do you remember` / `recall all` | `recall editor` | Inspects stored memories |
| `forget my <name> project` / `forget <key>` | `forget editor` | Removes specific memory |
| `clear memories` | `forget everything` | Wipes all stored preferences |

---

### 7. 📜 Action History, Audit Logs & Safe Undo
| Command / Syntax | Example | Description |
| :--- | :--- | :--- |
| `what did you do today` | `what files did you move today` | Audit log of executed operations |
| `show action history` | `action history` | Inspects recent actions |
| `undo` / `undo last action` | `undo last move` | Restores previous reversible state with pre-flight safety |

---

### 8. 📁 Zero-Path File & Folder Intelligence
| Command / Syntax | Example | Description |
| :--- | :--- | :--- |
| `create folder <name>` | `create folder Projects` | Creates folder in `D:\` by default |
| `create folder <name> inside <parent>` | `create folder Notes inside Projects` | Creates folder in resolved parent |
| `create file <name> [with content '...']` | `create file todo.txt with content 'Study'` | Creates file in `D:\` or specified parent |
| `rename file/folder <old> to <new>` | `rename file draft.txt to final.txt` | Discovers and renames item in place |
| `copy file <src> to <dest>` | `copy file report.pdf to Backup` | Resolves source and destination folder |
| `move file <src> to <dest>` | `move file data.csv to Archive` | Resolves source and destination folder |
| `delete file/folder <name>` | `delete file temp.log` | Safe delete to Recycle Bin (`send2trash`) |
| `delete ... permanently` | `delete folder Cache permanently` | Permanent deletion from disk |

---

### 9. 🚀 Application Launching & Universal Open
| Command / Syntax | Example | Description |
| :--- | :--- | :--- |
| `open <app>` / `launch <app>` | `open chrome` or `launch calculator` | Launches application with alias support |
| `open <name>` | `open Project` | Discovers and opens app, file, or folder with disambiguation |
| `open file <name>` | `open file budget.xlsx` | Opens file in default registered program |
| `open folder <name>` | `open folder Documents` | Opens folder in Windows File Explorer |

---

### 10. ⚡ Power & Session Controls
| Command / Syntax | Example | Description |
| :--- | :--- | :--- |
| `lock laptop` / `lock screen` | `lock laptop` | Locks workstation screen |
| `sleep laptop` | `sleep laptop` | Puts system into standby |
| `restart laptop [in X sec]` | `restart laptop in 60 seconds` | Restarts system with optional countdown |
| `shutdown laptop [in X sec]` | `shutdown laptop in 90 seconds` | Shuts down system with countdown |
| `cancel shutdown` | `cancel shutdown` | Aborts scheduled restart or shutdown |
| `battery status` | `battery status` | Displays battery %, charging state, and remaining time |

---

### 11. ❓ Help & Manual
| Command / Syntax | Description |
| :--- | :--- |
| `help` | Displays the complete interactive command reference manual |
| `help <topic>` | Displays focused help for `notes`, `reminders`, `clipboard`, `diagnostics`, `scheduler`, `memory`, `files`, `apps`, `power` |
| `exit` / `quit` | Closes Nova session and stops background services cleanly |

---

## 🛠️ Installation & Setup

### 1. Prerequisites
- **Windows 10 / 11**
- **Python 3.10+** (Python 3.12/3.14 compatible)
- *(Optional, for offline local LLM)* **Ollama**:
  ```bash
  # Download from https://ollama.com and pull a lightweight model
  ollama pull llama3.2
  ```

### 2. Environment Setup
```bash
# Clone or navigate to the repository
cd d:\Nova

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install required dependencies
pip install -r requirements.txt
```

---

## 💻 Running Nova Assistant CLI

### Safe Power Dry-Run Mode (Default)
Safe mode intercepts all system power operations (lock, sleep, restart, shutdown) and verifies API parameters without altering machine state:
```bash
.venv\Scripts\python run_nova.py
```

### Live System Execution Mode
Enables real execution of workstation lock, suspend/sleep, and restart/shutdown timers (with interactive confirmation):
```bash
.venv\Scripts\python run_nova.py --live-power
```

---

## 🧪 Automated Test Suite (106+ Tests)

Nova features comprehensive automated test coverage across all subsystems:

```bash
# Run all 106 automated tests
.venv\Scripts\python -m unittest discover -s tests -p "test_*.py"

# Or run individual test modules:
.venv\Scripts\python -m unittest tests/test_notes.py                 # Quick Notes CRUD & Persistence
.venv\Scripts\python -m unittest tests/test_reminders.py             # Reminders & Duplicate Checks
.venv\Scripts\python -m unittest tests/test_clipboard.py             # Clipboard & Secret Masking
.venv\Scripts\python -m unittest tests/test_system_diagnostics.py    # Hardware Diagnostics
.venv\Scripts\python -m unittest tests/test_scheduler.py             # Task Scheduler & Policies
.venv\Scripts\python -m unittest tests/test_phase4_integration.py     # End-to-End Phase 4 Integration
.venv\Scripts\python -m unittest tests/test_memory_and_history.py    # Memory, Audit & Undo
.venv\Scripts\python -m unittest tests/test_phase1_pipeline.py       # Planner, Policy & Verification
```
