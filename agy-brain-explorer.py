# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "typer>=0.12.0",
#     "rich>=13.7.0",
# ]
# ///

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

console = Console()
err_console = Console(stderr=True)


@dataclass
class SessionData:
    session_dir: Path
    session_id: str
    transcript_path: Path
    transcript_full_path: Path
    steps: list[dict[str, Any]]
    full_steps: list[dict[str, Any]]
    steps_by_index: dict[int, dict[str, Any]]
    full_steps_by_index: dict[int, dict[str, Any]]
    as_json: bool = False

    @classmethod
    def load(cls, session_dir: Path, as_json: bool = False) -> SessionData:
        session_dir = session_dir.resolve()
        if not session_dir.exists() or not session_dir.is_dir():
            raise typer.BadParameter(
                f"Directory '{session_dir}' does not exist or is not a directory."
            )

        logs_dir = session_dir / ".system_generated" / "logs"
        transcript_path = logs_dir / "transcript.jsonl"
        transcript_full_path = logs_dir / "transcript_full.jsonl"

        if not transcript_path.exists() and not transcript_full_path.exists():
            raise typer.BadParameter(
                f"Directory '{session_dir}' does not appear to be an Antigravity session "
                f"(missing {transcript_path})."
            )

        steps: list[dict[str, Any]] = []
        if transcript_path.exists():
            with open(transcript_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        steps.append(json.loads(line))

        full_steps: list[dict[str, Any]] = []
        if transcript_full_path.exists():
            with open(transcript_full_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        full_steps.append(json.loads(line))
        else:
            full_steps = steps

        if not steps and full_steps:
            steps = full_steps

        steps_by_index = {s["step_index"]: s for s in steps if "step_index" in s}
        full_steps_by_index = {
            s["step_index"]: s for s in full_steps if "step_index" in s
        }

        return cls(
            session_dir=session_dir,
            session_id=session_dir.name,
            transcript_path=transcript_path,
            transcript_full_path=transcript_full_path,
            steps=steps,
            full_steps=full_steps,
            steps_by_index=steps_by_index,
            full_steps_by_index=full_steps_by_index,
            as_json=as_json,
        )

    def get_step_output_file(self, step_index: int) -> Path | None:
        p = (
            self.session_dir
            / ".system_generated"
            / "steps"
            / str(step_index)
            / "output.txt"
        )
        return p if p.exists() else None

    def get_user_request_clean(self) -> str:
        for s in self.steps:
            if s.get("type") == "USER_INPUT":
                content = s.get("content", "")
                m = re.search(
                    r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", content, re.DOTALL
                )
                if m:
                    return m.group(1).strip()
                return content.strip()
        return "(none)"

    def get_metadata_info(self) -> dict[str, str]:
        meta: dict[str, str] = {}
        for s in self.steps:
            if s.get("type") == "USER_INPUT":
                content = s.get("content", "")
                # Model selection
                m_model = re.search(
                    r"setting `Model Selection` from .*? to ([^\n\r]+?)\.\s*No need",
                    content,
                )
                if m_model:
                    meta["Model"] = m_model.group(1).strip()
                # Local time
                m_time = re.search(r"The current local time is:\s*([^\n\r.]+)", content)
                if m_time:
                    meta["Local Time"] = m_time.group(1).strip()
                # Mentions (exclude template keyword 'ITEM' and deduplicate)
                all_mentions = re.findall(r"@\[([^\]]+)\]", content)
                filtered_mentions = list(
                    dict.fromkeys(m for m in all_mentions if m != "ITEM")
                )
                if filtered_mentions:
                    meta["Mentioned Items"] = ", ".join(filtered_mentions)
                break

        # Workspace detection from tool calls
        for s in self.full_steps:
            for tc in s.get("tool_calls", []):
                args = tc.get("args", {})
                cwd = args.get("Cwd")
                if cwd:
                    meta["Workspace"] = cwd
                    break
            if "Workspace" in meta:
                break
        return meta


def find_session_directory(session_arg: str) -> Path:
    """Resolve session_arg to a directory by checking:

    1. Explicit path (relative or absolute, expanded)
    2. Local directory in CWD
    3. Exact and prefix matches in ~/.gemini/antigravity*/brain/
    """
    raw_path = Path(session_arg).expanduser()
    try:
        resolved_path = raw_path.resolve()
    except OSError:
        resolved_path = raw_path

    # Check direct path first
    if resolved_path.is_dir():
        logs_dir = resolved_path / ".system_generated" / "logs"
        if (logs_dir / "transcript.jsonl").exists() or (
            logs_dir / "transcript_full.jsonl"
        ).exists():
            return resolved_path

    # Check relative to CWD
    local_path = (Path.cwd() / session_arg).resolve()
    if local_path.is_dir():
        logs_dir = local_path / ".system_generated" / "logs"
        if (logs_dir / "transcript.jsonl").exists() or (
            logs_dir / "transcript_full.jsonl"
        ).exists():
            return local_path

    # Search in ~/.gemini/antigravity*/brain/
    gemini_dir = Path.home() / ".gemini"
    brain_dirs: list[Path] = []
    if gemini_dir.is_dir():
        for ag_dir in sorted(gemini_dir.glob("antigravity*")):
            brain = ag_dir / "brain"
            if brain.is_dir():
                brain_dirs.append(brain)

    # 1. Exact match in brain directories
    exact_matches: list[Path] = []
    for brain in brain_dirs:
        target = brain / session_arg
        if target.is_dir():
            exact_matches.append(target)

    if len(exact_matches) == 1:
        return exact_matches[0]
    elif len(exact_matches) > 1:
        return max(exact_matches, key=lambda p: p.stat().st_mtime)

    # 2. Prefix / partial match in brain directories
    clean_arg = session_arg.lower().strip()
    partial_matches: list[Path] = []
    for brain in brain_dirs:
        try:
            for entry in brain.iterdir():
                if entry.is_dir() and entry.name.lower().startswith(clean_arg):
                    partial_matches.append(entry)
        except PermissionError:
            continue

    if len(partial_matches) == 1:
        return partial_matches[0]
    elif len(partial_matches) > 1:
        match_list = "\n  - ".join(
            f"{p.name} ({p.parent.parent.name})" for p in partial_matches[:10]
        )
        raise typer.BadParameter(
            f"Multiple sessions matched '{session_arg}':\n  - {match_list}\n"
            "Please specify the full session ID or an explicit path."
        )

    # If resolved_path exists as a dir, return it so SessionData.load can give a specific missing transcript error
    if resolved_path.is_dir():
        return resolved_path

    searched_dirs = (
        "\n  - ".join(str(b) for b in brain_dirs) if brain_dirs else "(none found)"
    )
    raise typer.BadParameter(
        f"Session '{session_arg}' could not be found as a directory path or inside Antigravity brain folders.\n"
        f"Checked path: {resolved_path}\n"
        f"Searched brain folders:\n  - {searched_dirs}"
    )


app = typer.Typer(
    help="Antigravity Session Exploration CLI: inspect transcripts, tool calls, and execution steps.",
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def show_summary(data: SessionData, output_json: bool) -> None:
    """Render session summary either as JSON or formatted Rich tables."""
    start_time: datetime | None = None
    end_time: datetime | None = None
    if data.steps:
        try:
            start_time = datetime.fromisoformat(data.steps[0].get("created_at", ""))
            end_time = datetime.fromisoformat(data.steps[-1].get("created_at", ""))
        except (ValueError, TypeError):
            pass

    duration_str = (
        str(end_time - start_time) if (start_time and end_time) else "unknown"
    )
    duration_sec = (
        (end_time - start_time).total_seconds() if (start_time and end_time) else None
    )

    meta = data.get_metadata_info()
    scratch_items = (
        list((data.session_dir / "scratch").glob("*"))
        if (data.session_dir / "scratch").exists()
        else []
    )
    uploaded_items = (
        list((data.session_dir / ".user_uploaded").glob("*"))
        if (data.session_dir / ".user_uploaded").exists()
        else []
    )
    user_req = data.get_user_request_clean()

    tool_counts: dict[str, int] = {}
    for s in data.full_steps:
        for tc in s.get("tool_calls", []):
            name = tc.get("name", "unknown")
            tool_counts[name] = tool_counts.get(name, 0) + 1

    if output_json:
        summary_dict = {
            "session_id": data.session_id,
            "directory": str(data.session_dir),
            "started_at": start_time.isoformat() if start_time else None,
            "ended_at": end_time.isoformat() if end_time else None,
            "duration_seconds": duration_sec,
            "duration": duration_str,
            "total_steps": len(data.steps),
            "metadata": meta,
            "scratch_files": len(scratch_items),
            "uploaded_files": len(uploaded_items),
            "user_request": user_req,
            "tool_invocations": tool_counts,
        }
        print(json.dumps(summary_dict, indent=2))
        return

    overview_table = Table(
        box=box.ROUNDED,
        show_header=False,
        title="Session Overview",
        title_style="bold cyan",
    )
    overview_table.add_column("Key", style="bold green", width=20)
    overview_table.add_column("Value", style="white")

    overview_table.add_row("Session ID", data.session_id)
    overview_table.add_row("Directory", str(data.session_dir))
    overview_table.add_row("Started At", str(start_time) if start_time else "unknown")
    overview_table.add_row("Ended At", str(end_time) if end_time else "unknown")
    overview_table.add_row("Duration", duration_str)
    overview_table.add_row("Total Steps", str(len(data.steps)))

    for k, v in meta.items():
        overview_table.add_row(k, v)

    overview_table.add_row("Scratch Files", str(len(scratch_items)))
    overview_table.add_row("Uploaded Files", str(len(uploaded_items)))

    console.print(overview_table)

    # User Request Panel
    console.print(
        Panel(
            user_req,
            title="[bold yellow]User Request[/bold yellow]",
            border_style="yellow",
            box=box.ROUNDED,
        )
    )

    if tool_counts:
        tools_table = Table(
            box=box.SIMPLE_HEAVY,
            title="Tool Invocations",
            title_style="bold magenta",
        )
        tools_table.add_column("Tool Name", style="bold cyan")
        tools_table.add_column("Count", justify="right", style="bold white")
        for tool, count in sorted(
            tool_counts.items(), key=lambda item: item[1], reverse=True
        ):
            tools_table.add_row(tool, str(count))
        console.print(tools_table)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    session: Annotated[
        str,
        typer.Argument(
            metavar="SESSION",
            help="Path to session directory OR session ID (searched in ~/.gemini/antigravity*/brain).",
        ),
    ],
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            "-j",
            help="Output results as JSON formatted content.",
        ),
    ] = False,
) -> None:
    """Initialize session data from a path or session ID (defaults to summary if no subcommand)."""
    session_dir = find_session_directory(session)
    ctx.obj = SessionData.load(session_dir, as_json=as_json)

    if ctx.invoked_subcommand is None:
        show_summary(ctx.obj, output_json=as_json)


