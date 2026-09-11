# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "typer>=0.12.0",
#     "rich>=13.7.0",
# ]
# ///

from __future__ import annotations

import contextlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
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


@dataclass
class TraceSummary:
    session_id: str
    source_brain: str
    session_dir: Path
    created_at: str
    created_dt: datetime | None
    updated_at: str
    step_count: int
    user_request: str
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        local_time_str = ""
        if self.created_dt:
            try:
                local_time_str = (
                    self.created_dt.astimezone().isoformat()
                    if self.created_dt.tzinfo
                    else self.created_dt.isoformat()
                )
            except (ValueError, OSError):
                local_time_str = self.created_at
        return {
            "session_id": self.session_id,
            "source_brain": self.source_brain,
            "directory": str(self.session_dir),
            "created_at": self.created_at,
            "created_at_local": local_time_str,
            "updated_at": self.updated_at,
            "step_count": self.step_count,
            "user_request": self.user_request,
            "model": self.model,
        }


def format_datetime_display(dt: datetime | None, raw_str: str) -> str:
    """Format datetime for terminal table display in user local time if possible."""
    if dt is not None:
        with contextlib.suppress(ValueError, OSError):
            if dt.tzinfo is not None:
                local_dt = dt.astimezone()
                return local_dt.strftime("%Y-%m-%d %H:%M")
            return dt.strftime("%Y-%m-%d %H:%M")
    return raw_str.replace("T", " ")[:16]


def find_all_brain_directories() -> list[Path]:
    """Discover all brain directories under ~/.gemini/ (e.g. antigravity, antigravity-cli, antigravity-acp)."""
    gemini_dir = Path.home() / ".gemini"
    if not gemini_dir.is_dir():
        return []

    found: dict[Path, None] = {}
    # First search for antigravity*/brain
    for ag_dir in sorted(gemini_dir.glob("antigravity*")):
        brain = ag_dir / "brain"
        if brain.is_dir():
            found[brain.resolve()] = None

    # Also search for any other brain directories under ~/.gemini
    try:
        for brain in gemini_dir.glob("**/brain"):
            if brain.is_dir():
                found[brain.resolve()] = None
    except OSError:
        pass

    return list(found.keys())


def discover_traces(
    brain_filter: str | None = None,
    asc: bool = False,
) -> list[TraceSummary]:
    """Scan all brain directories under ~/.gemini and return traces sorted chronologically by creation date/time."""
    brain_dirs = find_all_brain_directories()
    traces: list[TraceSummary] = []

    for brain in brain_dirs:
        source_brain = brain.parent.name
        if brain_filter and brain_filter.lower() not in source_brain.lower():
            continue

        try:
            entries = list(brain.iterdir())
        except OSError:
            continue

        for s in entries:
            if not s.is_dir():
                continue
            logs = s / ".system_generated" / "logs"
            t_compact = logs / "transcript.jsonl"
            t_full = logs / "transcript_full.jsonl"

            # Prefer compact for quick indexing, fallback to full
            t_file = (
                t_compact
                if t_compact.exists()
                else (t_full if t_full.exists() else None)
            )
            if not t_file:
                continue

            first_created_str: str | None = None
            last_created_str: str | None = None
            first_created_dt: datetime | None = None
            user_req: str | None = None
            model_name: str | None = None
            step_count = 0

            with (
                contextlib.suppress(json.JSONDecodeError, OSError, UnicodeDecodeError),
                open(t_file, encoding="utf-8") as f,
            ):
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    step_count += 1
                    d = json.loads(line)

                    if "created_at" in d:
                        last_created_str = d["created_at"]
                        if first_created_str is None:
                            first_created_str = d["created_at"]

                    if user_req is None and d.get("type") == "USER_INPUT":
                        content = d.get("content", "")
                        m = re.search(
                            r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>",
                            content,
                            re.DOTALL,
                        )
                        if m:
                            user_req = m.group(1).strip()
                        else:
                            lines = content.strip().splitlines()
                            user_req = lines[0].strip() if lines else "(none)"
                        m_model = re.search(
                            r"setting `Model Selection` from .*? to ([^\n\r]+?)\.\s*No need",
                            content,
                        )
                        if m_model:
                            model_name = m_model.group(1).strip()

            if first_created_str:
                with contextlib.suppress(ValueError, TypeError):
                    first_created_dt = datetime.fromisoformat(
                        first_created_str.replace("Z", "+00:00")
                    )

            if first_created_dt is None:
                with contextlib.suppress(OSError, ValueError):
                    st = s.stat()
                    first_created_dt = datetime.fromtimestamp(
                        st.st_ctime, tz=timezone.utc
                    )
                    first_created_str = first_created_dt.isoformat()

            if last_created_str is None:
                with contextlib.suppress(OSError, ValueError):
                    last_created_str = datetime.fromtimestamp(
                        s.stat().st_mtime, tz=timezone.utc
                    ).isoformat()

            traces.append(
                TraceSummary(
                    session_id=s.name,
                    source_brain=source_brain,
                    session_dir=s,
                    created_at=first_created_str or "",
                    created_dt=first_created_dt,
                    updated_at=last_created_str or "",
                    step_count=step_count,
                    user_request=(user_req or "(none)").replace("\n", " ")[:90],
                    model=model_name,
                )
            )

    def sort_key(t: TraceSummary) -> float:
        if t.created_dt:
            return t.created_dt.timestamp()
        return 0.0

    traces.sort(key=sort_key, reverse=not asc)
    return traces


