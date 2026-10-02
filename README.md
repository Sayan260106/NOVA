# Project Nova - JARVIS-Class Virtual Assistant

Nova is an intelligent, modular, agentic virtual assistant built for Windows OS automation, system control, file intelligence, and application management.

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

## 🛠️ Usage

### Run Nova Assistant CLI
```bash
# In safe power dry-run mode (default)
.venv\Scripts\python run_nova.py

# With live system power control enabled
.venv\Scripts\python run_nova.py --live-power
```

### Run Tests & Verification
```bash
# App Manager tests
.venv\Scripts\python tests/test_app_manager.py

# Zero-path File Manager tests (D: drive, specific folder, rename, search)
.venv\Scripts\python tests/test_file_manager.py

# Power Manager tests
.venv\Scripts\python tests/test_power_manager.py

# Brain end-to-end integration tests
.venv\Scripts\python tests/test_brain.py

# Complete 26-point comprehensive test suite
.venv\Scripts\python tests/run_verification.py
```