@app.command(name="summary")
def cmd_summary(
    ctx: typer.Context,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            "-j",
            help="Output results as JSON formatted content.",
        ),
    ] = False,
) -> None:
    """Show high-level overview of the session, metadata, timing, and tool statistics."""
    data: SessionData = ctx.obj
    output_json = as_json or data.as_json
    show_summary(data, output_json=output_json)


@app.command(name="steps")
def cmd_steps(
    ctx: typer.Context,
    tools_only: Annotated[
        bool,
        typer.Option(
            "--tools-only",
            "-t",
            help="Only show steps with tool calls.",
        ),
    ] = False,
    user_only: Annotated[
        bool,
        typer.Option(
            "--user-only",
            "-u",
            help="Only show user input steps.",
        ),
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            "-n",
            help="Limit number of steps shown.",
        ),
    ] = None,
    offset: Annotated[
        int,
        typer.Option(
            "--offset",
            help="Number of steps to skip.",
        ),
    ] = 0,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            "-j",
            help="Output results as JSON formatted content.",
        ),
    ] = False,
) -> None:
    """List timeline of conversation steps in a formatted table."""
    data: SessionData = ctx.obj
    output_json = as_json or data.as_json

    table = Table(
        box=box.ROUNDED,
        title=f"Timeline for {data.session_id}",
        title_style="bold cyan",
    )
    table.add_column("#", style="dim", justify="right", width=4)
    table.add_column("Time", style="cyan", width=8)
    table.add_column("Source", style="green", width=14)
    table.add_column("Type", style="yellow", width=18)
    table.add_column("Preview / Action", style="white")

    matched = 0
    json_results: list[dict[str, Any]] = []

    for s in data.full_steps:
        idx = s.get("step_index", 0)
        source = s.get("source", "")
        tp = s.get("type", "")
        tool_calls = s.get("tool_calls", [])

        if tools_only and not tool_calls:
            continue
        if user_only and tp != "USER_INPUT":
            continue

        if matched < offset:
            matched += 1
            continue

        if limit is not None and matched >= offset + limit:
            break

        time_str = ""
        try:
            time_str = datetime.fromisoformat(s.get("created_at", "")).strftime(
                "%H:%M:%S"
            )
        except (ValueError, TypeError):
            pass

        # Build preview string
        preview = ""
        clean_preview = ""
        if tool_calls:
            calls_desc = []
            for tc in tool_calls:
                name = tc.get("name", "tool")
                args = tc.get("args", {})
                action = (
                    args.get("toolAction")
                    or args.get("CommandLine")
                    or args.get("AbsolutePath")
                    or ""
                )
                if action:
                    calls_desc.append(f"{name} ({action})")
                else:
                    calls_desc.append(name)
            clean_preview = "; ".join(calls_desc)
            preview = "[bold magenta]" + clean_preview + "[/bold magenta]"
        elif tp == "USER_INPUT":
            content = s.get("content", "")
            m = re.search(
                r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", content, re.DOTALL
            )
            clean_text = m.group(1).strip() if m else content.strip()
            clean_preview = clean_text.replace("\n", " ")[:90]
            preview = clean_preview
        elif tp == "GENERIC":
            content = s.get("content", "")
            first_line = (
                content.strip().splitlines()[0] if content.strip() else "(empty)"
            )
            clean_preview = first_line[:90]
            preview = f"[dim]{clean_preview}[/dim]"
        else:
            content = s.get("content", "")
            clean_preview = content.replace("\n", " ")[:90]
            preview = clean_preview

        if output_json:
            json_results.append(
                {
                    "step_index": idx,
                    "time": time_str,
                    "created_at": s.get("created_at"),
                    "source": source,
                    "type": tp,
                    "status": s.get("status"),
                    "preview": clean_preview,
                    "has_tool_calls": bool(tool_calls),
                    "tool_calls": [
                        {
                            "name": tc.get("name"),
                            "action": tc.get("args", {}).get("toolAction"),
                            "summary": tc.get("args", {}).get("toolSummary"),
                            "args": tc.get("args", {}),
                        }
                        for tc in tool_calls
                    ],
                }
            )
        else:
            table.add_row(str(idx), time_str, source, tp, preview)

        matched += 1

    if output_json:
        print(json.dumps(json_results, indent=2))
    else:
        console.print(table)


