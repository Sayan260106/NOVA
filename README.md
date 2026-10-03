# Project Nova — JARVIS-Class Virtual Assistant

Nova is an intelligent, modular, agentic virtual assistant built for Windows OS automation, system control, file intelligence, application management, multi-step command execution, and privacy-first local summarization.

---

## 🚀 Capabilities Implemented (Checkpoints)

### a) Application Discovery & Launching
- Discovers **all applications** present on the laptop:
  - Windows Modern / Store apps (UWP) via `Get-StartApps` & `shell:AppsFolder`
  - Start Menu shortcuts (`.lnk`) across system and user profiles
  - Windows Registry `App Paths` (`HKLM` & `HKCU`)
  - Standard system executables in `PATH`
- Supports alias resolution and fuzzy matching (e.g. `calc` -> `Calculator`, `chrome` -> `Google Chrome`, `notes` -> `Notepad`, `terminal` -> `Windows Terminal`).
- Zero-configuration launching of any installed program.

### b) Zero-Path File & Folder Intelligence
- **D: Drive Default Workspace**: If a destination folder is not explicitly specified, Nova automatically creates folders and files directly in the root of the **D: drive** (`D:\`).
- **Specific Folder Creation**: When a folder is specified (e.g. `create folder Notes inside Projects` or `create file data.txt in specific folder Vault`), Nova locates the target folder anywhere on the laptop and places the new item inside it.
- **Rename Files & Folders**:
  - `rename file <old_name> to <new_name>`: Locates the file anywhere on the computer and renames it in place.
  - `rename folder <old_name> to <new_name>`: Locates the directory and renames it.
- **Copy & Move**:
  - `copy file <name> to <destination_folder>`: Resolves both source and destination folder automatically.
  - `move file <name> to <destination_folder>`: Resolves both source and destination folder automatically.
- **Delete with Disambiguation & Confirmation**:
  - `delete file <name>` or `delete folder <name>`: Automatically discovers all files/folders with the same name across all drives.
  - If multiple duplicates exist, Nova lists each matching path with its file size/type and asks you to select which one to delete.
  - Asks for explicit confirmation (`[y/N]`) displaying the exact target path before executing deletion.
  - Safely moves to Windows Recycle Bin via `send2trash` (or permanent deletion when specified).
- **Open with Disambiguation & Confirmation**:
  - `open <name>`: Discovers all files, folders, and applications matching the given name or stem.
  - If multiple candidates exist (e.g. both a folder and file named `Project`, or duplicate files across different folders), Nova lists each candidate (`[1] Folder`, `[2] File`), asks you which one to open, prompts for confirmation (`[Y/n]`), and opens that item.
  - `open file <name>`: Specifically filters for and opens matching files in default editors.
  - `open folder <name>`: Specifically filters for and opens matching directories in File Explorer.
  - `launch <app>` / `open app <name>`: Discovers and launches installed applications.

### c) System Power & Session Management
- **Lock**: Workstation lock via Windows `user32.dll LockWorkStation`.
- **Sleep**: Suspend / standby via Windows `powrprof.dll SetSuspendState`.
- **Restart**: Command generation & scheduling via `shutdown /r /t <seconds>`.
- **Shutdown**: Command generation & scheduling via `shutdown /s /t <seconds>`.
- **Abort Power**: Aborts any scheduled restart/shutdown via `shutdown /a`.
- **Battery & Power Monitoring**: Real-time battery %, charging status, remaining time.
- **Safety**: Safe dry-run mode enabled by default; confirmation prompt required for live power execution.

### d) Universal Search & Indexing across File Explorer
- Fast SQLite-backed indexer (`~/.nova/nova_index.db`) caching files, directories, and installed software.
- Multi-drive search across all logical drives (`C:\`, `D:\`, etc.) present in File Explorer.
- Sub-second search across applications, files, and folders with relevance ranking.

### e) Complex & Compound Multi-Step Commands (Goal a)
- Understands and executes multi-step commands joined by natural conjunctions (`and`, `then`, `and then`, `after that`, `;`).
- Automatically maintains execution context across steps (e.g., creating a folder and immediately placing a file inside that newly created folder without needing redundant paths).
- Hybrid execution: Powered by local Ollama LLM intent decomposition when available, with a robust deterministic rule-based compound engine as an instant fallback.

### f) Local & Offline Summarization (Goal b — Zero API Keys)
- Summarizes any arbitrary text, local file/document, or conversational session context completely offline.
- Powered by local Ollama (`llama3.2` / `mistral` / etc.) running locally at `localhost:11434` without any external cloud APIs, internet connectivity, or API keys required.
- High-reliability heuristic extractive summarizer fallback that works 100% offline even if Ollama is not installed or running.

---

## 📖 Complete Nova Commands Reference

Nova supports natural conversational phrasing, explicit commands, and multi-step instructions.

### 1. 🚀 Application Management
| Command / Syntax | Example | Description |
| :--- | :--- | :--- |
| `open <app>` | `open chrome` | Launches the application using fuzzy matching & aliases |
| `launch <app>` | `launch calculator` | Synonym for launching applications |
| `start <app>` | `start notepad` | Synonym for launching applications |
| `run <app>` | `run terminal` | Synonym for launching applications |
| `open app <name>` | `open app spotify` | Explicitly targets installed applications |

*Supported Aliases:* `calc` -> Calculator, `chrome` -> Google Chrome, `notes` -> Notepad, `terminal` -> Windows Terminal, `code` -> Visual Studio Code, `edge` -> Microsoft Edge, `files` / `explorer` -> File Explorer, and more.

---

### 2. 📁 Zero-Path File & Folder Intelligence
| Command / Syntax | Example | Description |
| :--- | :--- | :--- |
| `create folder <name>` | `create folder Projects` | Creates folder in **D: drive** (`D:\`) by default |
| `create folder <name> inside <parent>` | `create folder Notes inside Projects` | Locates `<parent>` anywhere on PC and creates folder inside |
| `make a folder '<name>' in <parent>` | `make a folder 'Demo' in Project folder` | Natural phrasing for nested folder creation |
| `create file <name>` | `create file todo.txt` | Creates an empty file in **D: drive** root |
| `create file <name> with content '<text>'` | `create file notes.txt with content 'Call client'` | Creates file with initial text content |
| `create file <name> [with content '...'] inside <parent>` | `create file brief.txt with content 'Nova' inside Vault` | Creates file with content inside the resolved parent directory |
| `rename file <old> to <new>` | `rename file draft.txt to final.txt` | Discovers `<old>` anywhere on PC and renames it in place |
| `rename folder <old> to <new>` | `rename folder DeepArchive to Classified` | Discovers `<old>` folder and renames it in place |
| `copy file <src> to <dest>` | `copy file report.pdf to Backup` | Auto-resolves source file and destination folder |
| `move file <src> to <dest>` | `move file data.csv to Archive` | Auto-resolves source file and destination folder |
| `delete file <name>` | `delete file temp.log` | Safely moves file to **Windows Recycle Bin** (`send2trash`) |
| `delete folder <name>` | `delete folder TempDir` | Safely moves folder to **Windows Recycle Bin** |
| `delete file/folder <name> permanently` | `delete file secret.key permanently` | Permanently deletes item from disk |

#### 🛡️ Duplicate Disambiguation & Deletion Confirmation
If duplicate files or folders exist with the same name across your drives:
1. Nova displays a numbered list of all discovered candidates with their paths and file sizes.
2. Prompts you to pick the exact candidate: `Which one would you like to delete? [1-N] (or 'c' to cancel)`.
3. Displays a final confirmation prompt (`[y/N]`) showing the exact path before performing deletion.

---

### 3. 📂 Universal Open (Apps, Files & Folders)
| Command / Syntax | Example | Description |
| :--- | :--- | :--- |
| `open <name>` | `open Project` | Discovers matching applications, files, and folders across system |
| `open file <name>` | `open file budget.xlsx` | Specifically searches for and opens files in default editor |
| `open folder <name>` | `open folder Documents` | Specifically searches for and opens folders in Windows File Explorer |

#### 🔀 Open Disambiguation & Confirmation
When multiple items share the same name (e.g. an application, a file, and a folder):
1. Nova categorizes candidates (`📁 Folder`, `📄 File`, `🖥️ App`) with full paths and sizes.
2. Prompts you to select which target you want to open: `Which one would you like to open? [1-N]`.
3. Prompts for confirmation (`[Y/n]`) before opening.

---

### 4. 🔎 Universal Search & Discovery across File Explorer
| Command / Syntax | Example | Description |
| :--- | :--- | :--- |
| `find app <name>` | `find app spotify` | Searches cataloged installed applications |
| `find file <name>` | `find file run_nova.py` | Searches indexed files across all logical drives (`C:\`, `D:\`) |
| `find folder <name>` | `find folder Documents` | Searches indexed directories across all drives |
| `find <query>` | `find invoice` | Universal search across applications, files, and folders |
| `search for <query>` | `search for report.pdf` | Synonym for universal search |
| `locate <query>` | `locate python` | Synonym for universal search |

---

### 5. 🧠 Complex & Compound Multi-Step Commands
Connect multiple actions into a single instruction using `and`, `then`, `and then`, `after that`, or `;`:

| Example Instruction | Execution Flow |
| :--- | :--- |
| `Make a folder 'Demo' in Project folder and create a file 'xyz.txt'` | 1. Creates `Demo` inside `Project`<br>2. Automatically places `xyz.txt` inside `Demo` |
| `Create folder TestSuite in D: drive and create file results.txt with content 'Passed' inside TestSuite` | 1. Creates `TestSuite` in `D:\`<br>2. Creates `results.txt` with content inside `TestSuite` |
| `create folder Vault then create file keys.txt inside Vault` | Chains creation in sequence |
| `open notepad; open calculator` | Executes multiple application launches sequentially |

---

### 6. 📝 Summarization (100% Local & Offline — Zero API Keys)
| Command / Syntax | Example | Description |
| :--- | :--- | :--- |
| `summarize this text: <text>` | `summarize this text: Quantum computing uses qubits in superposition...` | Summarizes arbitrary text directly |
| `summarize: <text>` | `summarize: Photosynthesis converts light energy into chemical energy.` | Short syntax for text summarization |
| `summarize file <filename>` | `summarize file results.txt` | Locates file on disk, reads text, and produces concise summary |
| `summarize document <file> in <folder>` | `summarize document report.pdf inside Vault` | Summarizes specific file inside specified folder |
| `summarize context` | `summarize context` | Summarizes recent conversation and executed actions |
| `summarize conversation` | `summarize conversation` | Synonym for session context summarization |
| `summarize history` | `summarize history` | Synonym for session context summarization |

---

### 7. ⚡ System Power & Battery Management
| Command / Syntax | Example | Description |
| :--- | :--- | :--- |
| `lock laptop` / `lock screen` | `lock laptop` | Locks the Windows workstation |
| `sleep laptop` / `put laptop to sleep` | `sleep laptop` | Suspends system to low-power standby |
| `restart laptop` | `restart laptop` | Restarts the computer immediately |
| `restart laptop in <seconds> seconds` | `restart laptop in 60 seconds` | Schedules restart with a countdown timer |
| `shutdown laptop` | `shutdown laptop` | Shuts down the computer immediately |
| `shutdown laptop in <seconds> seconds` | `shutdown laptop in 90 seconds` | Schedules shutdown with a countdown timer |
| `cancel shutdown` / `abort restart` | `cancel shutdown` | Aborts any active scheduled shutdown or restart |
| `battery status` / `power status` | `battery status` | Shows battery %, charging status, and remaining runtime |

> **Safety Notice:** Nova runs in safe dry-run mode by default. Real power actions require passing the `--live-power` flag and interactive confirmation.

---

### 8. 🏛️ System Architecture & Memory
| Command / Syntax | Example | Description |
| :--- | :--- | :--- |
| `show language chart` | `show language chart` | Displays the complete 24-component JARVIS architecture & tech stack chart |
| `languages` / `tech stack` | `languages` | Displays programming language recommendations for virtual assistants |

---

### 9. 🚪 Session Control
| Command / Syntax | Description |
| :--- | :--- |
| `help` / `commands` / `what can you do` | Displays the complete Nova interactive command manual |
| `exit` / `quit` / `bye` / `shutdown nova` | Shuts down the Nova virtual assistant session cleanly |

---

## 🧠 Memory: Component Architecture & Programming Languages

| JARVIS Component                       | Recommended Language               | Why                                                                     |
| -------------------------------------- | ---------------------------------- | ----------------------------------------------------------------------- |
| 🧠 **Main AI / Agent Brain**           | **Python**                         | Best AI/LLM ecosystem and easy agent development                        |
| 🤖 **LLM Integration**                 | **Python**                         | Excellent SDK/API support for AI models                                 |
| 🎙️ **Speech-to-Text (STT)**           | **Python**                         | Strong support for Whisper, Vosk and other speech engines               |
| 🔊 **Text-to-Speech (TTS)**            | **Python**                         | Easy integration with local and cloud TTS engines                       |
| 👂 **Wake Word Detection**             | **Python + C++ engine if needed**  | Python for orchestration; native engine for very low latency            |
| ⚡ **Real-Time Audio Processing**       | **C++**                            | Better performance for continuous audio processing                      |
| 🧠 **Memory System**                   | **Python**                         | Easy integration with databases, embeddings and vector DBs              |
| 🔎 **RAG / Document Search**           | **Python**                         | Strong ecosystem for embeddings, retrieval and AI pipelines             |
| 🛠️ **Tool/Function Calling**          | **Python**                         | Easy integration with APIs, scripts and applications                    |
| 💻 **Windows OS Automation**           | **Python**                         | Excellent libraries for processes, files, keyboard/mouse and automation |
| 🐧 **Linux System Control**            | **Python + Bash**                  | Python orchestration + native Linux commands                            |
| ⚙️ **Low-Level OS Operations**         | **C++**                            | Use when you need maximum performance/native system access              |
| 🔌 **Hardware / ESP32 / IoT**          | **C/C++**                          | Standard choice for microcontrollers and embedded systems               |
| 🌐 **Backend Server**                  | **Python (FastAPI)**               | Fast, asynchronous and excellent for AI services                        |
| 🔄 **Real-Time Communication**         | **Python + WebSocket**             | Low-latency communication between components                            |
| 🖥️ **JARVIS Desktop UI**              | **TypeScript + React**             | Rich, animated and modern interface                                     |
| 🎨 **JARVIS HUD / Animations**         | **TypeScript + React + CSS/WebGL** | Best for futuristic visual interface                                    |
| 🌐 **Web Dashboard**                   | **TypeScript + React**             | Same UI technology can be reused                                        |
| 📱 **Mobile App**                      | **TypeScript + React Native**      | Reuse much of the frontend knowledge/code                               |
| 🗄️ **Database**                       | **SQL**                            | Reliable structured storage                                             |
| 🔍 **Vector Database**                 | **Python + Qdrant/FAISS/etc.**     | Python integrates easily with embeddings                                |
| 📊 **Data/Analytics**                  | **Python**                         | NumPy, Pandas, visualization ecosystem                                  |
| 🔐 **Authentication/Security**         | **Python/TypeScript**              | Depends on whether auth is backend or frontend                          |
| 🚀 **Performance-Critical Algorithms** | **C++**                            | Use only where profiling shows Python is a bottleneck                   |
| 🧪 **Testing / Automation**            | **Python**                         | Easy unit, integration and system testing                               |

---

## 🛠️ Installation & Setup

### 1. Prerequisites
- **Windows 10 / 11**
- **Python 3.10+** (Python 3.12/3.14 compatible)
- *(Optional, for local LLM)* **Ollama**:
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

## 🧪 Test Suites & Verification

Nova features a complete automated testing suite covering all checkpoints:

```bash
# 1. Comprehensive Verification Suite (All 41 Checkpoints)
.venv\Scripts\python tests/run_verification.py

# 2. Complex Multi-Step Commands & Summarization Suite (Goal a & Goal b)
.venv\Scripts\python -m unittest tests/test_complex_brain.py

# 3. Duplicate Name Disambiguation & Interactive Deletion Suite
.venv\Scripts\python -m unittest tests/test_deletion_disambiguation.py

# 4. Multi-Candidate Open Disambiguation Suite
.venv\Scripts\python -m unittest tests/test_open_disambiguation.py

# 5. Zero-Path File Manager & D: Drive Intelligence Suite
.venv\Scripts\python -m unittest tests/test_file_manager.py

# 6. Installed Application Discovery & Launching Suite
.venv\Scripts\python -m unittest tests/test_app_manager.py

# 7. System Power & Battery Management Suite
.venv\Scripts\python -m unittest tests/test_power_manager.py

# 8. Brain End-to-End Intent & Integration Suite
.venv\Scripts\python -m unittest tests/test_brain.py
```
