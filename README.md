# Accessible Codex Frontend (Windows & WSL)

Screen-reader-friendly desktop UI for running the Codex CLI on Windows or inside WSL. Focus areas:

- **Windows-first, WSL-ready**: Uses the Windows Codex CLI by default and auto-detects WSL as an alternative backend (similar to picking an SSH target).
- **Automatic Codex install/update**: On launch, checks GitHub releases for the latest Windows Codex build (including alpha/beta) and updates if needed.
- **Accessible logging**: Output and thinking panes stream live without jumping the caret; noisy `[stderr]` plumbing and token lines are suppressed from the conversation log.
- **Session portability**: Reads conversation logs from `%USERPROFILE%\\.codex\\sessions` and normalizes paths so history opens on any machine or backend.
- **Config lives in `%USERPROFILE%\\.codex`**: User settings (passwords, backend choice, etc.) are stored beside sessions for portability.
- **Token metrics toggle**: “Show Token Metrics” in the View menu; hidden (and out of the tab order) by default.
- **Menu-first controls**: Run/stop, clear/view logs, and history actions live in menus/shortcuts; the main window stays clean.

## Quick start (dev run)
1) Install deps: `pip install -r requirements.txt`  
2) Launch: `python codex_frontend_wx.py`

## Portable build (one-file exe)
1) `pip install pyinstaller`  
2) `pyinstaller --onefile --noconfirm codex_frontend_wx.py`  
3) Grab `dist\\codex_frontend_wx.exe` and copy it with the `requirements.txt`-installed runtime DLLs (if any). The app will fetch/update the Codex CLI on first launch.

## Authentication
On first run the app offers an accessible chooser to authenticate via ChatGPT-in-browser or by pasting an API key directly into the Codex CLI helper.

## Known good paths
- Sessions: `%USERPROFILE%\\.codex\\sessions`
- Default Windows history root: same as above
- WSL history root: `/root/.codex/sessions`

For more detail, see `agents.md` and the docs under `docs/agents/`.
