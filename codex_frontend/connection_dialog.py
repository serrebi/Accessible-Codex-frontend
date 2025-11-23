"""Dialog for configuring backend connection (local WSL or remote SSH)."""
from __future__ import annotations

from typing import Any, Dict

import wx


class ConnectionDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, initial: Dict[str, Any]):
        super().__init__(parent, title="Connection Settings", size=(440, 340))

        modes = ["Local Windows (default)", "Local WSL", "Remote SSH"]
        self.mode_choices = modes
        current_mode = initial.get("mode", "windows")
        selection = 0
        if current_mode == "wsl":
            selection = 1
        elif current_mode == "remote":
            selection = 2

        self.mode_radio = wx.RadioBox(self, label="Backend", choices=modes, majorDimension=1, style=wx.RA_SPECIFY_ROWS)
        self.mode_radio.SetSelection(selection)

        self.host_txt = wx.TextCtrl(self, value=initial.get("host", ""))
        self.port_txt = wx.SpinCtrl(self, min=1, max=65535, initial=int(initial.get("port", 22)))
        self.user_txt = wx.TextCtrl(self, value=initial.get("username", "root"))
        self.pass_txt = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.pass_txt.SetValue(initial.get("password", ""))

        form = wx.FlexGridSizer(4, 2, 6, 6)
        form.Add(wx.StaticText(self, label="Host"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.host_txt, 1, wx.EXPAND)
        form.Add(wx.StaticText(self, label="Port"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.port_txt, 1, wx.EXPAND)
        form.Add(wx.StaticText(self, label="Username"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.user_txt, 1, wx.EXPAND)
        form.Add(wx.StaticText(self, label="Password"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.pass_txt, 1, wx.EXPAND)
        form.AddGrowableCol(1, 1)

        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)

        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(self.mode_radio, 0, wx.ALL | wx.EXPAND, 10)
        layout.Add(form, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        layout.Add(btns, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizerAndFit(layout)

        self.mode_radio.Bind(wx.EVT_RADIOBOX, self._on_mode_change)
        self._on_mode_change(None)

    def _on_mode_change(self, _evt):
        sel = self.mode_radio.GetSelection()
        is_remote = sel == 2
        for widget in (self.host_txt, self.port_txt, self.user_txt, self.pass_txt):
            widget.Enable(is_remote)

    def get_values(self) -> Dict[str, Any]:
        sel = self.mode_radio.GetSelection()
        if sel == 0:
            mode = "windows"
        elif sel == 1:
            mode = "wsl"
        else:
            mode = "remote"
        return {
            "mode": mode,
            "host": self.host_txt.GetValue().strip(),
            "port": self.port_txt.GetValue(),
            "username": self.user_txt.GetValue().strip(),
            "password": self.pass_txt.GetValue(),
        }
