# Execution Flow

## Prompt Lifecycle
1. UI commands enqueue dictionaries describing the requested action onto `Worker.q`.
2. The worker dispatches helpers (`run_wsl_bash`, `run_wsl_sudo`) to run Codex CLI or filesystem operations inside WSL.
3. When executing prompts, the worker shells into `codex exec --dangerously-bypass-approvals`, streaming stdout and stderr line-by-line to the UI.
4. Each line is classified as visible output, thinking/telemetry, or raw log data, and routed to the appropriate panel while also being appended to the active conversation file.
5. Completed runs return a result object that includes the full raw stream so it can be reviewed later in the run log dialog.

## Session Management
- The worker associates Codex session IDs with conversation files.
- Before issuing a new prompt, it attempts to resume the previous session for that file; on failure it falls back to creating a fresh exec session.
- After each run, the worker reopens the active conversation file to keep the displayed log consistent with disk state.

## History Refresh
- Conversation discovery uses `find` with `-printf` to list files sorted by modification time, optionally filtered by configured directory names or suffixes.
- Labels strip the base conversation directory prefix for readability, and selecting an entry loads the file content into the chat context.
