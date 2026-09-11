# Antigravity Brain Exploration CLI (`agy-brain-explorer.py`)

A python CLI tool to inspect Google Antigravity session trajectories, transcripts, tool invocations, and execution step outputs.

Built with [Typer](https://typer.tiangolo.com/) and [Rich](https://github.com/Textualize/rich), `agy-brain-explorer.py` provides formatted terminal tables, color-coded status badges, syntax-highlighted tool payloads, and machine-readable JSON exports.

---

## Features

- **Automated Session Discovery**: Pass an absolute path, a local relative path, or just a session UUID / prefix. Sessions located in `~/.gemini/antigravity*/brain/` are automatically resolved.
- **Session Overview (Default)**: Running without a subcommand defaults to `summary`. Displays start/end timestamps, elapsed duration, detected model, client timezone, mentioned items, workspace paths, and tool frequency metrics.
- **Interactive Timeline**: Browse conversation turns with filters for tool calls (`--tools-only`), user inputs (`--user-only`), pagination, and offsets.
- **Detailed Step Inspection**: Drill down into individual steps to view model thinking, prompt contents, formatted tool call arguments, and step output logs (`output.txt`).
- **Tool & Command Auditing**: Dedicated commands to view all tool invocations or exclusively audit shell commands executed via `run_command` alongside their working directories.
- **Raw JSON Inspection**: Dump full or compact JSON records for any step for debugging or piping into `jq`.
- **Zero-Config Execution**: Uses [PEP 723](https://peps.python.org/pep-0723/) inline script metadata, allowing execution via `uv` without manually setting up a virtual environment.

---

## Prerequisites

- **Python**: `>= 3.11`
- **Dependencies**: `typer >= 0.12.0`, `rich >= 13.7.0`
- **Recommended Runner**: [`uv`](https://docs.astral.sh/uv/)

---

## Quick Start

### Using `uv` (Recommended)

Run directly with dependencies automatically resolved:

```bash
uv run agy-brain-explorer.py <SESSION_ID_OR_PATH> [COMMAND]
```

For example, using the included sample session:

```bash
# High-level summary (default command)
uv run agy-brain-explorer.py 74126ecc-9639-4ff3-9dcb-7ac2d9400986

# Timeline of steps
uv run agy-brain-explorer.py 74126ecc-9639-4ff3-9dcb-7ac2d9400986 steps --limit 5

# Inspect a specific step
uv run agy-brain-explorer.py 74126ecc-9639-4ff3-9dcb-7ac2d9400986 step 1
```

### Using standard `venv`

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install "typer>=0.12.0" "rich>=13.7.0"

python agy-brain-explorer.py <SESSION_ID_OR_PATH> [COMMAND]
```

---

## Session Resolution

The `<SESSION>` argument accepts:
1. **Explicit Directory Path**: Full or relative path to a session directory (e.g. `./74126ecc-9639-4ff3-9dcb-7ac2d9400986` or `/path/to/session`).
2. **Session UUID**: Full UUID corresponding to a folder in `~/.gemini/antigravity*/brain/<UUID>`.
3. **Prefix / Partial ID**: The start of a UUID (e.g., `74126ecc`). It searches all available Antigravity brain folders and resolves the match automatically.

---

## Command Reference

### Global Syntax

```bash
agy-brain-explorer.py [OPTIONS] SESSION [COMMAND] [ARGS]...
```

**Global Options:**
- `-j`, `--json`: Output results in JSON format across any command.
- `-h`, `--help`: Show help message.

---

### 1. `summary` (Default Command)
Displays a high-level overview of the session, including metadata, timing, duration, workspace paths, initial user request, and tool invocation statistics. Executed automatically when no subcommand is specified.

```bash
uv run agy-brain-explorer.py <SESSION>
# or explicitly:
uv run agy-brain-explorer.py <SESSION> summary
```

**Options:**
- `-j`, `--json`: Output summary as JSON.

---

### 2. `steps`
Lists the conversation timeline in a formatted table showing step number, time, actor source (`USER_EXPLICIT`, `MODEL`, `SYSTEM`), step type, and action/preview.

```bash
uv run agy-brain-explorer.py <SESSION> steps [OPTIONS]
```

**Options:**
- `-t`, `--tools-only`: Filter to steps containing tool invocations.
- `-u`, `--user-only`: Filter to user input steps.
- `-n`, `--limit <INT>`: Limit number of steps displayed.
- `--offset <INT>`: Skip initial number of steps.
- `-j`, `--json`: Return step timeline as JSON.

**Example:**
```bash
# Show only the first 10 steps that ran tools
uv run agy-brain-explorer.py <SESSION> steps --tools-only --limit 10
```

---

### 3. `step`
Inspects a specific step in detail. Displays metadata header, text content, model thinking (if present), formatted tool call arguments, and step output logs (`output.txt`).

```bash
uv run agy-brain-explorer.py <SESSION> step <STEP_INDEX> [OPTIONS]
```

**Options:**
- `-l`, `--lines <INT>`: Maximum lines of step execution output to display (default: `50`).
- `-j`, `--json`: Output step details as JSON.

**Example:**
```bash
# View details of step 9 with up to 100 lines of output log
uv run agy-brain-explorer.py <SESSION> step 9 --lines 100
```

---

### 4. `tools`
Lists all tool calls executed across the entire session chronologically, including tool name, action/summary, and arguments/target.

```bash
uv run agy-brain-explorer.py <SESSION> tools
```

**Options:**
- `-j`, `--json`: Output tool calls as JSON.

---

### 5. `commands`
Audits all shell commands executed via the `run_command` tool. Displays step index, target working directory (`Cwd`), and the exact command line executed.

```bash
uv run agy-brain-explorer.py <SESSION> commands
```

**Options:**
- `-j`, `--json`: Output executed commands as JSON.

---

### 6. `raw`
Dumps the raw JSON record of a specific step index.

```bash
uv run agy-brain-explorer.py <SESSION> raw <STEP_INDEX> [OPTIONS]
```

**Options:**
- `--full` / `--compact`: Choose whether to inspect `transcript_full.jsonl` (default: `--full`) or truncated `transcript.jsonl`.
- `-j`, `--json`: Output pure JSON (suitable for piping to `jq`).

---

## Antigravity Session Directory Layout

For reference, `agy-brain-explorer.py` expects session directories structured as follows:

```text
<session_dir>/
├── .system_generated/
│   ├── logs/
│   │   ├── transcript.jsonl        # Compact conversation history
│   │   └── transcript_full.jsonl   # Complete, untruncated transcript
│   └── steps/
│       └── <step_index>/
│           └── output.txt          # Raw output/log from step execution
├── scratch/                        # Temporary files generated during session
└── .user_uploaded/                 # Files uploaded by the user
```
