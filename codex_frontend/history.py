"""Conversation history utilities."""
from __future__ import annotations

import time
from typing import List, Optional, Tuple

from . import settings, backend


def _is_conversation_history(path: str) -> bool:
    if not path:
        return False
    rel = path
    if rel.startswith("/root/.codex/"):
        rel = rel[len("/root/.codex/") :]
    rel_lower = rel.lower()
    parts = rel_lower.split('/')
    if not any(name in parts for name in settings.HISTORY_INCLUDE_DIR_NAMES):
        return False
    if not rel_lower.endswith(settings.HISTORY_INCLUDE_SUFFIXES):
        return False
    return True


def list_codex_history(password: Optional[str], base_dir: str) -> Tuple[List[str], Optional[str]]:
    if not base_dir:
        return [], "conversation directory not set"
    script = (
        "dir="
        + backend.bash_single_quote(base_dir)
        + "; if [ -d \"$dir\" ]; then find \"$dir\" -maxdepth 4 -type f -printf '%T@\\t%p\\n' 2>/dev/null; fi"
    )
    cmd = f"bash -lc {backend.bash_single_quote(script)}"
    result = backend.run_as_root(cmd, password, timeout=60)
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
    safe = path.replace("'", "")
    result = backend.run_as_root(
        f"test -f {backend.bash_single_quote(safe)} && cat {backend.bash_single_quote(safe)} || echo 'not found'",
        password,
        timeout=60,
    )
    return (result.stdout or result.stderr or "").strip()


def ensure_conversation_dir(password: Optional[str], base_dir: str) -> Tuple[bool, str]:
    if not base_dir:
        return False, "conversation directory not set"
    cmd = f"mkdir -p {backend.bash_single_quote(base_dir)} && printf '%s\n' {backend.bash_single_quote(base_dir)}"
    result = backend.run_as_root(cmd, password, timeout=30)
    if result.ok:
        return True, (result.stdout or "").strip()
    return False, (result.stderr or result.stdout or f"rc={result.code}").strip()


def create_new_conversation(password: Optional[str], base_dir: str) -> Tuple[bool, str]:
    ok, msg = ensure_conversation_dir(password, base_dir)
    if not ok:
        return False, msg
    cmd = (
        f"dir={backend.bash_single_quote(base_dir)}; "
        "stamp=$(date +%Y%m%dT%H%M%S); "
        "file=\"$dir/conversation_${stamp}.md\"; "
        "while [ -e \"$file\" ]; do stamp=$(date +%Y%m%dT%H%M%S_%N); file=\"$dir/conversation_${stamp}.md\"; done; "
        "printf '# Conversation started %s\\n\\n' \"$(date -Iseconds)\" > \"$file\" || exit 1; "
        "printf '%s\\n' \"$file\""
    )
    result = backend.run_as_root(cmd, password, timeout=30)
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
    script = (
        "path=" + backend.bash_single_quote(path) + "; "
        "if [ ! -e \"$path\" ]; then exit 1; fi; "
        "payload=$(cat <<'EOF'\n"
        f"{payload}"
        "EOF\n); "
        "printf \"%s\" \"$payload\" >> \"$path\" || exit 1"
    )
    result = backend.run_as_root(f"bash -lc {backend.bash_single_quote(script)}", password, timeout=30)
    if result.ok:
        return True, "appended conversation entry"
    return False, (result.stderr or result.stdout or f"rc={result.code}").strip()
