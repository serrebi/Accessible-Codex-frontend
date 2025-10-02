"""Codex CLI orchestration helpers."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .run_result import RunResult
from . import settings
from . import backend

SESSION_FILE_RE = re.compile(
    r"rollout-[0-9T:-]+-(?P<sid>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$"
)


def codex_exec_prompt(prompt: str, password: Optional[str], timeout: int = 900) -> RunResult:
    cmd = (
        "codex --search --dangerously-bypass-approvals-and-sandbox "
        "exec --skip-git-repo-check "
        f"{backend.bash_single_quote(prompt)}"
    )
    return backend.run_as_root(cmd, password, timeout=timeout)


def codex_exec_prompt_stream(
    prompt: str,
    password: Optional[str],
    stdout_cb,
    stderr_cb,
    timeout: int = 900,
) -> RunResult:
    cmd = (
        "codex --search --dangerously-bypass-approvals-and-sandbox "
        "exec --skip-git-repo-check "
        f"{backend.bash_single_quote(prompt)}"
    )
    return backend.stream_as_root(cmd, password, timeout, stdout_cb, stderr_cb)


def codex_resume_prompt_stream(
    prompt: str,
    password: Optional[str],
    session_id: Optional[str],
    stdout_cb,
    stderr_cb,
    timeout: int = 900,
) -> RunResult:
    if session_id:
        resume_target = session_id.strip()
        cmd = (
            "codex --search --dangerously-bypass-approvals-and-sandbox "
            "exec --skip-git-repo-check resume "
            f"{backend.bash_single_quote(resume_target)} {backend.bash_single_quote(prompt)}"
        )
    else:
        cmd = (
            "codex --search --dangerously-bypass-approvals-and-sandbox "
            "exec --skip-git-repo-check resume --last "
            f"{backend.bash_single_quote(prompt)}"
        )
    return backend.stream_as_root(cmd, password, timeout, stdout_cb, stderr_cb)


def check_shell_ready() -> Tuple[bool, str]:
    result = backend.run_shell("echo SHELL_OK")
    ok = result.ok and "SHELL_OK" in result.stdout
    return (ok, result.stdout.strip() or result.stderr.strip())


def check_codex_installed() -> Tuple[bool, str]:
    result = backend.run_shell("command -v codex || true")
    path = result.stdout.strip()
    return (bool(path), path or "codex not found in PATH")


def log_codex_help() -> str:
    result = backend.run_shell("codex -h || codex --help || true")
    return (result.stdout or result.stderr or "").strip()


def list_session_files(password: Optional[str]) -> List[Tuple[float, str]]:
    script = (
        "dir=$HOME/.codex/sessions; "
        "if [ -d \"$dir\" ]; then "
        "find \"$dir\" -maxdepth 5 -type f -printf '%T@\\t%p\\n' 2>/dev/null | "
        "sort -nr | head -n 200; "
        "fi"
    )
    cmd = f"bash -lc {backend.bash_single_quote(script)}"
    result = backend.run_as_root(cmd, password, timeout=30)
    if not result.ok:
        return []

    entries: List[Tuple[float, str]] = []
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            ts_str, path = line.split('\t', 1)
            ts = float(ts_str)
        except ValueError:
            continue
        entries.append((ts, path.strip()))
    return entries


def session_snapshot(password: Optional[str]) -> Dict[str, float]:
    snapshot: Dict[str, float] = {}
    for ts, path in list_session_files(password):
        snapshot[path] = ts
    return snapshot


def session_id_from_path(path: str) -> Optional[str]:
    match = SESSION_FILE_RE.search(path)
    if not match:
        return None
    return match.group("sid")