@app.command(name="step")
def cmd_step(
    ctx: typer.Context,
    step_index: Annotated[
        int,
        typer.Argument(help="Step index to inspect."),
    ],
    max_lines: Annotated[
        int,
        typer.Option(
            "--lines",
            "-l",
            help="Max lines of output to display.",
        ),
    ] = 50,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            "-j",
            help="Output results as JSON formatted content.",
        ),
    ] = False,
) -> None:
    """Inspect detailed information, tool calls, and output of a specific step."""
    data: SessionData = ctx.obj
    output_json = as_json or data.as_json

    s = data.full_steps_by_index.get(step_index)
    if not s:
        err_console.print(
            f"[bold red]Error:[/bold red] Step index {step_index} not found in session."
        )
        raise typer.Exit(code=1)

    step_out_file = data.get_step_output_file(step_index)
    step_output_str: str | None = None
    if step_out_file:
        step_output_str = step_out_file.read_text(encoding="utf-8", errors="replace")

    if output_json:
        step_data = dict(s)
        if step_output_str is not None:
            step_data["step_output"] = step_output_str
        print(json.dumps(step_data, indent=2))
        return

    source = s.get("source", "")
    tp = s.get("type", "")
    created_at = s.get("created_at", "")
    status = s.get("status", "")

    header_text = Text.assemble(
        ("Step ", "bold white"),
        (str(step_index), "bold cyan"),
        ("  |  Source: ", "dim"),
        (source, "green"),
        ("  |  Type: ", "dim"),
        (tp, "yellow"),
        ("  |  Status: ", "dim"),
        (status, "blue"),
        ("  |  Time: ", "dim"),
        (created_at, "magenta"),
    )
    console.print(Panel(header_text, box=box.ROUNDED, border_style="cyan"))

    # Content
    content = s.get("content")
    if content:
        console.print(
            Panel(content, title="Content", box=box.ROUNDED, border_style="blue")
        )

    # Thinking if present
    thinking = s.get("thinking")
    if thinking:
        console.print(
            Panel(thinking, title="Thinking", box=box.ROUNDED, border_style="dim")
        )

    # Tool calls
    tool_calls = s.get("tool_calls", [])
    if tool_calls:
        for idx, tc in enumerate(tool_calls, 1):
            name = tc.get("name", "unknown")
            args = tc.get("args", {})
            args_json = json.dumps(args, indent=2)
            syntax = Syntax(args_json, "json", theme="monokai", word_wrap=True)
            console.print(
                Panel(
                    syntax,
                    title=f"[bold magenta]Tool Call #{idx}: {name}[/bold magenta]",
                    box=box.ROUNDED,
                    border_style="magenta",
                )
            )

    # Step execution output file if present
    if step_output_str is not None and step_out_file:
        lines = step_output_str.splitlines()
        truncated = False
        if len(lines) > max_lines:
            display_text = (
                "\n".join(lines[:max_lines])
                + f"\n\n... [truncated {len(lines) - max_lines} lines; use --lines to show more] ..."
            )
            truncated = True
        else:
            display_text = step_output_str

        console.print(
            Panel(
                display_text,
                title=f"[bold green]Step Output ({step_out_file.name})[/bold green]"
                + (" [dim](truncated)[/dim]" if truncated else ""),
                box=box.ROUNDED,
                border_style="green",
            )
        )


