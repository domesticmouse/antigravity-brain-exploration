# Antigravity Brain Exploration CLI (`agy-brain-explorer.py`)

A python CLI tool to discover and inspect Google Antigravity session trajectories, transcripts, tool invocations, and execution step outputs across all brain directories under `~/.gemini`.

Built with [Typer](https://typer.tiangolo.com/), `agy-brain-explorer.py` renders all outputs directly as GitHub Flavored Markdown tables and sections, featuring chronological trace indexing, clickable Antigravity conversation links, and clear step audits.

---

## Features

- **Multi-Brain Trace Explorer (Default)**: Running without arguments discovers all conversation traces across all brain directories under `~/.gemini` (e.g. `antigravity`, `antigravity-cli`, `antigravity-acp`).
- **Markdown-First Rendering**: All results render cleanly as GitHub Flavored Markdown with clickable `conversation://` session links.
- **Chronological Ordering**: Traces are ordered by actual creation date/time (defaulting to newest first), replacing unhelpful UUID-based lexicographic sorting.
- **Interactive Trace Browser**: Launch with `--interactive` / `-i` to view traces and select any session by numerical index to inspect its summary, timeline, or tools without typing long UUIDs.
- **Automated Session Discovery**: Pass an absolute path, a local relative path, or just a session UUID / prefix. Sessions located anywhere under `~/.gemini/**/brain/` are automatically resolved.
- **Session Overview**: Displays start/end timestamps in local time, elapsed duration, detected model, client timezone, mentioned items, workspace paths, and tool frequency metrics.
- **Interactive Timeline**: Browse conversation turns with filters for tool calls (`--tools-only`), user inputs (`--user-only`), pagination, and offsets.
- **Detailed Step Inspection**: Drill down into individual steps to view model thinking, prompt contents, formatted tool call arguments, and step output logs (`output.txt`).
- **Tool & Command Auditing**: Dedicated commands to view all tool invocations or exclusively audit shell commands executed via `run_command` alongside their working directories.
- **Raw Step Record**: Formatted JSON code block of any step for debugging.
- **Zero-Config Execution**: Uses [PEP 723](https://peps.python.org/pep-0723/) inline script metadata, allowing execution via `uv` without manually setting up a virtual environment.

---

## Prerequisites

- **Python**: `>= 3.11`
- **Dependencies**: `typer >= 0.12.0`
- **Recommended Runner**: [`uv`](https://docs.astral.sh/uv/)

---

## Quick Start

### Using `uv` (Recommended)

Run directly with dependencies automatically resolved:

```bash
# 1. Explore all conversation traces across ~/.gemini (ordered by creation time, newest first)
uv run agy-brain-explorer.py

# 2. Interactive trace browser (select by number to inspect)
uv run agy-brain-explorer.py -i

# 3. Filter traces or customize sorting
uv run agy-brain-explorer.py --limit 10
uv run agy-brain-explorer.py --asc              # Oldest first
uv run agy-brain-explorer.py --brain antigravity-cli

# 4. Inspect a specific session by UUID or prefix
uv run agy-brain-explorer.py 74126ecc-9639-4ff3-9dcb-7ac2d9400986
uv run agy-brain-explorer.py 74126ecc steps --limit 5
uv run agy-brain-explorer.py 74126ecc step 1
```

### Using standard `venv`

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install "typer>=0.12.0"

# Run explorer
python agy-brain-explorer.py

# Inspect a session
python agy-brain-explorer.py <SESSION_ID_OR_PATH> [COMMAND]
```

---

## Command Reference

### 1. Conversation Trace Explorer (Default Mode)

When run without a session identifier (or with `list` / `explore` / `traces`), `agy-brain-explorer.py` scans all brain directories under `~/.gemini` and displays all discovered conversation traces ordered chronologically by creation timestamp:

```bash
uv run agy-brain-explorer.py [OPTIONS]
# or explicitly:
uv run agy-brain-explorer.py list [OPTIONS]
```

**Options:**
- `-n`, `--limit <INT>`: Limit number of traces displayed (default: `30`).
- `-a`, `--all`: Display all discovered traces without pagination limit.
- `--asc`: Sort oldest first (default is newest first).
- `-b`, `--brain <STR>`: Filter traces by brain root name (e.g. `antigravity-cli`).
- `-i`, `--interactive`: Launch interactive session picker to inspect sessions by index number.
- `-m`, `--md`, `--markdown`: Output as Markdown (default: True).
- `-h`, `--help`: Show help and options.

**Examples:**
```bash
# View the 10 most recent traces in Markdown
uv run agy-brain-explorer.py --limit 10

# View only traces from antigravity-cli
uv run agy-brain-explorer.py --brain antigravity-cli

# Interactively browse and inspect sessions
uv run agy-brain-explorer.py -i
```

---

### 2. Single-Session Inspection

Inspect a specific session by supplying its full UUID, partial prefix, or folder path:

```bash
agy-brain-explorer.py [OPTIONS] SESSION [COMMAND] [ARGS]...
```

#### `summary` (Default Session Subcommand)
Displays a high-level overview of the session, including metadata, timing, duration, workspace paths, initial user request, and tool invocation statistics in Markdown. Executed automatically when no subcommand is specified.

```bash
uv run agy-brain-explorer.py <SESSION>
# or explicitly:
uv run agy-brain-explorer.py <SESSION> summary
```

#### `steps` (Timeline View)
Lists the conversation timeline in a Markdown table showing step number, time, actor source (`USER_EXPLICIT`, `MODEL`, `SYSTEM`), step type, and action/preview.

```bash
uv run agy-brain-explorer.py <SESSION> steps [OPTIONS]
```
- `-t`, `--tools-only`: Filter to steps containing tool invocations.
- `-u`, `--user-only`: Filter to user input steps.
- `-n`, `--limit <INT>`: Limit number of steps displayed.
- `--offset <INT>`: Skip initial number of steps.

#### `step` (Detailed Inspection)
Inspects a specific step in detail in Markdown. Displays metadata header, text content, model thinking (if present), formatted tool call arguments, and step output logs (`output.txt`).

```bash
uv run agy-brain-explorer.py <SESSION> step <STEP_INDEX> [OPTIONS]
```
- `-l`, `--lines <INT>`: Maximum lines of step execution output to display (default: `50`).

#### `tools` (Tool Call Audit)
Lists all tool calls executed across the entire session chronologically in Markdown, including tool name, action/summary, and arguments/target.

```bash
uv run agy-brain-explorer.py <SESSION> tools
```

#### `commands` (Shell Execution Audit)
Audits all shell commands executed via the `run_command` tool in a Markdown table. Displays step index, target working directory (`Cwd`), and the exact command line executed.

```bash
uv run agy-brain-explorer.py <SESSION> commands
```

#### `raw` (Raw Step Dump)
Dumps the raw JSON record of a specific step index in a Markdown code block.

```bash
uv run agy-brain-explorer.py <SESSION> raw <STEP_INDEX> [--full/--compact]
```

---

## Session Resolution

The `<SESSION>` argument accepts:
1. **Explicit Directory Path**: Full or relative path to a session directory (e.g. `./74126ecc-9639-4ff3-9dcb-7ac2d9400986` or `/path/to/session`).
2. **Session UUID**: Full UUID corresponding to a folder in `~/.gemini/**/brain/<UUID>`.
3. **Prefix / Partial ID**: The start of a UUID (e.g., `74126ecc`). It searches all available Antigravity brain folders and resolves the match automatically.

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

---

## License
Open source and available under the [Apache License 2.0](LICENSE).

## Disclaimer
This is not an official Google product.
