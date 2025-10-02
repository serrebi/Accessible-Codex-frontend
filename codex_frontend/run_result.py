"""Dataclass representing the result of a command run inside WSL."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RunResult:
    ok: bool
    code: int
    stdout: str
    stderr: str
