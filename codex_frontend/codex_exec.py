"""Codex CLI orchestration helpers."""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple, Callable
from pathlib import Path
import json

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
        f"{backend.shell_quote(prompt)}"
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
        f"{backend.shell_quote(prompt)}"
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
            f"{backend.shell_quote(resume_target)} {backend.shell_quote(prompt)}"
        )
    else:
        cmd = (
            "codex --search --dangerously-bypass-approvals-and-sandbox "
            "exec --skip-git-repo-check resume --last "
            f"{backend.shell_quote(prompt)}"
        )
    return backend.stream_as_root(cmd, password, timeout, stdout_cb, stderr_cb)


def check_shell_ready() -> Tuple[bool, str]:
    result = backend.run_shell("echo SHELL_OK")
    ok = result.ok and "SHELL_OK" in (result.stdout or "")
    return (ok, (result.stdout or "").strip() or (result.stderr or "").strip())


def check_codex_installed() -> Tuple[bool, str]:
    if backend.is_windows():
        path = _find_windows_codex_path()
    else:
        result = backend.run_shell("command -v codex || true")
        path = result.stdout.strip()
    
    if not path:
        return False, "codex not found in PATH"
        
    # Verify it runs (catch Exec format error, etc)
    if backend.is_windows():
        cmd = f"& {backend.shell_quote(path)} --version"
    else:
        cmd = "codex --version"
        
    res = backend.run_shell(cmd)
    if not res.ok:
        return False, f"codex found at {path} but failed to run: {res.stderr or res.stdout}"

    return True, path


def log_codex_help() -> str:
    result = backend.run_shell("codex --help")
    return (result.stdout or result.stderr or "").strip()



# Updates / install -------------------------------------------------


def _find_windows_codex_path() -> str:
    r"""Return an existing codex.exe path if present (PATH, %USERPROFILE%\.codex, or %USERPROFILE%\bin)."""
    if not backend.is_windows():
        return ""
    script = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$candidates = @()
try {
    $where = where.exe codex 2>$null
    if ($where) { $candidates += ($where -split "`n") }
} catch {}
$candidates += "$env:USERPROFILE\.codex\codex.exe"
$candidates += "$env:USERPROFILE\bin\codex.exe"
foreach ($c in $candidates) {
    $p = $c.Trim()
    if (-not $p) { continue }
    if (Test-Path $p) { Write-Output $p; break }
}
"""
    res = backend.run_shell(script)
    return res.stdout.strip().splitlines()[0].strip() if res.ok and res.stdout else ""


def _windows_latest_release() -> Tuple[bool, str, str]:
    """Return (ok, version_tag, url) for latest Windows codex asset (prefers newest, including prerelease)."""
    if not backend.is_windows():
        return False, "", "not windows"
    script = r"""
$rel = Invoke-RestMethod -UseBasicParsing https://api.github.com/repos/openai/codex/releases?per_page=1
$rel = $rel | Select-Object -First 1
$asset = $rel.assets | Where-Object { $_.name -eq 'codex-x86_64-pc-windows-msvc.exe' } | Select-Object -First 1
if (-not $asset) { Write-Output "ERROR|asset"; exit 0 }
Write-Output ("OK|" + $rel.tag_name + "|" + $asset.browser_download_url)
"""
    res = backend.run_shell(script)
    if not res.ok or not res.stdout:
        return False, "", "failed to query releases"
    line = res.stdout.strip()
    if not line.startswith("OK|"):
        return False, "", line
    _, tag, url = line.split("|", 2)
    return True, tag, url


def _current_codex_version() -> Optional[str]:
    if backend.is_windows():
        path = _find_windows_codex_path()
        cmd = f"& {backend.shell_quote(path)} --version" if path else "codex --version"
    else:
        cmd = "codex --version"
    res = backend.run_shell(cmd)
    if not res.ok or not res.stdout:
        return None
    parts = res.stdout.strip().split()
    return parts[-1] if parts else None


def ensure_remote_codex_latest(password: Optional[str] = None) -> Tuple[bool, str]:
    """
    Fast remote check: install only if codex is missing or npm reports a newer version.
    Skips network-heavy steps when not needed; uses sudo when a password is provided.
    """
    if backend.is_windows():
         return True, "skip (Windows backend)"

    # 1) Cheap existence + version check
    fast_check = r"""