@app.command(name="tools")
def cmd_tools(
    ctx: typer.Context,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            "-j",
            help="Output results as JSON formatted content.",
        ),
    ] = False,
) -> None:
    """List all tool calls executed throughout the entire session."""
    data: SessionData = ctx.obj
    output_json = as_json or data.as_json

    if output_json:
        tools_list: list[dict[str, Any]] = []
        for s in data.full_steps:
            idx = s.get("step_index", 0)
            for tc in s.get("tool_calls", []):
                args = tc.get("args", {})
                tools_list.append(
                    {
                        "step_index": idx,
                        "tool": tc.get("name", ""),
                        "action": args.get("toolAction")
                        or args.get("toolSummary")
                        or "",
                        "summary": args.get("toolSummary") or "",
                        "args": args,
                    }
                )
        print(json.dumps(tools_list, indent=2))
        return

    table = Table(box=box.ROUNDED, title="All Tool Calls", title_style="bold magenta")
    table.add_column("Step", style="dim", justify="right", width=5)
    table.add_column("Tool", style="bold cyan", width=14)
    table.add_column("Action / Summary", style="yellow", width=25)
    table.add_column("Parameters / Target", style="white")

    for s in data.full_steps:
        idx = s.get("step_index", 0)
        tool_calls = s.get("tool_calls", [])
        for tc in tool_calls:
            name = tc.get("name", "")
            args = tc.get("args", {})
            action = args.get("toolAction") or args.get("toolSummary") or ""

            target = ""
            if "CommandLine" in args:
                target = (
                    f"[bold]{args['CommandLine']}[/bold] (cwd: {args.get('Cwd', '')})"
                )
            elif "AbsolutePath" in args:
                target = args["AbsolutePath"]
            elif "DirectoryPath" in args:
                target = args["DirectoryPath"]
            elif "TargetFile" in args:
                target = args["TargetFile"]
            else:
                target = json.dumps(
                    {k: v for k, v in args.items() if not k.startswith("tool")}
                )[:80]

            table.add_row(str(idx), name, action, target)

    console.print(table)


