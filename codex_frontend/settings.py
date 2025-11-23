"""Shared constants and path helpers for the Codex frontend."""
from __future__ import annotations

import os
from pathlib import Path

APP_TITLE = "Codex Frontend"
CONF_FILENAME = "codex_frontend_config.json"

DEFAULT_APPROVAL_POLICY = "never"
DEFAULT_SANDBOX_MODE = "danger-full-access"
DEFAULT_ENABLE_WEB_SEARCH = True
DEFAULT_INTELLIGENCE = "balanced"
DEFAULT_AUTO_UPDATE_CODEX = True
# Free-form model string (optional); when empty the server default is used.
DEFAULT_MODEL: str = "gpt-5.1-codex-max"
# Reasoning/effort level for flagship models
DEFAULT_REASONING_LEVEL: str = "medium"
DEFAULT_TRUST_PATHS = ["/root", "/home", "/mnt/c", "/mnt/c/Users"]
DEFAULT_CONVERSATION_TOKEN_BUDGET = 8000
HISTORY_INCLUDE_DIR_NAMES = ("sessions", "history", "conversations", "front_conversations")
HISTORY_INCLUDE_SUFFIXES = (".json", ".jsonl", ".md", ".markdown", ".txt", ".log")
DEFAULT_EXEC_PROMPT = "Health check: state your current approval policy and sandbox mode, then stop."


def windows_to_wsl_path(path: str) -> str:
    """Convert a Windows path to a WSL path (best-effort)."""
    if not path:
        return ""
    drive, tail = os.path.splitdrive(path)
    if not drive:
        return path.replace("\\", "/")
    letter = drive.rstrip(":").lower()
    tail = tail.replace("\\", "/")
    if not tail.startswith("/"):
        tail = "/" + tail
    return f"/mnt/{letter}{tail}"


def wsl_to_windows_path(path: str) -> str:
    """Convert a WSL path (/mnt/c/Users/...) back to a Windows path."""
    if not path or not path.startswith("/mnt/") or len(path) < 6:
        return ""
    letter = path[5].upper()
    remainder = path[6:]
    return f"{letter}:{remainder.replace('/', '\\')}"


def default_conversation_dir() -> str:
    """Return a machine-appropriate default conversation directory (Windows path)."""
    home = Path.home() / ".codex" / "sessions"
    return str(home)

def gemini_conversation_dir() -> str:
    """Return a machine-appropriate default conversation directory for Gemini (Windows path)."""
    home = Path.home() / ".gemini" / "sessions"
    return str(home)


# Distinct defaults per backend
DEFAULT_WINDOWS_CONVERSATION_DIR = default_conversation_dir()
DEFAULT_WSL_CONVERSATION_DIR = windows_to_wsl_path(DEFAULT_WINDOWS_CONVERSATION_DIR)
DEFAULT_GEMINI_CONVERSATION_DIR = gemini_conversation_dir()
DEFAULT_CONVERSATION_DIR = DEFAULT_WINDOWS_CONVERSATION_DIR  # native Windows is the new default


def project_root() -> Path:
    """Return the project root directory (one level above this package)."""
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """Legacy project root (still used for assets)."""
    return project_root()


def conf_dir() -> Path:
    """Directory where frontend config JSON is stored (user-scoped, portable)."""
    return Path.home() / ".codex"


def conf_path() -> Path:
    path = conf_dir() / CONF_FILENAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return path
