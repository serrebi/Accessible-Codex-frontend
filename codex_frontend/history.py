"""Conversation history utilities."""
from __future__ import annotations

import time
from typing import List, Optional, Tuple

import os
from pathlib import Path

from . import settings, backend


def _is_conversation_history(path: str) -> bool:
    if not path:
        return False
    rel = path
    if rel.startswith("/root/.codex/"):
        rel = rel[len("/root/.codex/") :]
    default_base = settings.DEFAULT_WSL_CONVERSATION_DIR.rstrip("/")
    if default_base and rel.startswith(default_base + "/"):
        rel = rel[len(default_base) + 1 :]
    win_base = settings.DEFAULT_WINDOWS_CONVERSATION_DIR
    if win_base and rel.lower().startswith(win_base.lower() + "\\"):
        rel = rel[len(win_base) + 1 :]
    rel_lower = rel.lower().replace("\\", "/")
    parts = rel_lower.split('/')
    if not any(name in parts for name in settings.HISTORY_INCLUDE_DIR_NAMES):
        return False
    if not rel_lower.endswith(settings.HISTORY_INCLUDE_SUFFIXES):
        return False
    return True


def _bash_assign_path(var: str, path: str) -> str:
    q_path = backend.bash_single_quote(path)
    # A simplified and more robust way to handle path assignment and tilde expansion.
    # We construct the shell variable slicing carefully to avoid f-string interpretation.
    command = f"{var}={q_path}; "
    command += f"if [[ \"${var}\" == '~/'* ]]; then "
    command += 'home_dir=""; '
    command += 'if [ -n "$SUDO_USER" ]; then home_dir=$(getent passwd "$SUDO_USER" | cut -d: -f6); fi; '
    command += 'if [ -z "$home_dir" ]; then home_dir="$HOME"; fi; '
    command += var + '="$home_dir/${' + var + ':2}"; '
    command += "fi"
    return command


def list_codex_history(password: Optional[str], base_dir: str) -> Tuple[List[str], Optional[str]]:
    if not base_dir:
        return [], "conversation directory not set"

    if backend.is_windows():
        entries: List[Tuple[float, str]] = []
        for root, _dirs, files in os.walk(base_dir):
            depth = Path(root).relative_to(Path(base_dir)).parts
            if len(depth) > 4:
                continue
            for name in files:
                if not name.lower().endswith(settings.HISTORY_INCLUDE_SUFFIXES):
                    continue
                path = os.path.join(root, name)
                try:
                    ts = os.path.getmtime(path)
                except OSError:
                    continue
                entries.append((ts, path))
        if not entries:
            return [], None
        entries.sort(key=lambda item: item[0], reverse=True)
        filtered = [p for _, p in entries if _is_conversation_history(p)]
        return (filtered or [p for _, p in entries], None)

    script = (
        _bash_assign_path("dir", base_dir)
        + "; if [ -d \"$dir\" ]; then find \"$dir\" -maxdepth 4 -type f -printf '%T@\\t%p\\n' 2>/dev/null; fi"
    )
    # Just pass the script; run_as_root handles wrapping/shell execution
    result = backend.run_as_root(script, password, timeout=60)
    if not result.ok:
        err = (result.stderr or result.stdout or "").strip() or f"find failed (rc={result.code})"
        return [], err

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

    if not entries:
        return [], None

    entries.sort(key=lambda item: item[0], reverse=True)
    filtered = [path for _, path in entries if _is_conversation_history(path)]
    if filtered:
        return filtered, None
    return [path for _, path in entries], None


def read_history_file(path: str, password: Optional[str]) -> str:
    if backend.is_windows():
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"not found ({exc})"
    
    # For reading, we just cat the file. The path comes from list_codex_history 
    # which returns absolute paths (from find), so expansion shouldn't be needed here usually.
    # However, to be safe against ~ passed directly:
    script = (
        _bash_assign_path("path", path)
        + "; test -f \"$path\" && cat \"$path\" || echo 'not found'"
    )
    result = backend.run_as_root(script, password, timeout=60)
    return (result.stdout or result.stderr or "").strip()


def ensure_conversation_dir(password: Optional[str], base_dir: str) -> Tuple[bool, str]:
    if not base_dir:
        return False, "conversation directory not set"
    if backend.is_windows():
        try:
            Path(base_dir).mkdir(parents=True, exist_ok=True)
            return True, str(base_dir)
        except OSError as exc:
            return False, str(exc)
    
    script = (
        _bash_assign_path("dir", base_dir)
        + "; if [ -z \"$dir\" ]; then echo 'DEBUG: dir is empty' >&2; exit 1; fi; "
        + "echo \"DEBUG: creating dir='$dir'\" >&2; "
        + "mkdir -p \"$dir\" && printf '%s\\n' \"$dir\""
    )
    result = backend.run_as_root(script, password, timeout=30)
    if result.ok:
        return True, (result.stdout or "").strip()
    return False, (result.stderr or result.stdout or f"rc={result.code}").strip()