@app.command(name="commands")
def cmd_commands(
    ctx: typer.Context,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            "-j",
            help="Output results as JSON formatted content.",
        ),
    ] = False,
) -> None:
    """List all shell commands run via run_command with details and working directories."""
    data: SessionData = ctx.obj
    output_json = as_json or data.as_json

    if output_json:
        cmds_list: list[dict[str, Any]] = []
        for s in data.full_steps:
            idx = s.get("step_index", 0)
            for tc in s.get("tool_calls", []):
                if tc.get("name") == "run_command":
                    args = tc.get("args", {})
                    cmds_list.append(
                        {
                            "step_index": idx,
                            "command": args.get("CommandLine", ""),
                            "cwd": args.get("Cwd", ""),
                            "action": args.get("toolAction")
                            or args.get("toolSummary")
                            or "",
                            "wait_ms": args.get("WaitMsBeforeAsync"),
                            "args": args,
                        }
                    )
        print(json.dumps(cmds_list, indent=2))
        return

    table = Table(
        box=box.ROUNDED, title="Executed Shell Commands", title_style="bold green"
    )
    table.add_column("Step", style="dim", justify="right", width=5)
    table.add_column("Working Directory (Cwd)", style="cyan", width=30)
    table.add_column("Command Line", style="bold white")

    for s in data.full_steps:
        idx = s.get("step_index", 0)
        for tc in s.get("tool_calls", []):
            if tc.get("name") == "run_command":
                args = tc.get("args", {})
                cmd = args.get("CommandLine", "")
                cwd = args.get("Cwd", "")
                table.add_row(str(idx), cwd, cmd)

    console.print(table)


