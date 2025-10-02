"""SSH backend implementation for remote Codex execution."""
from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional, Tuple

import paramiko

from .run_result import RunResult

ENV_PREFIX = "env NO_COLOR=1 CLICOLOR=0 CI=1 TERM=dumb"


def bash_single_quote(text: str) -> str:
    return "'" + text.replace("'", "'\"'\"'") + "'"


class SSHBackend:
    def __init__(self, host: str, port: int, username: str, password: str):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._client: Optional[paramiko.SSHClient] = None
        self._lock = threading.Lock()

    def description(self) -> str:
        return f"Remote SSH {self.username}@{self.host}:{self.port}"

    def _ensure_client(self) -> paramiko.SSHClient:
        with self._lock:
            if self._client and self._client.get_transport() and self._client.get_transport().is_active():
                return self._client
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                look_for_keys=False,
                allow_agent=False,
                timeout=15,
            )
            self._client = client
            return client

    def _wait_for_exit(self, channel: paramiko.Channel, timeout: Optional[int]) -> Tuple[bool, int]:
        if timeout is None:
            exit_status = channel.recv_exit_status()
            return False, exit_status
        deadline = time.time() + timeout
        while True:
            if channel.exit_status_ready():
                exit_status = channel.recv_exit_status()
                return False, exit_status
            if time.time() >= deadline:
                channel.close()
                return True, 124
            time.sleep(0.1)

    def run_shell(self, script: str, input_text: Optional[str], timeout: Optional[int]) -> RunResult:
        cmd = f"bash -lc {bash_single_quote(script)}"
        return self._exec_command(cmd, input_text, timeout)

    def run_as_root(self, cmd: str, timeout: Optional[int]) -> RunResult:
        wrapped = f"bash -lc {bash_single_quote(f'{ENV_PREFIX} {cmd}')}"
        return self._exec_command(wrapped, None, timeout)

    def stream_as_root(
        self,
        cmd: str,
        timeout: Optional[int],
        stdout_cb: Optional[Callable[[str], None]],
        stderr_cb: Optional[Callable[[str], None]],
    ) -> RunResult:
        wrapped = f"bash -lc {bash_single_quote(f'{ENV_PREFIX} {cmd}')}"
        return self._stream_command(wrapped, timeout, stdout_cb, stderr_cb)

    def _exec_command(
        self,
        command: str,
        input_text: Optional[str],
        timeout: Optional[int],
    ) -> RunResult:
        client = self._ensure_client()
        stdin, stdout, stderr = client.exec_command(command)
        channel = stdout.channel
        if input_text:
            stdin.write(input_text)
            if not input_text.endswith("\n"):
                stdin.write("\n")
            stdin.flush()
        stdin.close()

        timed_out, exit_status = self._wait_for_exit(channel, timeout)
        stdout_text = stdout.read().decode("utf-8", errors="replace")
        stderr_text = stderr.read().decode("utf-8", errors="replace")
        if timed_out:
            exit_status = 124
        ok = exit_status == 0
        if timed_out and not stderr_text:
            stderr_text = f"Timeout after {timeout or 0} seconds"
        return RunResult(ok, exit_status, stdout_text, stderr_text)

    def _stream_command(
        self,
        command: str,
        timeout: Optional[int],
        stdout_cb: Optional[Callable[[str], None]],
        stderr_cb: Optional[Callable[[str], None]],
    ) -> RunResult:
        client = self._ensure_client()
        stdin, stdout, stderr = client.exec_command(command)
        channel = stdout.channel
        stdin.close()

        stdout_chunks: List[str] = []
        stderr_chunks: List[str] = []

        def _consume(stream, chunks: List[str], callback: Optional[Callable[[str], None]]):
            while True:
                line = stream.readline()
                if not line:
                    break
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="replace")
                chunks.append(line)
                if callback:
                    callback(line)

        threads: List[threading.Thread] = []
        t_out = threading.Thread(target=_consume, args=(stdout, stdout_chunks, stdout_cb), daemon=True)
        t_err = threading.Thread(target=_consume, args=(stderr, stderr_chunks, stderr_cb), daemon=True)
        t_out.start()
        t_err.start()
        threads.extend([t_out, t_err])

        timed_out, exit_status = self._wait_for_exit(channel, timeout)

        for t in threads:
            t.join()

        stdout_text = "".join(stdout_chunks)
        stderr_text = "".join(stderr_chunks)
        if timed_out:
            exit_status = 124
        ok = exit_status == 0
        if timed_out and not stderr_text:
            stderr_text = f"Timeout after {timeout or 0} seconds"
        return RunResult(ok, exit_status, stdout_text, stderr_text)
