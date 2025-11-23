# Configuration

## Defaults
- `approval_policy`: `"never"`
- `sandbox_mode`: `"danger-full-access"`
- `web_search`: enabled
- `model`: `gpt-5.1-codex-max`
- `intelligence`: `balanced`
- `reasoning_level`: `medium` (low/medium/high/extra high)
- `trusted_paths`: `/root`, `/home`, `/mnt/c`, `/mnt/c/Users`

## Management
- On Windows, config lives in `%USERPROFILE%\.codex\config.toml`. On WSL/remote, it is `/root/.codex/config.toml`.
- The Options dialog reads the existing config on launch; it only writes defaults if no config is found.
- Writing uses direct file writes on Windows and root `cat > ~/.codex/config.toml` for WSL/remote.

## Password Persistence
- The Windows-side configuration file `codex_frontend_config.json` stores the sudo password when the user checks "Save password".
- Passwords are base64-encoded only; no encryption or secure storage is provided.

## Auto-Start Behavior
- If a password is stored or an existing Codex config is found, the UI automatically kicks off the pipeline and skips auth prompts.

## Models and Reasoning
- Model combo mirrors Codex presets: `gpt-5.1-codex-max`, `gpt-5.1-codex`, `gpt-5.1-codex-mini`, `gpt-5.1`, plus legacy/blank entries.
- Reasoning levels: `low`, `medium`, `high`, `extra high`.
- Intelligence: `balanced`, `precise`, `creative`, `fast`.
