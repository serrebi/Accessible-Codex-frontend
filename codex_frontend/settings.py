"""Shared constants and path helpers for the Codex frontend."""
from __future__ import annotations

from pathlib import Path

APP_TITLE = "Codex Frontend (WSL)"
CONF_FILENAME = "codex_frontend_config.json"

DEFAULT_APPROVAL_POLICY = "never"
DEFAULT_SANDBOX_MODE = "danger-full-access"
DEFAULT_ENABLE_WEB_SEARCH = True
DEFAULT_TRUST_PATHS = ["/root", "/home", "/mnt/c", "/mnt/c/Users"]
DEFAULT_CONVERSATION_DIR = "/root/.codex/conversations"
DEFAULT_CONVERSATION_TOKEN_BUDGET = 8000
HISTORY_INCLUDE_DIR_NAMES = ("sessions", "history", "conversations", "front_conversations")
HISTORY_INCLUDE_SUFFIXES = (".json", ".jsonl", ".md", ".markdown", ".txt", ".log")
DEFAULT_EXEC_PROMPT = "Health check: state your current approval policy and sandbox mode, then stop."


def project_root() -> Path:
    """Return the project root directory (one level above this package)."""
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """Directory where frontend config JSON is stored."""
    return project_root()


def conf_path() -> Path:
    return app_dir() / CONF_FILENAME
