# Antigravity Brain Explorer Skill (`agy-brain-explorer`)

An [Antigravity Skill](https://antigravity.google/) and companion CLI tool to discover, inspect, and audit Google Antigravity session trajectories, transcripts, tool invocations, and execution step outputs across all brain storage directories under `~/.gemini`.

Packaged as an Antigravity agent skill under [`.agents/skills/agy-brain-explorer/`](.agents/skills/agy-brain-explorer/) and powered by [Typer](https://typer.tiangolo.com/), it equips both AI agents and developers to explore past conversations, trace execution flows, review tool parameters, and debug trajectories with Markdown-first rendering and clickable Antigravity conversation links (`conversation://<session-id>`).

---

## Repository Structure

This repository is structured as a standalone Antigravity Skill package:

```text
.
├── .agents/
│   └── skills/
│       └── agy-brain-explorer/
│           ├── SKILL.md                          # Skill definition & runbook for Antigravity agents
│           └── scripts/
│               └── agy-brain-explorer.py         # Standalone CLI exploration script (PEP 723)
├── LICENSE                                       # Apache 2.0 License
└── README.md                                     # Documentation and usage guide
```

- **[`SKILL.md`](.agents/skills/agy-brain-explorer/SKILL.md)**: Teaches Antigravity agents how and when to invoke the tool, including required parameters, sandbox bypass instructions, and command recipes.
- **[`scripts/agy-brain-explorer.py`](.agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py)**: The executable Python script featuring PEP 723 inline metadata for zero-config execution via `uv`.

---

## Using as an Antigravity Skill

### 1. Installation

You can install this skill either per-workspace or globally for all sessions on your machine:

- **Workspace Skill**: Clone or copy this repository (or just the `.agents/skills/agy-brain-explorer` directory) into your workspace root.
- **Global Skill**: Copy or symlink `.agents/skills/agy-brain-explorer` into your global Antigravity customizations folder:
  ```bash
  mkdir -p ~/.gemini/config/skills
  ln -s "$(pwd)/.agents/skills/agy-brain-explorer" ~/.gemini/config/skills/agy-brain-explorer
  ```

### 2. Progressive Disclosure & Agent Activation

Antigravity uses progressive disclosure. The agent sees the skill's name and description in its available skills list:

> **agy-brain-explorer**: Discover, list, inspect, and audit Google Antigravity session trajectories, transcripts, tool invocations, and execution steps across all brain storage directories under ~/.gemini. Use whenever asked to list recent/past sessions, review session histories, inspect tool executions, or debug trajectory steps.

When prompted with queries such as:
- *"What did we do in our last session?"*
- *"List my recent Antigravity conversations."*
- *"Show me the commands run during session `c1e9ba23`."*
- *"Audit the tool calls in step 5 of the previous task."*

The agent activates the skill, reads `SKILL.md`, and runs the script using `run_command`.

### 3. Agent Sandbox Requirements

> [!IMPORTANT]
> When executed by an agent, `run_command` must specify **`BypassSandbox: true`**.
> 1. Antigravity session directories reside at `~/.gemini/**/brain/`, outside standard workspace sandbox bounds.
> 2. `uv run` requires unsandboxed process creation permissions.

---

## Standalone CLI Features

- **Multi-Brain Trace Explorer (Default)**: Running without arguments discovers all conversation traces across all brain directories under `~/.gemini` (e.g. `antigravity`, `antigravity-cli`, `antigravity-acp`).
- **Markdown-First Rendering**: All results render cleanly as GitHub Flavored Markdown with clickable `conversation://` session links that open directly in Antigravity.
- **Chronological Ordering**: Traces are ordered by actual creation timestamp (newest first by default), rather than arbitrary directory sorting.
- **Interactive Trace Browser**: Launch with `--interactive` / `-i` to view traces and select any session by numerical index to inspect its summary, timeline, or tools without typing long UUIDs.
- **Automated Session Discovery**: Pass an absolute path, a local relative path, or just a session UUID prefix (e.g. `74126ecc`). Sessions located anywhere under `~/.gemini/**/brain/` are automatically resolved.
- **Session Overview**: Displays start/end timestamps in local time, elapsed duration, detected model, client timezone, mentioned items, workspace paths, and tool frequency metrics.
- **Interactive Timeline**: Browse conversation turns with filters for tool calls (`--tools-only`), user inputs (`--user-only`), pagination, and offsets.
- **Detailed Step Inspection**: Drill down into individual steps to view model thinking, prompt contents, formatted tool call arguments, and step output logs (`output.txt`).
- **Tool & Command Auditing**: Dedicated commands to view all tool invocations or exclusively audit shell commands executed via `run_command` alongside their working directories.
- **Raw Step Record**: Formatted JSON code block of any step for debugging.
- **Zero-Config Execution**: Uses [PEP 723](https://peps.python.org/pep-0723/) inline script metadata, allowing instant execution via `uv` without manually setting up a virtual environment.

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
# Path to script from repository root
SCRIPT=".agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py"

# 1. Explore all conversation traces across ~/.gemini (newest first)
uv run $SCRIPT

# 2. Interactive trace browser (select by number to inspect)
uv run $SCRIPT -i

# 3. Filter traces or customize sorting
uv run $SCRIPT --limit 10
uv run $SCRIPT --asc              # Oldest first
uv run $SCRIPT --brain antigravity-cli

# 4. Inspect a specific session by UUID or prefix
uv run $SCRIPT 74126ecc-9639-4ff3-9dcb-7ac2d9400986
uv run $SCRIPT 74126ecc steps --limit 5
uv run $SCRIPT 74126ecc step 1
```

> [!TIP]
> Add a shell alias for quick access anywhere:
> ```bash
> alias agy-brain-explorer="uv run /path/to/.agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py"
> ```

### Using standard `venv`

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install "typer>=0.12.0"

# Run explorer
python .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py

# Inspect a session
python .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION_ID_OR_PATH> [COMMAND]
```

---

## Command Reference

### 1. Conversation Trace Explorer (Default Mode)

When run without a session identifier (or with `list` / `explore` / `traces`), the explorer scans all brain directories under `~/.gemini` and displays all discovered conversation traces ordered chronologically:

```bash
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py [OPTIONS]
# or explicitly:
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py list [OPTIONS]
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
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py --limit 10

# View only traces from antigravity-cli
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py --brain antigravity-cli

# Interactively browse and inspect sessions
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py -i
```

---

### 2. Single-Session Inspection

Inspect a specific session by supplying its full UUID, partial prefix, or folder path:

```bash
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py [OPTIONS] SESSION [COMMAND] [ARGS]...
```

#### `summary` (Default Session Subcommand)
Displays a high-level overview of the session, including metadata, timing, duration, workspace paths, initial user request, and tool invocation statistics in Markdown. Executed automatically when no subcommand is specified.

```bash
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION>
# or explicitly:
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> summary
```

#### `steps` (Timeline View)
Lists the conversation timeline in a Markdown table showing step number, time, actor source (`USER_EXPLICIT`, `MODEL`, `SYSTEM`), step type, and action/preview.

```bash
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> steps [OPTIONS]
```
- `-t`, `--tools-only`: Filter to steps containing tool invocations.
- `-u`, `--user-only`: Filter to user input steps.
- `-n`, `--limit <INT>`: Limit number of steps displayed.
- `--offset <INT>`: Skip initial number of steps.

#### `step` (Detailed Inspection)
Inspects a specific step in detail in Markdown. Displays metadata header, text content, model thinking (if present), formatted tool call arguments, and step output logs (`output.txt`).

```bash
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> step <STEP_INDEX> [OPTIONS]
```
- `-l`, `--lines <INT>`: Maximum lines of step execution output to display (default: `50`).

#### `tools` (Tool Call Audit)
Lists all tool calls executed across the entire session chronologically in Markdown, including tool name, action/summary, and arguments/target.

```bash
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> tools
```

#### `commands` (Shell Execution Audit)
Audits all shell commands executed via the `run_command` tool in a Markdown table. Displays step index, target working directory (`Cwd`), and the exact command line executed.

```bash
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> commands
```

#### `raw` (Raw Step Dump)
Dumps the raw JSON record of a specific step index in a Markdown code block.

```bash
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> raw <STEP_INDEX> [--full/--compact]
```

---

## Session Resolution

The `<SESSION>` argument accepts:
1. **Explicit Directory Path**: Full or relative path to a session directory (e.g. `./74126ecc-9639-4ff3-9dcb-7ac2d9400986` or `/path/to/session`).
2. **Session UUID**: Full UUID corresponding to a folder in `~/.gemini/**/brain/<UUID>`.
3. **Prefix / Partial ID**: The start of a UUID (e.g., `74126ecc`). It searches all available Antigravity brain folders and resolves the match automatically.

---

## Antigravity Session Directory Layout

For reference, session directories are structured as follows:

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
