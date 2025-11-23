"""Helper functions for invoking commands inside WSL."""
from __future__ import annotations

import subprocess
import threading
from typing import Callable, List, Optional, Tuple

from .run_result import RunResult


def bash_single_quote(text: str) -> str:
    return "'" + text.replace("'", "'\"'\"'") + "'"


def available() -> bool:
    try:
        cp = subprocess.run(
            ["wsl.exe", "-e", "bash", "-lc", "echo WSL_OK"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        return cp.returncode == 0 and "WSL_OK" in (cp.stdout or "")
    except FileNotFoundError:
        return False
    except Exception:
        return False


def run_wsl_bash(script: str, input_text: Optional[str] = None, timeout: Optional[int] = None) -> RunResult:
    args = ["wsl.exe", "-e", "bash", "-lc", script]
    try:
        cp = subprocess.run(
            args,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return RunResult(cp.returncode == 0, cp.returncode, cp.stdout, cp.stderr)
    except FileNotFoundError as exc:
        return RunResult(False, 127, "", f"wsl.exe not found: {exc}")
    except subprocess.TimeoutExpired as exc:
        return RunResult(False, 124, exc.stdout or "", f"Timeout: {exc}")
    except Exception as exc:  # pragma: no cover - defensive
        return RunResult(False, 1, "", f"Exception: {exc}")


def run_wsl_root_user(cmd: str, timeout: Optional[int] = None) -> RunResult:
    env_prefix = "export NO_COLOR=1 CLICOLOR=0 CI=1 TERM=dumb;"
    inner = f"{env_prefix} {cmd}"
    script = f"bash -lc {bash_single_quote(inner)}"
    args = ["wsl.exe", "-u", "root", "-e", "bash", "-lc", script]
    try:
        cp = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return RunResult(cp.returncode == 0, cp.returncode, cp.stdout, cp.stderr)
    except Exception as exc:  # pragma: no cover - defensive
        return RunResult(False, 1, "", f"Root fallback exception: {exc}")


def run_wsl_sudo(cmd: str, password: str, timeout: Optional[int] = None) -> RunResult:
    env_prefix = "export NO_COLOR=1 CLICOLOR=0 CI=1 TERM=dumb;"
    inner = f"sudo -S -p '' bash -lc {bash_single_quote(env_prefix + ' ' + cmd)}"
    return run_wsl_bash(inner, input_text=password + "\n", timeout=timeout)


def run_as_root(cmd: str, password: Optional[str], timeout: Optional[int] = None) -> RunResult:
    if password:
        result = run_wsl_sudo(cmd, password, timeout=timeout)
        if result.ok:
            return result
        return run_wsl_root_user(cmd, timeout=timeout)
    return run_wsl_root_user(cmd, timeout=timeout)


def _stream_subprocess(
    args: List[str],
    input_text: Optional[str],
    timeout: Optional[int],
    stdout_cb: Optional[Callable[[str], None]],
    stderr_cb: Optional[Callable[[str], None]],
) -> RunResult:
    try:
        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE if input_text is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        return RunResult(False, 127, "", f"command not found: {exc}")
    except Exception as exc:  # pragma: no cover - defensive
        return RunResult(False, 1, "", f"Exception: {exc}")

    if input_text is not None and proc.stdin:
        try:
            proc.stdin.write(input_text)
            if not input_text.endswith("\n"):
                proc.stdin.write("\n")
        except Exception:
            pass
        finally:
            try:
                proc.stdin.flush()
            except Exception:
                pass
            proc.stdin.close()

    stdout_chunks: List[str] = []
    stderr_chunks: List[str] = []

    def _consume(stream, chunks: List[str], callback: Optional[Callable[[str], None]]):
        try:
            for chunk in iter(stream.readline, ""):
                chunks.append(chunk)
                if callback:
                    callback(chunk)
        finally:
            stream.close()

    threads: List[threading.Thread] = []
    if proc.stdout:
        t = threading.Thread(target=_consume, args=(proc.stdout, stdout_chunks, stdout_cb), daemon=True)
        t.start()
        threads.append(t)
    if proc.stderr:
        t = threading.Thread(target=_consume, args=(proc.stderr, stderr_chunks, stderr_cb), daemon=True)
        t.start()
        threads.append(t)

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    for thread in threads:
        thread.join()

    stdout_text = "".join(stdout_chunks)
    stderr_text = "".join(stderr_chunks)

    if timed_out:
        if not stderr_text:
            stderr_text = f"Timeout after {timeout or 0} seconds"
        return RunResult(False, 124, stdout_text, stderr_text)

    code = proc.returncode if proc.returncode is not None else 1
    return RunResult(code == 0, code, stdout_text, stderr_text)


def stream_wsl_bash(
    script: str,
    input_text: Optional[str],
    timeout: Optional[int],
    stdout_cb: Optional[Callable[[str], None]],
    stderr_cb: Optional[Callable[[str], None]],
) -> RunResult:
    args = ["wsl.exe", "-e", "bash", "-lc", script]
    return _stream_subprocess(args, input_text, timeout, stdout_cb, stderr_cb)


def stream_wsl_root_user(
    cmd: str,
    timeout: Optional[int],
    stdout_cb: Optional[Callable[[str], None]],
    stderr_cb: Optional[Callable[[str], None]],
) -> RunResult:
    env_prefix = "export NO_COLOR=1 CLICOLOR=0 CI=1 TERM=dumb;"
    inner = f"{env_prefix} {cmd}"
    script = f"bash -lc {bash_single_quote(inner)}"
    args = ["wsl.exe", "-u", "root", "-e", "bash", "-lc", script]
    return _stream_subprocess(args, None, timeout, stdout_cb, stderr_cb)


def stream_wsl_sudo(
    cmd: str,
    password: str,
    timeout: Optional[int],
    stdout_cb: Optional[Callable[[str], None]],
    stderr_cb: Optional[Callable[[str], None]],
) -> RunResult:
    env_prefix = "export NO_COLOR=1 CLICOLOR=0 CI=1 TERM=dumb;"
    inner = f"sudo -S -p '' bash -lc {bash_single_quote(env_prefix + ' ' + cmd)}"
    return stream_wsl_bash(inner, input_text=password + "\n", timeout=timeout, stdout_cb=stdout_cb, stderr_cb=stderr_cb)


def stream_as_root(
    cmd: str,
    password: Optional[str],
    timeout: Optional[int],
    stdout_cb: Optional[Callable[[str], None]],
    stderr_cb: Optional[Callable[[str], None]],
) -> RunResult:
    if password:
        result = stream_wsl_sudo(cmd, password, timeout, stdout_cb, stderr_cb)
        if result.ok:
            return result
        return stream_wsl_root_user(cmd, timeout, stdout_cb, stderr_cb)
    return stream_wsl_root_user(cmd, timeout, stdout_cb, stderr_cb)