def find_session_directory(session_arg: str) -> Path:
    """Resolve session_arg to a directory by checking:

    1. Explicit path (relative or absolute, expanded)
    2. Local directory in CWD
    3. Exact and prefix matches in all ~/.gemini/**/brain/ directories
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

    # Search across all brain directories in ~/.gemini
    brain_dirs = find_all_brain_directories()

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


# ---------------------------------------------------------------------------
# Explorer Presentation & CLI
# ---------------------------------------------------------------------------


def run_interactive_session_picker(traces: list[TraceSummary]) -> None:
    """Allow interactive selection and exploration of traces."""
    console.print()
    console.print("[bold cyan]Interactive Trace Explorer[/bold cyan]")
    while True:
        try:
            choice = console.input(
                f"\nEnter trace #[1-{len(traces)}] or session ID to inspect ([bold red]q[/bold red] to quit): "
            ).strip()
        except (KeyboardInterrupt, EOFError):
            break

        if choice.lower() in ("q", "quit", "exit"):
            break
        if not choice:
            continue

        selected_trace: TraceSummary | None = None
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(traces):
                selected_trace = traces[idx - 1]
            else:
                err_console.print(
                    f"[bold red]Error:[/bold red] Index {idx} out of range (1-{len(traces)})."
                )
                continue
        else:
            matches = [
                t for t in traces if t.session_id.lower().startswith(choice.lower())
            ]
            if len(matches) == 1:
                selected_trace = matches[0]
            elif len(matches) > 1:
                err_console.print(
                    f"[bold red]Error:[/bold red] Multiple traces match '{choice}'. Please provide more characters."
                )
                continue
            else:
                err_console.print(
                    f"[bold red]Error:[/bold red] No trace matches '{choice}'."
                )
                continue

        console.print(
            f"\n[bold green]Selected session:[/bold green] [bold cyan]{selected_trace.session_id}[/bold cyan] "
            f"({selected_trace.source_brain})"
        )
        session_data = SessionData.load(selected_trace.session_dir)

        action = (
            console.input(
                "Action: [1] Summary (default), [2] Steps, [3] Tools, [4] Commands, [b] Back: "
            )
            .strip()
            .lower()
        )

        if action in ("b", "back"):
            continue
        elif action in ("2", "steps", "s"):
            show_steps(session_data, limit=30)
        elif action in ("3", "tools", "t"):
            show_tools(session_data)
        elif action in ("4", "commands", "c"):
            show_commands(session_data)
        else:
            show_summary(session_data, output_json=False)


def run_explorer(
    limit: int | None = 30,
    asc: bool = False,
    brain_filter: str | None = None,
    output_json: bool = False,
    interactive: bool = False,
) -> None:
    """List or export all traces ordered chronologically by creation date/time."""
    traces = discover_traces(brain_filter=brain_filter, asc=asc)

    if output_json:
        out = [t.to_dict() for t in (traces[:limit] if limit else traces)]
        print(json.dumps(out, indent=2))
        return

    if not traces:
        err_console.print(
            "[bold yellow]No Antigravity conversation traces found under ~/.gemini.[/bold yellow]"
        )
        if brain_filter:
            err_console.print(f"[dim]Filter applied: --brain {brain_filter}[/dim]")
        return

    traces_to_show = traces[:limit] if limit else traces

    title_desc = f"Antigravity Conversation Traces ({len(traces)} total"
    if brain_filter:
        title_desc += f", filter: {brain_filter}"
    order_str = "oldest first" if asc else "newest first"
    title_desc += f", {order_str})"

    table = Table(
        box=box.ROUNDED,
        title=title_desc,
        title_style="bold cyan",
        expand=True,
    )
    table.add_column("#", style="dim", justify="right", min_width=3, max_width=4)
    table.add_column("Created", style="bold cyan", min_width=16, max_width=16)
    table.add_column("Brain", style="bold green", min_width=11, max_width=15)
    table.add_column("Session ID", style="bold white", min_width=8, max_width=8)
    table.add_column("Steps", style="yellow", justify="right", min_width=5, max_width=6)
    table.add_column(
        "User Request", style="white", ratio=1, overflow="ellipsis", no_wrap=True
    )

    for idx, t in enumerate(traces_to_show, 1):
        created_display = format_datetime_display(t.created_dt, t.created_at)
        table.add_row(
            str(idx),
            created_display,
            t.source_brain,
            t.session_id[:8],
            str(t.step_count),
            t.user_request[:80],
        )

    console.print(table)

    if limit and len(traces) > limit:
        console.print(
            f"[dim]Showing {len(traces_to_show)} of {len(traces)} traces. Use --all or --limit to show more.[/dim]"
        )
    else:
        console.print(f"[dim]Showing all {len(traces_to_show)} traces.[/dim]")

    console.print(
        "[dim]Tip: Inspect any session with: uv run agy-brain-explorer.py <SESSION_ID>[/dim]"
    )

    if interactive:
        run_interactive_session_picker(traces_to_show)


explorer_app = typer.Typer(
    help=(
        "Antigravity Session & Trace Exploration CLI: explore all conversation traces across "
        "~/.gemini brain directories, or inspect specific session transcripts, tool calls, and execution steps."
    ),
    no_args_is_help=False,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@explorer_app.callback(invoke_without_command=True)
def explorer_callback(
    ctx: typer.Context,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            "-n",
            help="Limit number of traces displayed (default: 30).",
        ),
    ] = 30,
    all_traces: Annotated[
        bool,
        typer.Option(
            "--all",
            "-a",
            help="Show all discovered traces without pagination limit.",
        ),
    ] = False,
    asc: Annotated[
        bool,
        typer.Option(
            "--asc",
            help="Order traces oldest first (default: newest first).",
        ),
    ] = False,
    brain: Annotated[
        str | None,
        typer.Option(
            "--brain",
            "-b",
            help="Filter traces by brain root directory name (e.g. 'antigravity-cli').",
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            "-j",
            help="Output trace listing as JSON formatted content.",
        ),
    ] = False,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive",
            "-i",
            help="Interactively select a session from the list to inspect.",
        ),
    ] = False,
) -> None:
    effective_limit = None if all_traces else limit
    run_explorer(
        limit=effective_limit,
        asc=asc,
        brain_filter=brain,
        output_json=as_json,
        interactive=interactive,
    )


# ---------------------------------------------------------------------------
# Single Session Inspection CLI
# ---------------------------------------------------------------------------

session_app = typer.Typer(
    help="Inspect a specific Antigravity session transcript, steps, and tool execution.",
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


def find_triggering_step(
    data: SessionData, step_index: int
) -> tuple[int, dict[str, Any]] | None:
    """Find the preceding step that dispatched tool calls resulting in step_index."""
    s = data.full_steps_by_index.get(step_index)
    if not s or s.get("type") != "GENERIC":
        return None
    for idx in range(step_index - 1, -1, -1):
        candidate = data.full_steps_by_index.get(idx)
        if candidate and candidate.get("tool_calls"):
            return idx, candidate
        if candidate and candidate.get("type") in ("USER_INPUT", "PLANNER_RESPONSE"):
            break
    return None


def show_steps(
    data: SessionData,
    tools_only: bool = False,
    user_only: bool = False,
    limit: int | None = None,
    offset: int = 0,
    output_json: bool = False,
) -> None:
    """Render conversation timeline steps as JSON or formatted table."""
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
            trigger = find_triggering_step(data, idx)
            if trigger:
                parent_idx, parent_step = trigger
                parent_tools = parent_step.get("tool_calls", [])
                tools_desc = ", ".join(tc.get("name", "tool") for tc in parent_tools)
                clean_preview = f"Result of Step {parent_idx} ({tools_desc})"
                preview = f"[dim cyan]{clean_preview}[/dim cyan]"
            else:
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
            step_item: dict[str, Any] = {
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
            step_trigger = find_triggering_step(data, idx)
            if step_trigger:
                step_item["result_of_step"] = step_trigger[0]
            json_results.append(step_item)
        else:
            table.add_row(str(idx), time_str, source, tp, preview)

        matched += 1

    if output_json:
        print(json.dumps(json_results, indent=2))
    else:
        console.print(table)


def show_tools(data: SessionData, output_json: bool = False) -> None:
    """Render list of all tool invocations as JSON or formatted table."""
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


def show_commands(data: SessionData, output_json: bool = False) -> None:
    """Render list of all executed shell commands as JSON or formatted table."""
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


@session_app.callback(invoke_without_command=True)
def session_callback(
    ctx: typer.Context,
    session: Annotated[
        str,
        typer.Argument(
            metavar="SESSION",
            help="Path to session directory OR session ID (searched in ~/.gemini/**/brain).",
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


@session_app.command(name="summary")
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


@session_app.command(name="steps")
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
    show_steps(
        data,
        tools_only=tools_only,
        user_only=user_only,
        limit=limit,
        offset=offset,
        output_json=output_json,
    )


@session_app.command(name="step")
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

    trigger = find_triggering_step(data, step_index)
    parent_idx: int | None = None
    parent_tools: list[dict[str, Any]] = []
    if trigger:
        parent_idx, parent_step = trigger
        parent_tools = parent_step.get("tool_calls", [])

    if output_json:
        step_data = dict(s)
        if trigger and parent_idx is not None:
            step_data["result_of_step"] = parent_idx
            step_data["triggering_tools"] = [
                {
                    "name": tc.get("name"),
                    "action": tc.get("args", {}).get("toolAction")
                    or tc.get("args", {}).get("toolSummary"),
                    "args": tc.get("args", {}),
                }
                for tc in parent_tools
            ]
        if step_output_str is not None:
            step_data["step_output"] = step_output_str
        print(json.dumps(step_data, indent=2))
        return

    source = s.get("source", "")
    tp = s.get("type", "")
    created_at = s.get("created_at", "")
    status = s.get("status", "")

    header_parts = [
        ("Step ", "bold white"),
        (str(step_index), "bold cyan"),
        ("  |  Source: ", "dim"),
        (source, "green"),
        ("  |  Type: ", "dim"),
        (tp, "yellow"),
    ]
    if trigger and parent_idx is not None:
        tool_names_str = ", ".join(tc.get("name", "tool") for tc in parent_tools)
        header_parts.extend(
            [
                ("  |  Result of: ", "dim"),
                (f"Step {parent_idx} ({tool_names_str})", "bold yellow"),
            ]
        )
    header_parts.extend(
        [
            ("  |  Status: ", "dim"),
            (status, "blue"),
            ("  |  Time: ", "dim"),
            (created_at, "magenta"),
        ]
    )
    header_text = Text.assemble(*header_parts)
    console.print(Panel(header_text, box=box.ROUNDED, border_style="cyan"))

    # If this step is the result of a parent step, display the triggering tool context
    if trigger and parent_idx is not None:
        tool_descs = []
        for tc in parent_tools:
            tname = tc.get("name", "unknown")
            targs = tc.get("args", {})
            action = targs.get("toolAction") or targs.get("toolSummary") or ""
            target = ""
            if "CommandLine" in targs:
                target = f"Command: {targs['CommandLine']}"
                if "Cwd" in targs:
                    target += f" (cwd: {targs['Cwd']})"
            elif "AbsolutePath" in targs:
                target = f"Path: {targs['AbsolutePath']}"
            elif "TargetFile" in targs:
                target = f"File: {targs['TargetFile']}"
            elif "DirectoryPath" in targs:
                target = f"Directory: {targs['DirectoryPath']}"
            elif "SearchDirectory" in targs:
                target = f"Directory: {targs['SearchDirectory']}, Pattern: {targs.get('Pattern', '*')}"
            elif "Query" in targs:
                target = f"Query: {targs['Query']}"
            elif "Url" in targs:
                target = f"URL: {targs['Url']}"

            desc_lines = [f"[bold cyan]Tool:[/bold cyan] {tname}"]
            if action:
                desc_lines.append(f"[bold green]Action:[/bold green] {action}")
            if target:
                desc_lines.append(f"[bold white]Target / Args:[/bold white] {target}")
            tool_descs.append("\n".join(desc_lines))

        trigger_content = "\n\n".join(tool_descs)
        console.print(
            Panel(
                trigger_content,
                title=f"[bold yellow]Triggering Action (Step {parent_idx})[/bold yellow]",
                box=box.ROUNDED,
                border_style="yellow",
            )
        )

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
    # Avoid duplicate output if step_output_str is already represented in content
    if step_output_str is not None and step_out_file:
        is_duplicate = bool(content and step_output_str.strip() in content.strip())
        if not is_duplicate:
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


@session_app.command(name="tools")
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
    show_tools(data, output_json=output_json)


@session_app.command(name="commands")
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
    show_commands(data, output_json=output_json)


@session_app.command(name="raw")
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


# ---------------------------------------------------------------------------
# CLI Routing Entrypoint
# ---------------------------------------------------------------------------


def is_explorer_invocation(args: list[str]) -> bool:
    """Determine whether the invocation targets the trace explorer or a single session."""
    explorer_cmds = {"list", "explore", "traces"}
    val_flags = {"--limit", "-n", "--brain", "-b", "--offset", "--lines", "-l"}
    non_opts: list[str] = []
    skip_next = False

    for a in args:
        if skip_next:
            skip_next = False
            continue
        if a in val_flags:
            skip_next = True
            continue
        if not a.startswith("-"):
            non_opts.append(a)

    if not non_opts:
        # No arguments or only flags (e.g. `agy-brain-explorer.py` or `--json`)
        return True

    return non_opts[0] in explorer_cmds


def main() -> None:
    """Unified entrypoint that routes between trace explorer and session inspection."""
    args = sys.argv[1:]
    help_flags = {"-h", "--help"}

    if is_explorer_invocation(args):
        # Explorer mode
        explorer_cmds = {"list", "explore", "traces"}
        filtered_args: list[str] = []
        stripped_cmd = False
        for a in args:
            if not stripped_cmd and a in explorer_cmds:
                stripped_cmd = True
                continue
            filtered_args.append(a)
        sys.argv = [sys.argv[0]] + filtered_args
        explorer_app()
    else:
        # Session inspection mode
        session_subcommands = {"summary", "steps", "step", "tools", "commands", "raw"}
        has_subcommand = any(arg in session_subcommands for arg in args)
        final_args = list(args)
        if not has_subcommand and not any(arg in help_flags for arg in args):
            for i, arg in enumerate(final_args):
                if not arg.startswith("-"):
                    final_args.insert(i + 1, "summary")
                    break
        sys.argv = [sys.argv[0]] + final_args
        session_app()


if __name__ == "__main__":
    main()
