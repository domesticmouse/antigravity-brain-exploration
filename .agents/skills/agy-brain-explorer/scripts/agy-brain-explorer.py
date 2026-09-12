# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "typer>=0.12.0",
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

    @classmethod
    def load(cls, session_dir: Path) -> SessionData:
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


def sanitize_md_cell(text: str | None) -> str:
    """Sanitize text for use inside a Markdown table cell."""
    if not text:
        return ""
    return (
        text.replace("\r\n", " ")
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("|", "\\|")
        .strip()
    )


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


def format_datetime_display(dt: datetime | None, raw_str: str) -> str:
    """Format datetime for Markdown display in user local time if possible."""
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
    print("\nInteractive Trace Explorer")
    while True:
        try:
            choice = input(
                f"\nEnter trace #[1-{len(traces)}] or session ID to inspect (q to quit): "
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
                print(
                    f"Error: Index {idx} out of range (1-{len(traces)}).",
                    file=sys.stderr,
                )
                continue
        else:
            matches = [
                t for t in traces if t.session_id.lower().startswith(choice.lower())
            ]
            if len(matches) == 1:
                selected_trace = matches[0]
            elif len(matches) > 1:
                print(
                    f"Error: Multiple traces match '{choice}'. Please provide more characters.",
                    file=sys.stderr,
                )
                continue
            else:
                print(
                    f"Error: No trace matches '{choice}'.",
                    file=sys.stderr,
                )
                continue

        print(
            f"\nSelected session: {selected_trace.session_id} ({selected_trace.source_brain})"
        )
        session_data = SessionData.load(selected_trace.session_dir)

        action = (
            input(
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
            show_summary(session_data)


def run_explorer(
    limit: int | None = 30,
    asc: bool = False,
    brain_filter: str | None = None,
    interactive: bool = False,
) -> None:
    """List all traces in Markdown ordered chronologically by creation date/time."""
    traces = discover_traces(brain_filter=brain_filter, asc=asc)

    if not traces:
        print("*No Antigravity conversation traces found under ~/.gemini.*")
        if brain_filter:
            print(f"\n*Filter applied: `--brain {brain_filter}`*")
        return

    traces_to_show = traces[:limit] if limit else traces
    order_str = "oldest first" if asc else "newest first"
    header = f"### Antigravity Conversation Traces ({len(traces)} total"
    if brain_filter:
        header += f", filter: `{brain_filter}`"
    header += f", {order_str})\n"
    print(header)
    print("| # | Created | Brain | Session ID | Steps | User Request |")
    print("| :--- | :--- | :--- | :--- | :---: | :--- |")
    for idx, t in enumerate(traces_to_show, 1):
        created_display = format_datetime_display(t.created_dt, t.created_at)
        req_sanitized = sanitize_md_cell(t.user_request[:100])
        session_link = f"[`{t.session_id[:8]}`](conversation://{t.session_id})"
        print(
            f"| {idx} | {created_display} | {t.source_brain} | {session_link} | {t.step_count} | {req_sanitized} |"
        )
    if limit and len(traces) > limit:
        print(
            f"\n*Showing {len(traces_to_show)} of {len(traces)} traces. Use `--all` or `--limit` to show more.*"
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
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output trace listing as Markdown formatted content.",
        ),
    ] = True,
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


def show_summary(data: SessionData) -> None:
    """Render session summary as Markdown."""
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

    print(f"### Session Overview: `{data.session_id}`\n")
    print("| Property | Value |")
    print("| :--- | :--- |")
    print(
        f"| **Session ID** | [`{data.session_id}`](conversation://{data.session_id}) |"
    )
    print(f"| **Directory** | `{data.session_dir}` |")
    print(f"| **Started At** | {start_time if start_time else 'unknown'} |")
    print(f"| **Ended At** | {end_time if end_time else 'unknown'} |")
    print(f"| **Duration** | {duration_str} |")
    print(f"| **Total Steps** | {len(data.steps)} |")
    for k, v in meta.items():
        print(f"| **{sanitize_md_cell(k)}** | {sanitize_md_cell(str(v))} |")
    print(f"| **Scratch Files** | {len(scratch_items)} |")
    print(f"| **Uploaded Files** | {len(uploaded_items)} |\n")

    print("#### Initial User Request")
    print(f"> {sanitize_md_cell(user_req)}\n")

    if tool_counts:
        print("#### Tool Invocations")
        print("| Tool Name | Count |")
        print("| :--- | :---: |")
        for tool, count in sorted(
            tool_counts.items(), key=lambda item: item[1], reverse=True
        ):
            print(f"| `{tool}` | {count} |")


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
) -> None:
    """Render conversation timeline steps as Markdown."""
    matched = 0
    md_results: list[tuple[int, str, str, str, str]] = []

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
        elif tp == "USER_INPUT":
            content = s.get("content", "")
            m = re.search(
                r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", content, re.DOTALL
            )
            clean_text = m.group(1).strip() if m else content.strip()
            clean_preview = clean_text.replace("\n", " ")[:90]
        elif tp == "GENERIC":
            trigger = find_triggering_step(data, idx)
            if trigger:
                parent_idx, parent_step = trigger
                parent_tools = parent_step.get("tool_calls", [])
                tools_desc = ", ".join(tc.get("name", "tool") for tc in parent_tools)
                clean_preview = f"Result of Step {parent_idx} ({tools_desc})"
            else:
                content = s.get("content", "")
                first_line = (
                    content.strip().splitlines()[0] if content.strip() else "(empty)"
                )
                clean_preview = first_line[:90]
        else:
            content = s.get("content", "")
            clean_preview = content.replace("\n", " ")[:90]

        md_results.append(
            (idx, time_str, source, tp, sanitize_md_cell(clean_preview))
        )
        matched += 1

    print(f"### Timeline for `{data.session_id}`\n")
    print("| Step | Time | Source | Type | Preview / Action |")
    print("| :---: | :--- | :--- | :--- | :--- |")
    for s_idx, t_str, src, s_type, p_view in md_results:
        print(f"| {s_idx} | {t_str} | `{src}` | `{s_type}` | {p_view} |")


def show_tools(data: SessionData) -> None:
    """Render list of all tool invocations as Markdown."""
    print(f"### Tool Invocations for `{data.session_id}`\n")
    print("| Step | Tool | Action / Summary | Parameters / Target |")
    print("| :---: | :--- | :--- | :--- |")
    for s in data.full_steps:
        idx = s.get("step_index", 0)
        for tc in s.get("tool_calls", []):
            name = tc.get("name", "")
            args = tc.get("args", {})
            action = args.get("toolAction") or args.get("toolSummary") or ""
            target = ""
            if "CommandLine" in args:
                target = f"`{args['CommandLine']}` (cwd: `{args.get('Cwd', '')}`)"
            elif "AbsolutePath" in args:
                target = f"`{args['AbsolutePath']}`"
            elif "DirectoryPath" in args:
                target = f"`{args['DirectoryPath']}`"
            elif "TargetFile" in args:
                target = f"`{args['TargetFile']}`"
            else:
                target = json.dumps(
                    {k: v for k, v in args.items() if not k.startswith("tool")}
                )[:80]
            print(
                f"| {idx} | `{name}` | {sanitize_md_cell(action)} | {sanitize_md_cell(target)} |"
            )


def show_commands(data: SessionData) -> None:
    """Render list of all executed shell commands as Markdown."""
    print(f"### Executed Shell Commands for `{data.session_id}`\n")
    print("| Step | Working Directory (Cwd) | Command Line |")
    print("| :---: | :--- | :--- |")
    for s in data.full_steps:
        idx = s.get("step_index", 0)
        for tc in s.get("tool_calls", []):
            if tc.get("name") == "run_command":
                args = tc.get("args", {})
                cmd = args.get("CommandLine", "")
                cwd = args.get("Cwd", "")
                print(
                    f"| {idx} | `{sanitize_md_cell(cwd)}` | `{sanitize_md_cell(cmd)}` |"
                )


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
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """Initialize session data from a path or session ID (defaults to summary if no subcommand)."""
    session_dir = find_session_directory(session)
    ctx.obj = SessionData.load(session_dir)

    if ctx.invoked_subcommand is None:
        show_summary(ctx.obj)


@session_app.command(name="summary")
def cmd_summary(
    ctx: typer.Context,
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """Show high-level overview of the session, metadata, timing, and tool statistics as Markdown."""
    data: SessionData = ctx.obj
    show_summary(data)


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
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """List timeline of conversation steps as Markdown."""
    data: SessionData = ctx.obj
    show_steps(
        data,
        tools_only=tools_only,
        user_only=user_only,
        limit=limit,
        offset=offset,
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
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """Inspect detailed information, tool calls, and output of a specific step in Markdown."""
    data: SessionData = ctx.obj

    s = data.full_steps_by_index.get(step_index)
    if not s:
        print(
            f"Error: Step index {step_index} not found in session.",
            file=sys.stderr,
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

    source = s.get("source", "")
    tp = s.get("type", "")
    created_at = s.get("created_at", "")
    status = s.get("status", "")

    print(f"### Step {step_index} Details\n")
    print(f"- **Source**: `{source}`")
    print(f"- **Type**: `{tp}`")
    print(f"- **Status**: `{status}`")
    print(f"- **Time**: `{created_at}`")
    if trigger and parent_idx is not None:
        tool_names_str = ", ".join(
            f"`{tc.get('name', 'tool')}`" for tc in parent_tools
        )
        print(f"- **Result of**: Step {parent_idx} ({tool_names_str})")
    print()

    if trigger and parent_idx is not None:
        print(f"#### Triggering Action (Step {parent_idx})")
        for tc in parent_tools:
            tname = tc.get("name", "unknown")
            targs = tc.get("args", {})
            action = targs.get("toolAction") or targs.get("toolSummary") or ""
            print(f"- **Tool**: `{tname}`")
            if action:
                print(f"  - **Action**: {action}")
            if "CommandLine" in targs:
                print(
                    f"  - **Command**: `{targs['CommandLine']}` (cwd: `{targs.get('Cwd', '')}`)"
                )
            elif "AbsolutePath" in targs:
                print(f"  - **Path**: `{targs['AbsolutePath']}`")
            elif "TargetFile" in targs:
                print(f"  - **File**: `{targs['TargetFile']}`")
        print()

    content = s.get("content")
    if content:
        print("#### Content")
        print("```")
        print(content)
        print("```\n")

    thinking = s.get("thinking")
    if thinking:
        print("#### Thinking")
        print("```")
        print(thinking)
        print("```\n")

    tool_calls = s.get("tool_calls", [])
    if tool_calls:
        print("#### Tool Calls")
        for tc_idx, tc in enumerate(tool_calls, 1):
            name = tc.get("name", "unknown")
            args = tc.get("args", {})
            print(f"**Tool Call #{tc_idx}: `{name}`**")
            print("```json")
            print(json.dumps(args, indent=2))
            print("```\n")

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
            print(
                f"#### Step Output (`{step_out_file.name}`)"
                + (" *(truncated)*" if truncated else "")
            )
            print("```")
            print(display_text)
            print("```\n")


@session_app.command(name="tools")
def cmd_tools(
    ctx: typer.Context,
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """List all tool calls executed throughout the entire session as Markdown."""
    data: SessionData = ctx.obj
    show_tools(data)


@session_app.command(name="commands")
def cmd_commands(
    ctx: typer.Context,
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """List all shell commands run via run_command with details and working directories as Markdown."""
    data: SessionData = ctx.obj
    show_commands(data)


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
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """Print the raw JSON record of a specific step in a Markdown code block."""
    data: SessionData = ctx.obj

    lookup = data.full_steps_by_index if full else data.steps_by_index
    s = lookup.get(step_index)
    if not s:
        print(f"Error: Step {step_index} not found.", file=sys.stderr)
        raise typer.Exit(code=1)

    json_str = json.dumps(s, indent=2)
    print(f"### Raw Step {step_index} Record\n")
    print("```json")
    print(json_str)
    print("```")


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
        # No arguments or only flags (e.g. `agy-brain-explorer.py` or `--md`)
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