@app.command(name="raw")
def cmd_raw(
    ctx: typer.Context,
    step_index: Annotated[
        int,
        typer.Argument(help="Step index to dump."),
    ],
    full: Annotated[
        bool,
        typer.Option(
            "--full/--compact",
            help="Use transcript_full vs compact transcript.",
        ),
    ] = True,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            "-j",
            help="Output results as JSON formatted content.",
        ),
    ] = False,
) -> None:
    """Print the raw JSON record of a specific step."""
    data: SessionData = ctx.obj
    output_json = as_json or data.as_json

    lookup = data.full_steps_by_index if full else data.steps_by_index
    s = lookup.get(step_index)
    if not s:
        err_console.print(f"[bold red]Error:[/bold red] Step {step_index} not found.")
        raise typer.Exit(code=1)

    json_str = json.dumps(s, indent=2)
    if output_json:
        print(json_str)
    else:
        syntax = Syntax(json_str, "json", theme="monokai", word_wrap=True)
        console.print(syntax)


def main() -> None:
    """Entrypoint that defaults to the 'summary' subcommand if none is provided."""
    subcommands = {"summary", "steps", "step", "tools", "commands", "raw"}
    help_flags = {"-h", "--help"}

    args = sys.argv[1:]
    if args and not any(arg in help_flags for arg in args):
        has_subcommand = any(arg in subcommands for arg in args)
        if not has_subcommand:
            for i, arg in enumerate(args):
                if not arg.startswith("-"):
                    sys.argv.insert(i + 2, "summary")
                    break

    app()


if __name__ == "__main__":
    main()
