"""Application bootstrap helpers for the Codex frontend."""
from __future__ import annotations

import os
import sys

import wx

from .mainframe import MainFrame


class App(wx.App):
    def OnInit(self):  # pragma: no cover - wx entry point
        self.SetAppName("CodexFrontendWSL")
        frame = MainFrame()
        frame.Show()
        return True


def main() -> None:
    if os.name != "nt":
        print("This program is intended for Windows hosts with WSL.", file=sys.stderr)
    app = App(False)
    app.MainLoop()
