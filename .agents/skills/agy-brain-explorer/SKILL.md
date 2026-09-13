---
name: agy-brain-explorer
description: >-
  Discover, list, inspect, and audit Google Antigravity session trajectories,
  transcripts, tool invocations, and execution steps across all brain storage
  directories under ~/.gemini. Use whenever asked to list recent/past sessions,
  review session histories, inspect tool executions, or debug trajectory steps.
---

# Antigravity Brain Explorer Skill

This skill provides procedures and commands to discover, inspect, and audit Antigravity session trajectories and conversation logs using the helper script [`agy-brain-explorer.py`](scripts/agy-brain-explorer.py).

## Execution Environment & Prerequisites

### 1. Always Run via `uv`
Run Python scripts using [`uv`](https://docs.astral.sh/uv/) so PEP 723 inline script dependencies (`typer>=0.12.0`) are automatically resolved and cached without manual virtual environment management.

From the workspace root:
```bash
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py [OPTIONS] [COMMAND]
```

Or from the skill folder:
```bash
uv run scripts/agy-brain-explorer.py [OPTIONS] [COMMAND]
```

### 2. Mandatory Bypass Sandbox (`BypassSandbox: true`)
> [!IMPORTANT]
> **Always set `BypassSandbox: true` when executing `run_command`.**
> 1. Running `uv run` inside Antigravity's standard sandbox fails with `Operation not permitted (os error 1)` when attempting to spawn the Python process.
> 2. Discovering and inspecting session trajectories requires reading directory structures and JSONL transcripts located in user storage at `~/.gemini/**/brain/`, which reside outside the workspace sandbox boundary.

### 3. Native Markdown Rendering
> [!TIP]
> **All results render directly as GitHub Flavored Markdown.**
> Session IDs are formatted with Antigravity UI links (`[<short_id>](conversation://<full_session_uuid>)`) so the user can click directly into past conversations from chat.

---

## Workflows & Command Reference

### 1. Discover and List Recent Sessions

Scan all brain directories under `~/.gemini` and display conversation traces ordered chronologically (newest first):

```bash
# List most recent 10 sessions formatted as Markdown with clickable conversation links (default)
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py --limit 10

# Filter by a specific brain root (e.g., 'antigravity-cli' or 'antigravity')
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py --brain antigravity --limit 10

# Filter sessions by initial user prompt query
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py -q "Please build a unified static HTML"
```

### 2. Search Sessions by Prompt or Deep Transcript (`search`)

Find sessions matching a prompt keyword or search across conversation turns and tool calls:

```bash
# Search sessions by initial prompt across all brain directories
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py search "Please build a unified static HTML"

# Filter search by brain root
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py search "build static docs" --brain antigravity-cli

# Deep search across all conversation steps (user requests, model responses, tool args, commands)
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py search "build-docs-site.js" --all-steps

# Search within a single specific session
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> search "node --test"
```

### 3. Inspect Session Overview (`summary`)

Pass a session UUID, partial prefix (e.g. `c1e9ba23`), or directory path to view metadata, timing, duration, model, workspace, and tool usage frequencies:

```bash
# Markdown formatted overview (default)
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION_ID_OR_PREFIX>
```

### 4. Browse Conversation Timeline (`steps`)

Display conversation turns with step numbers, timestamps, sources (`USER_EXPLICIT`, `MODEL`), types, and preview/actions:

```bash
# Markdown table of conversation steps (default)
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> steps --limit 20

# Filter to steps that called tools
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> steps --tools-only

# Filter to user prompt steps only
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> steps --user-only
```

### 5. Drill Down into a Specific Step (`step`)

Inspect the user prompt, model thinking, exact tool call parameters, triggering action, and step output logs:

```bash
# View step 5 details formatted in Markdown
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> step 5

# Limit step output log preview to 100 lines
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> step 5 --lines 100
```

### 6. Audit Tool & Command Executions

Quickly review all tool invocations or shell commands run during a session:

```bash
# List all tool invocations with targets and parameters in Markdown
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> tools

# Audit all shell commands run via run_command with working directories in Markdown
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> commands
```

### 7. Inspect Raw JSON Records (`raw`)

Retrieve untruncated JSON step data from `transcript_full.jsonl`:

```bash
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> raw 1 --full
```