def create_new_conversation(password: Optional[str], base_dir: str) -> Tuple[bool, str]:
    ok, msg = ensure_conversation_dir(password, base_dir)
    if not ok:
        return False, msg
    if backend.is_windows():
        stamp = time.strftime("%Y%m%dT%H%M%S")
        base_path = Path(base_dir)
        path = base_path / f"conversation_{stamp}.md"
        counter = 0
        while path.exists():
            counter += 1
            path = base_path / f"conversation_{stamp}_{counter}.md"
        try:
            path.write_text(f"# Conversation started {time.strftime('%Y-%m-%dT%H:%M:%S')}\n\n", encoding="utf-8")
            return True, str(path)
        except OSError as exc:
            return False, str(exc)
    
    script = (
        _bash_assign_path("dir", base_dir)
        + "; stamp=$(date +%Y%m%dT%H%M%S); "
        "file=\"$dir/conversation_${stamp}.md\"; "
        "while [ -e \"$file\" ]; do stamp=$(date +%Y%m%dT%H%M%S_%N); file=\"$dir/conversation_${stamp}.md\"; done; "
        "printf '# Conversation started %s\\n\\n' \"$(date -Iseconds)\" > \"$file\" || exit 1; "
        "printf '%s\\n' \"$file\""
    )
    result = backend.run_as_root(script, password, timeout=30)
    if not result.ok:
        return False, (result.stderr or result.stdout or f"rc={result.code}").strip()
    out = (result.stdout or "").strip()
    path = out.splitlines()[-1] if out else ""
    if not path:
        return False, "conversation path missing"
    return True, path


def append_conversation_entry(
    path: str,
    prompt: str,
    stdout: str,
    stderr: str,
    password: Optional[str],
) -> Tuple[bool, str]:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    parts = [
        f"## Prompt ({timestamp})",
        prompt or "(empty)",
        "",
    ]
    clean_stdout = stdout.rstrip("\n")
    clean_stderr = stderr.rstrip("\n")
    if clean_stdout:
        parts.extend(["### Output", clean_stdout, ""])
    if clean_stderr:
        parts.extend(["### Stderr", clean_stderr, ""])

    payload = "\n".join(parts) + "\n"
    if backend.is_windows():
        try:
            with Path(path).open("a", encoding="utf-8") as fh:
                fh.write(payload)
            return True, "appended conversation entry"
        except OSError as exc:
            return False, str(exc)
            
    # payload needs separate quoting as it's content
    payload_quoted = backend.bash_single_quote(payload)
    
    # path expansion handled by _bash_assign_path
    script = (
        _bash_assign_path("path", path)
        + "; if [ ! -e \"$path\" ]; then exit 1; fi; "
        f"printf \"%s\" {payload_quoted} >> \"$path\" || exit 1"
    )
    result = backend.run_as_root(script, password, timeout=30)
    if result.ok:
        return True, "appended conversation entry"
    return False, (result.stderr or result.stdout or f"rc={result.code}").strip()


def rename_conversation_file(
    password: Optional[str],
    old_path: str,
    new_filename: str
) -> Tuple[bool, str, str]:
    """Rename a conversation file. Returns (success, new_full_path, error_msg)."""
    if not old_path:
        return False, "", "invalid old path"
    
    # Sanitize new filename
    safe_name = "".join(c for c in new_filename if c.isalnum() or c in (' ', '.', '_', '-')).strip()
    safe_name = safe_name.replace(" ", "_")
    if not safe_name:
        return False, "", "invalid new filename"
    if not safe_name.lower().endswith(".md"):
        safe_name += ".md"

    if backend.is_windows():
        try:
            old_p = Path(old_path)
            if not old_p.exists():
                return False, "", "file not found"
            new_p = old_p.parent / safe_name
            # Avoid overwriting
            if new_p.exists() and new_p != old_p:
                safe_name = f"{safe_name.rsplit('.', 1)[0]}_{int(time.time())}.md"
                new_p = old_p.parent / safe_name
            
            old_p.rename(new_p)
            return True, str(new_p), ""
        except OSError as exc:
            return False, "", str(exc)

    # Remote/WSL logic
    # We need to handle path expansion for old_path, and directory extraction
    
    script = (
        _bash_assign_path("src", old_path)
        + f"; dest_name={backend.bash_single_quote(safe_name)}; "
        "if [ ! -e \"$src\" ]; then echo 'not found'; exit 1; fi; "
        "dir=$(dirname \"$src\"); "
        "dest=\"$dir/$dest_name\"; "
        "if [ -e \"$dest\" ] && [ \"$src\" != \"$dest\" ]; then "
        "  dest=\"${dest%.*}_$(date +%s).md\"; "
        "fi; "
        "mv \"$src\" \"$dest\" && echo \"$dest\""
    )
    result = backend.run_as_root(script, password, timeout=30)
    if result.ok:
        final_path = result.stdout.strip().splitlines()[-1]
        return True, final_path, ""
    return False, "", (result.stderr or result.stdout).strip()
