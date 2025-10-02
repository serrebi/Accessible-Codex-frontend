# User Interface

## Layout
- **History panel (left)** shows discovered conversations, sorted by modification time, and reopens the active file after each run so context stays aligned.
- **Chat panel (right)** gathers the sudo password (unless already stored), exposes Start/Stop/New conversation controls, displays the conversation log, token metrics strip, thinking/telemetry log, and provides the prompt entry box.

## Options Dialog
- Mirrors the root user's `/root/.codex/config.toml` file, exposing model selection, approval policy, sandbox mode, web search toggle, and trusted path entries.
- Prefills controls from the last fetched snapshot of the TOML file and writes updates back through the worker thread helpers.

## Password Handling
- A "Save password" checkbox persists the sudo password into `codex_frontend_config.json` on the Windows side, encoded with base64.
- When a stored password exists, the chat panel hides the password controls and can auto-start the pipeline without prompting.

## Run Log Access
- The "View run log" button opens a modal containing the full raw stdout and stderr stream from the most recent Codex invocation, preserving data even when portions are filtered out during live display.

## Thinking View
- Lines that include timestamps with "Thinking" or search telemetry tokens are routed into the thinking textbox while the main log keeps visible output.
- Both the conversation log and thinking pane trigger metric updates whenever new text streams in so the UI stays synchronized.
