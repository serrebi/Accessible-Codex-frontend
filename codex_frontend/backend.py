"""Backend selection layer for local WSL or remote SSH execution."""
from __future__ import annotations

import subprocess
import os
from typing import Callable, Optional

from .run_result import RunResult
from . import wsl, settings

ssh_backend = None


def _ensure_ssh_backend():
    global ssh_backend
    if ssh_backend is not None:
        return
    try:
        from . import ssh_backend as _mod
        ssh_backend = _mod
    except ImportError:
        raise RuntimeError("Remote SSH mode requires the 'paramiko' package to be installed.")


class BaseBackend:
    def bash_single_quote(self, text: str) -> str:
        raise NotImplementedError

    def shell_quote(self, text: str) -> str:
        return self.bash_single_quote(text)

    def run_shell(
        self,
        script: str,
        input_text: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> RunResult:
        raise NotImplementedError

    def run_as_root(
        self,
        cmd: str,
        password: Optional[str],
        timeout: Optional[int] = None,
    ) -> RunResult:
        raise NotImplementedError

    def stream_as_root(
        self,
        cmd: str,
        password: Optional[str],
        timeout: Optional[int],
        stdout_cb: Optional[Callable[[str], None]],
        stderr_cb: Optional[Callable[[str], None]],
    ) -> RunResult:
        raise NotImplementedError

    def description(self) -> str:
        raise NotImplementedError

    def detect_os(self) -> str:
        raise NotImplementedError

    def detect_arch(self) -> str:
        raise NotImplementedError


class WSLBackend(BaseBackend):
    def bash_single_quote(self, text: str) -> str:
        return wsl.bash_single_quote(text)

    def run_shell(self, script: str, input_text: Optional[str] = None, timeout: Optional[int] = None) -> RunResult:
        return wsl.run_wsl_bash(script, input_text=input_text, timeout=timeout)

    def run_as_root(self, cmd: str, password: Optional[str], timeout: Optional[int] = None) -> RunResult:
        return wsl.run_as_root(cmd, password, timeout=timeout)

    def stream_as_root(
        self,
        cmd: str,
        password: Optional[str],
        timeout: Optional[int],
        stdout_cb: Optional[Callable[[str], None]],
        stderr_cb: Optional[Callable[[str], None]],
    ) -> RunResult:
        return wsl.stream_as_root(cmd, password, timeout, stdout_cb, stderr_cb)

    def description(self) -> str:
        return "Local WSL"

    def detect_os(self) -> str:
        # Simple WSL detection
        res = self.run_shell("grep -E '^(PRETTY_NAME|NAME)=' /etc/os-release || uname -s", timeout=5)
        if not res.ok:
            return "WSL (Unknown Linux)"
        text = res.stdout.strip()
        if "PRETTY_NAME=" in text:
            for line in text.splitlines():
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip('"')
        if "NAME=" in text:
             for line in text.splitlines():
                if line.startswith("NAME="):
                    return line.split("=", 1)[1].strip('"')
        return text or "WSL (Linux)"

    def detect_arch(self) -> str:
        res = self.run_shell("uname -m", timeout=5)
        return res.stdout.strip() if res.ok else "unknown"


class WindowsBackend(BaseBackend):
    def bash_single_quote(self, text: str) -> str:  # pragma: no cover - naming for compatibility
        return self.shell_quote(text)

    def shell_quote(self, text: str) -> str:
        # PowerShell single-quote escaping
        return "'" + text.replace("'", "''") + "'"

    def run_shell(
        self,
        script: str,
        input_text: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> RunResult:
        args = ["powershell", "-NoProfile", "-Command", script]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            cp = subprocess.run(
                args,
                input=input_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=creationflags,
                startupinfo=startupinfo,
            )
            return RunResult(cp.returncode == 0, cp.returncode, cp.stdout, cp.stderr)
        except FileNotFoundError as exc:
            return RunResult(False, 127, "", f"powershell not found: {exc}")
        except subprocess.TimeoutExpired as exc:
            return RunResult(False, 124, exc.stdout or "", f"Timeout: {exc}")
        except Exception as exc:  # pragma: no cover - defensive
            return RunResult(False, 1, "", f"Exception: {exc}")

    def run_as_root(
        self,
        cmd: str,
        password: Optional[str],
        timeout: Optional[int] = None,
    ) -> RunResult:
        # No sudo concept on Windows; just run the command
        return self.run_shell(cmd, timeout=timeout)

    def stream_as_root(
        self,
        cmd: str,
        password: Optional[str],
        timeout: Optional[int],
        stdout_cb: Optional[Callable[[str], None]],
        stderr_cb: Optional[Callable[[str], None]],
    ) -> RunResult:
        args = ["powershell", "-NoProfile", "-Command", cmd]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE if password else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
                startupinfo=startupinfo,
            )
        except FileNotFoundError as exc:
            return RunResult(False, 127, "", f"powershell not found: {exc}")
        stdout_text = []
        stderr_text = []
        try:
            if proc.stdout:
                for line in proc.stdout:
                    stdout_text.append(line)
                    if stdout_cb:
                        stdout_cb(line)
            if proc.stderr:
                for line in proc.stderr:
                    stderr_text.append(line)
                    if stderr_cb:
                        stderr_cb(line)
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            return RunResult(False, 124, "".join(stdout_text), "Timeout")
        code = proc.returncode if proc.returncode is not None else 1
        return RunResult(code == 0, code, "".join(stdout_text), "".join(stderr_text))

    def description(self) -> str:
        return "Local Windows"

    def detect_os(self) -> str:
        return f"Windows {os.name}"

    def detect_arch(self) -> str:
        return os.environ.get("PROCESSOR_ARCHITECTURE", "unknown")


class SSHBackend(BaseBackend):
    def __init__(self, host: str, port: int, username: str, password: str):
        _ensure_ssh_backend()
        self._impl = ssh_backend.SSHBackend(host=host, port=port, username=username, password=password)

    def bash_single_quote(self, text: str) -> str:
        return ssh_backend.bash_single_quote(text)

    def run_shell(self, script: str, input_text: Optional[str] = None, timeout: Optional[int] = None) -> RunResult:
        return self._impl.run_shell(script, input_text=input_text, timeout=timeout)

    def run_as_root(self, cmd: str, password: Optional[str], timeout: Optional[int] = None) -> RunResult:
        return self._impl.run_as_root(cmd, password=password, timeout=timeout)

    def stream_as_root(
        self,
        cmd: str,
        password: Optional[str],
        timeout: Optional[int],
        stdout_cb: Optional[Callable[[str], None]],
        stderr_cb: Optional[Callable[[str], None]],
    ) -> RunResult:
        return self._impl.stream_as_root(cmd, password=password, timeout=timeout, stdout_cb=stdout_cb, stderr_cb=stderr_cb)

    def description(self) -> str:
        return self._impl.description()

    def detect_os(self) -> str:
        return self._impl.detect_os()

    def detect_arch(self) -> str:
        return self._impl.detect_arch()


_current_backend: BaseBackend = WindowsBackend()
_mode: str = "windows"
_remote_settings: Optional[dict] = None


def use_local_backend() -> None:
    use_windows_backend()


def use_windows_backend() -> None:
    global _current_backend, _mode, _remote_settings
    _current_backend = WindowsBackend()
    _mode = "windows"
    _remote_settings = None


def use_wsl_backend() -> None:
    global _current_backend, _mode, _remote_settings
    if not wsl.available():
        raise RuntimeError("WSL is not available on this system.")
    _current_backend = WSLBackend()
    _mode = "wsl"
    _remote_settings = None


def use_remote_backend(host: str, port: int, username: str, password: str) -> None:
    global _current_backend, _mode, _remote_settings
    _current_backend = SSHBackend(host=host, port=port, username=username, password=password)
    _mode = "remote"
    _remote_settings = {
        "host": host,
        "port": port,
        "username": username,
    }


def is_remote() -> bool:
    return _mode == "remote"


def is_wsl() -> bool:
    return _mode == "wsl"


def is_windows() -> bool:
    return _mode == "windows"


def remote_settings() -> Optional[dict]:
    return _remote_settings.copy() if _remote_settings else None


def backend_description() -> str:
    return _current_backend.description()


def bash_single_quote(text: str) -> str:
    return _current_backend.bash_single_quote(text)


def shell_quote(text: str) -> str:
    return _current_backend.shell_quote(text)


def run_shell(script: str, input_text: Optional[str] = None, timeout: Optional[int] = None) -> RunResult:
    return _current_backend.run_shell(script, input_text=input_text, timeout=timeout)


def run_as_root(cmd: str, password: Optional[str], timeout: Optional[int] = None) -> RunResult:
    return _current_backend.run_as_root(cmd, password, timeout=timeout)


def stream_as_root(
    cmd: str,
    password: Optional[str],
    timeout: Optional[int],
    stdout_cb: Optional[Callable[[str], None]],
    stderr_cb: Optional[Callable[[str], None]],
) -> RunResult:
    return _current_backend.stream_as_root(cmd, password, timeout, stdout_cb, stderr_cb)


def detect_os() -> str:
    return _current_backend.detect_os()


def detect_arch() -> str:
    return _current_backend.detect_arch()

