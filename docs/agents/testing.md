# Testing Helpers

- The project does not ship dedicated automated tests for the frontend; helpers are pure Python functions within `codex_frontend_wx.py`.
- Run `python -m py_compile codex_frontend_wx.py` for a quick syntax smoke test.
- For headless checks, stub `wx` components or run under a dummy backend to exercise the worker helper logic without a real UI.
