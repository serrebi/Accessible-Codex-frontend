# Codex Frontend Overview

The Codex Frontend is a wxPython desktop application for Windows that drives the Codex CLI running inside WSL. It provides a GUI that shells into WSL through `wsl.exe`, manages root-level resources under `/root/.codex`, and mirrors Codex CLI behavior with approvals and sandbox restrictions bypassed.

## Goals
- Deliver a native-feeling Windows UI for Codex while executing all CLI work inside WSL as root.
- Keep configuration and conversation history synchronized with the Codex CLI under `/root/.codex`.
- Preserve responsiveness even when long-running Codex invocations stream large outputs.

## Core Components
- **Main application (`codex_frontend_wx.py`)**: Implements the entire UI, event wiring, and worker thread management.
- **History panel**: Lists conversation files discovered in the configured directories and opens them using root privileges for read access.
- **Chat panel**: Hosts password entry (when needed), Start/Stop/New conversation controls, the live output log, token metrics display, thinking log, and prompt entry field.
- **Worker thread**: Pulls commands from a queue to bootstrap the pipeline, execute prompts, refresh and open history files, and read or write configuration.

## Execution Model
- UI actions enqueue work dictionaries onto `Worker.q`.
- Helper functions (`run_wsl_bash`, `run_wsl_sudo`) invoke Codex CLI commands or filesystem operations inside WSL.
- The worker captures stdout/stderr streams line-by-line, updates UI panes, appends to conversation files, and manages Codex session IDs for resume support.

See the other documents in this folder for deeper dives on UI behavior, configuration, metrics, security considerations, and testing support.

## Sessions
- Conversation history and MCP-style session logs are read from the user-scoped Windows path `%USERPROFILE%\\.codex\\sessions` by default. This is mirrored into WSL when needed so the same files open regardless of host.
- The history panel and “Change Conversation Directory…” menu let users point to any writable folder; paths are normalized to work on either Windows or WSL.
- Token and stderr noise is suppressed in the conversation log to keep session files readable for screen reader users.

## Platforms (Windows / WSL)
- The frontend now prefers the native Windows Codex CLI if present on `PATH`, and will auto-install or update it from the official GitHub releases on launch (including alpha/beta builds).
- WSL remains available as a selectable backend, automatically detected and offered similarly to an SSH target; users can switch via the connection dialog.
- First-run prompts guide the user through Codex authentication either in a browser (ChatGPT) or by providing an API key via the CLI, both exposed in an accessible combo box.
- All filesystem operations are resilient to Windows vs. WSL path separators; stored paths are canonicalized before use.