if command -v codex >/dev/null 2>&1; then
    ver=$(codex --version 2>/dev/null)
    if [ $? -eq 0 ] && [ -n "$ver" ]; then
        echo "HAS|"${ver}
        exit 0
    fi
    echo "BROKEN"
    exit 0
fi
echo "MISSING"
"""
    res = backend.run_as_root(fast_check, password, timeout=6)
    state_line = (res.stdout or "").strip().splitlines()[:1]
    state = state_line[0] if state_line else ""

    has_codex = state.startswith("HAS|")
    current_ver = state.split("|", 1)[1].strip() if has_codex else ""

    # 2) Quick latest lookup (if npm exists); timeout to avoid hanging
    needs_install = False
    needs_update = False
    latest_ver = ""
    npm_check = r"""
if command -v npm >/dev/null 2>&1; then
    if command -v timeout >/dev/null 2>&1; then
        timeout 3s npm view @openai/codex version 2>/dev/null
    else
        npm view @openai/codex version 2>/dev/null
    fi
fi
"""
    if has_codex:
        latest_res = backend.run_as_root(npm_check, password, timeout=6)
        latest_ver = (latest_res.stdout or "").strip().splitlines()[:1]
        latest_ver = latest_ver[0] if latest_ver else ""
        if latest_ver and latest_ver not in current_ver:
            needs_update = True
    else:
        needs_install = True

    if has_codex and not needs_update:
        return True, f"Codex present ({current_ver})"

    # 3) Ensure npm only if we actually need install/update
    if needs_install or needs_update:
        npm_exists = backend.run_as_root("command -v npm >/dev/null 2>&1", password, timeout=5).ok
        if not npm_exists:
            os_name = backend.detect_os().lower()
            if "debian" in os_name or "ubuntu" in os_name or "kali" in os_name or "mint" in os_name or "pop" in os_name:
                pkg_cmd = "apt-get update -qq && apt-get install -y -qq nodejs npm"
            elif "fedora" in os_name or "red hat" in os_name or "rhel" in os_name or "centos" in os_name or "amzn" in os_name or "alma" in os_name or "rocky" in os_name or "oracle" in os_name:
                pkg_cmd = "if command -v dnf >/dev/null; then dnf install -y -q nodejs npm; else yum install -y -q nodejs npm; fi"
            elif "arch" in os_name or "manjaro" in os_name or "endeavour" in os_name:
                 pkg_cmd = "pacman -Sy --noconfirm nodejs npm"
            elif "darwin" in os_name:
                pkg_cmd = "brew install node"
            else:
                pkg_cmd = (
                    "if command -v apt-get >/dev/null; then apt-get update -qq && apt-get install -y -qq nodejs npm; "
                    "elif command -v dnf >/dev/null; then dnf install -y -q nodejs npm; "
                    "elif command -v yum >/dev/null; then yum install -y -q nodejs npm; "
                    "elif command -v pacman >/dev/null; then pacman -Sy --noconfirm nodejs npm; "
                    "elif command -v brew >/dev/null; then brew install node; "
                    "else echo 'ERROR|Package manager not found'; exit 1; fi"
                )
            got_npm = backend.run_as_root(pkg_cmd, password, timeout=180)
            if not got_npm.ok:
                return False, (got_npm.stderr or got_npm.stdout or "npm install failed").strip()

        # 4) Perform minimal install/update
        mode = "install" if needs_install else "update"
        npm_cmd = "npm install -g @openai/codex"
        if needs_update:
            npm_cmd += " --force"
        result = backend.run_as_root(npm_cmd, password, timeout=240)
        if not result.ok:
            return False, (result.stderr or result.stdout or f"{mode} failed").strip()

        # 5) Verify
        verify = backend.run_as_root("codex --version", password, timeout=10)
        if verify.ok and verify.stdout:
            return True, f"Codex {mode}ed: {verify.stdout.strip()}"
        return False, (verify.stderr or verify.stdout or "codex verify failed").strip()

    return True, "No action taken"


def ensure_windows_codex_latest() -> Tuple[bool, str]:
    """Download latest Windows codex if newer (includes prereleases)."""
    if not backend.is_windows():
        return True, "skip (non-Windows backend)"
    ok, tag, url = _windows_latest_release()
    if not ok or not url:
        return False, f"Failed to query latest release: {url or '(unknown)'}"
    current = _current_codex_version()
    if current and tag.lstrip("v") == current.lstrip("v"):
        return True, f"Codex already latest ({current})"
    
    existing = _find_windows_codex_path()
    if existing:
        dest = existing
        install_dir = str(Path(dest).parent)
    else:
        # Default to %USERPROFILE%\bin
        install_dir = os.path.expandvars(r"%USERPROFILE%\bin")
        dest = str(Path(install_dir) / "codex.exe")

    script = (
        f"$dest = {backend.shell_quote(dest)}; "
        f"$url = {backend.shell_quote(url)}; "
        "$null = New-Item -ItemType Directory -Force -Path (Split-Path $dest); "
        "Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing; "
        "$destDir = Split-Path $dest; "
        "$current = [Environment]::GetEnvironmentVariable('PATH','User'); "
        "if (-not $current) { $current = '' } "
        "if ($current -notlike ('*' + $destDir + '*')) { "
        "    [Environment]::SetEnvironmentVariable('PATH', ($destDir + ';' + $current), 'User') "
        "} "
        "$v = (& $dest --version) 2>$null; "
        "Write-Output \"UPDATED|$v\""
    )
    res = backend.run_shell(script)
    if res.ok:
        # Ensure current process sees the new binary
        if install_dir.lower() not in [p.lower() for p in os.environ["PATH"].split(os.pathsep)]:
            os.environ["PATH"] += os.pathsep + install_dir
        return True, (res.stdout or "").strip() or f"Updated to {tag}"
    return False, (res.stderr or res.stdout or "Download failed").strip()


def ensure_codex_authenticated(prompt_fn: Callable[[], Optional[Dict[str, str]]]) -> Tuple[bool, str]:
    """Ensure codex is authenticated; prompt user if not."""
    home_dot_codex = Path.home() / ".codex"
    status = backend.run_shell("codex auth status")
    if status.ok and "Authenticated" in (status.stdout or ""):
        return True, (status.stdout or "").strip()
    # If user already has .codex, assume they have a config and skip re-login
    if home_dot_codex.exists():
        return True, f"Using existing config at {home_dot_codex}; skipping login prompt."

    selection = prompt_fn()
    if selection is None:
        return False, "Authentication cancelled"

    method = selection.get("method")
    api_key = selection.get("api_key", "")

    if method == "chatgpt":
        res = backend.run_shell("codex auth login")
        if res.ok:
            return True, "Authenticated via ChatGPT browser flow."
        return False, (res.stderr or res.stdout or "codex auth login failed").strip()

    if method == "api_key":
        if not api_key:
            return False, "No API key provided."
        res = backend.run_shell(f"codex auth set-api-key {backend.shell_quote(api_key)}")
        if res.ok:
            return True, "API key saved."
        return False, (res.stderr or res.stdout or "codex auth set-api-key failed").strip()

    return False, "Unknown auth method."


def list_session_files(password: Optional[str]) -> List[Tuple[float, str]]:
    if backend.is_windows():
        base = settings.DEFAULT_WINDOWS_CONVERSATION_DIR
        entries: List[Tuple[float, str]] = []
        import os

        for root, _dirs, files in os.walk(base):
            for name in files:
                if not name.lower().endswith((".json", ".jsonl")):
                    continue
                path = os.path.join(root, name)
                try:
                    ts = os.path.getmtime(path)
                except OSError:
                    continue
                entries.append((ts, path))
        entries.sort(key=lambda item: item[0], reverse=True)
        return entries[:200]
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
