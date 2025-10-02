# Configuration

## Defaults
- `approval_policy`: `"never"`
- `sandbox_mode`: `"danger-full-access"`
- `web_search`: enabled
- `trusted_paths`: `/root`, `/home`, `/mnt/c`, `/mnt/c/Users`

## Management
- The Options dialog reads and writes `/root/.codex/config.toml` using root privileges via the worker helpers.
- On first run, the bootstrap pipeline ensures the configuration file exists by writing defaults (using `install` plus a heredoc) and then rereading the file for logging.

## Password Persistence
- The Windows-side configuration file `codex_frontend_config.json` stores the sudo password when the user checks "Save password".
- Passwords are base64-encoded only; no encryption or secure storage is provided.

## Auto-Start Behavior
- If a password is already stored or an existing frontend configuration file is found, the UI automatically kicks off the bootstrap pipeline when launched.
