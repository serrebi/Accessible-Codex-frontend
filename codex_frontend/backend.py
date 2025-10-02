"""Backend selection layer for local WSL or remote SSH execution."""
from __future__ import annotations

from typing import Callable, Optional

from .run_result import RunResult
from . import wsl

try:  # Paramiko is optional; only needed for SSH mode
    from . import ssh_backend
except ImportError:  # pragma: no cover - optional dependency missing
    ssh_backend = None  # type: ignore


class BaseBackend:
    def bash_single_quote(self, text: str) -> str:
        raise NotImplementedError

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


class SSHBackend(BaseBackend):
    def __init__(self, host: str, port: int, username: str, password: str):
        if ssh_backend is None:
            raise RuntimeError("Remote SSH mode requires the 'paramiko' package to be installed.")
        self._impl = ssh_backend.SSHBackend(host=host, port=port, username=username, password=password)

    def bash_single_quote(self, text: str) -> str:
        return ssh_backend.bash_single_quote(text)

    def run_shell(self, script: str, input_text: Optional[str] = None, timeout: Optional[int] = None) -> RunResult:
        return self._impl.run_shell(script, input_text=input_text, timeout=timeout)

    def run_as_root(self, cmd: str, password: Optional[str], timeout: Optional[int] = None) -> RunResult:
        return self._impl.run_as_root(cmd, timeout=timeout)

    def stream_as_root(
        self,
        cmd: str,
        password: Optional[str],
        timeout: Optional[int],
        stdout_cb: Optional[Callable[[str], None]],
        stderr_cb: Optional[Callable[[str], None]],
    ) -> RunResult:
        return self._impl.stream_as_root(cmd, timeout, stdout_cb, stderr_cb)

    def description(self) -> str:
        return self._impl.description()


_current_backend: BaseBackend = WSLBackend()
_mode: str = "local"
_remote_settings: Optional[dict] = None


def use_local_backend() -> None:
    global _current_backend, _mode, _remote_settings
    _current_backend = WSLBackend()
    _mode = "local"
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


def remote_settings() -> Optional[dict]:
    return _remote_settings.copy() if _remote_settings else None


def backend_description() -> str:
    return _current_backend.description()


def bash_single_quote(text: str) -> str:
    return _current_backend.bash_single_quote(text)


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
