# Security Notes

- The GUI can cache the sudo password; treat saved credentials as sensitive.
- All commands execute as root inside WSL, so misuse can impact the entire environment.
- No additional network controls are enforced; behavior relies entirely on the Codex CLI's own restrictions.
- Copying content to the clipboard sends the current conversation log directly to the Windows clipboard without sanitization.
- Password persistence relies on insecure base64 encoding and should not be considered protected storage.
