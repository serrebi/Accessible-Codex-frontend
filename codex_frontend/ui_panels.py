"""wxPython panels and dialogs used by the Codex frontend."""
from __future__ import annotations

from typing import TYPE_CHECKING, List

import wx

from . import settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .mainframe import MainFrame


class OptionsPanel(wx.Panel):
    def __init__(self, parent: wx.Window, mainframe: "MainFrame"):
        super().__init__(parent)
        self.mainframe = mainframe

        self.model_lbl = wx.StaticText(self, label="Model (optional):")
        self.model_txt = wx.TextCtrl(self)
        self.approval_lbl = wx.StaticText(self, label="Approval policy:")
        self.approval_cb = wx.ComboBox(
            self,
            choices=["untrusted", "on-failure", "on-request", "never"],
            style=wx.CB_READONLY,
        )
        self.sandbox_lbl = wx.StaticText(self, label="Sandbox mode:")
        self.sandbox_cb = wx.ComboBox(
            self,
            choices=["read-only", "workspace-write", "danger-full-access"],
            style=wx.CB_READONLY,
        )
        self.web_search_cb = wx.CheckBox(self, label="Enable web_search tool")
        self.trust_lbl = wx.StaticText(self, label="Trusted paths (one per line):")
        self.trust_txt = wx.TextCtrl(self, style=wx.TE_MULTILINE)

        self.load_btn = wx.Button(self, label="&Load from WSL")
        self.save_btn = wx.Button(self, label="&Save to WSL")

        sizer = wx.BoxSizer(wx.VERTICAL)

        def row(label: wx.Window, ctrl: wx.Window) -> None:
            row_sizer = wx.BoxSizer(wx.HORIZONTAL)
            row_sizer.Add(label, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 8)
            row_sizer.Add(ctrl, 1, wx.EXPAND)
            sizer.Add(row_sizer, 0, wx.EXPAND | wx.ALL, 6)

        row(self.model_lbl, self.model_txt)
        row(self.approval_lbl, self.approval_cb)
        row(self.sandbox_lbl, self.sandbox_cb)

        sizer.Add(self.web_search_cb, 0, wx.ALL, 6)
        sizer.Add(self.trust_lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)
        sizer.Add(self.trust_txt, 1, wx.EXPAND | wx.ALL, 6)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_sizer.Add(self.load_btn, 0, wx.RIGHT, 8)
        btn_sizer.Add(self.save_btn, 0)
        sizer.Add(btn_sizer, 0, wx.ALL, 6)

        self.SetSizer(sizer)

        self.approval_cb.SetStringSelection(settings.DEFAULT_APPROVAL_POLICY)
        self.sandbox_cb.SetStringSelection(settings.DEFAULT_SANDBOX_MODE)
        self.web_search_cb.SetValue(settings.DEFAULT_ENABLE_WEB_SEARCH)
        self.trust_txt.SetValue("\n".join(settings.DEFAULT_TRUST_PATHS))

        self.load_btn.Bind(wx.EVT_BUTTON, self.on_load)
        self.save_btn.Bind(wx.EVT_BUTTON, self.on_save)

    def on_load(self, _evt):
        pw = self.mainframe.get_password()
        self.mainframe.worker.q.put({"action": "load_config", "password": pw if pw else None})

    def on_save(self, _evt):
        pw = self.mainframe.get_password()
        model = self.model_txt.GetValue().strip() or None
        approval = self.approval_cb.GetStringSelection()
        sandbox = self.sandbox_cb.GetStringSelection()
        web_search = self.web_search_cb.GetValue()
        trust_paths = [ln.strip() for ln in self.trust_txt.GetValue().splitlines() if ln.strip()]
        self.mainframe.worker.q.put(
            {
                "action": "save_config",
                "password": pw if pw else None,
                "model": model,
                "approval_policy": approval,
                "sandbox_mode": sandbox,
                "web_search": web_search,
                "trust_paths": trust_paths,
            }
        )

    def set_from_toml(self, toml_text: str) -> None:
        model = ""
        approval = settings.DEFAULT_APPROVAL_POLICY
        sandbox = settings.DEFAULT_SANDBOX_MODE
        web_search = settings.DEFAULT_ENABLE_WEB_SEARCH
        trust_paths: List[str] = []

        section = "root"
        for raw in toml_text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"')
                if section == "root":
                    if key == "model":
                        model = value
                    elif key == "approval_policy":
                        approval = value
                    elif key == "sandbox_mode":
                        sandbox = value
                elif section == "tools" and key == "web_search":
                    web_search = value.lower() in ("1", "true", "yes", "on")
            if section.startswith('projects."') and line.startswith("trust_level"):
                path = section[len('projects."'):-1]
                trust_paths.append(path)

        self.model_txt.SetValue(model)
        if approval in ["untrusted", "on-failure", "on-request", "never"]:
            self.approval_cb.SetStringSelection(approval)
        if sandbox in ["read-only", "workspace-write", "danger-full-access"]:
            self.sandbox_cb.SetStringSelection(sandbox)
        self.web_search_cb.SetValue(bool(web_search))
        if trust_paths:
            self.trust_txt.SetValue("\n".join(sorted(set(trust_paths))))
        else:
            self.trust_txt.SetValue("")


class OptionsDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, mainframe: "MainFrame"):
        super().__init__(parent, title="Options", size=(480, 520))
        self.panel = OptionsPanel(self, mainframe)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.panel, 1, wx.EXPAND | wx.ALL, 10)

        close_btn = wx.Button(self, label="Close")
        close_btn.Bind(wx.EVT_BUTTON, self.on_close)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_sizer.AddStretchSpacer(1)
        btn_sizer.Add(close_btn, 0)

        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(sizer)

    def set_from_toml(self, toml_text: str) -> None:
        self.panel.set_from_toml(toml_text)

    def on_close(self, _evt):
        self.EndModal(wx.ID_OK)


class RunLogDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, text: str):
        super().__init__(parent, title="Codex raw run log", size=(640, 480))
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.viewer = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.viewer.SetValue(text or "(no log captured)")
        sizer.Add(self.viewer, 1, wx.EXPAND | wx.ALL, 10)
        close_btn = wx.Button(self, label="Close")
        close_btn.Bind(wx.EVT_BUTTON, self.on_close)
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_sizer.AddStretchSpacer(1)
        btn_sizer.Add(close_btn, 0)
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizerAndFit(sizer)

    def on_close(self, _evt):
        self.EndModal(wx.ID_OK)


class HistoryPanel(wx.Panel):
    def __init__(self, parent: wx.Window, mainframe: "MainFrame"):
        super().__init__(parent)
        self.mainframe = mainframe

        self.refresh_btn = wx.Button(self, label="&Refresh history list")
        self.change_dir_btn = wx.Button(self, label="Change &directory")
        self.load_path_btn = wx.Button(self, label="&Load path...")
        self.dir_label = wx.StaticText(self, label="Directory:")
        self.dir_value = wx.StaticText(self, label="-")
        self.listbox = wx.ListBox(self)
        self.open_btn = wx.Button(self, label="&Open selected")
        self.metrics_label = wx.StaticText(self, label="Tokens used: (unknown)   Remaining: (unknown)")
        self.viewer = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        dir_row = wx.BoxSizer(wx.HORIZONTAL)
        dir_row.Add(self.dir_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        dir_row.Add(self.dir_value, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        main_sizer.Add(dir_row, 0, wx.EXPAND | wx.ALL, 6)
        main_sizer.Add(self.metrics_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        main_sizer.Add(self.listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        main_sizer.Add(self.open_btn, 0, wx.ALL, 6)
        main_sizer.Add(self.viewer, 1, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(main_sizer)

        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
        self.open_btn.Bind(wx.EVT_BUTTON, self.on_open)
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.on_open)
        self.change_dir_btn.Bind(wx.EVT_BUTTON, self.on_change_dir)
        self.load_path_btn.Bind(wx.EVT_BUTTON, self.on_load_path)

        self.refresh_btn.Hide()
        self.change_dir_btn.Hide()
        self.load_path_btn.Hide()

    def on_refresh(self, _evt):
        pw = self.mainframe.get_password()
        self.mainframe.worker.q.put(
            {
                "action": "refresh_history",
                "password": pw if pw else None,
                "conversation_dir": self.mainframe.get_conversation_dir(),
            }
        )

    def on_open(self, _evt):
        sel = self.listbox.GetSelection()
        if sel == wx.NOT_FOUND:
            return
        path = self.listbox.GetClientData(sel) or self.listbox.GetString(sel)
        pw = self.mainframe.get_password()
        self.mainframe.worker.q.put({"action": "open_history", "password": pw if pw else None, "path": path})
        self.mainframe.set_current_conversation(path)

    def populate(self, items: List[str]) -> None:
        self.listbox.Clear()
        current = self.mainframe.current_conversation_path
        selection = wx.NOT_FOUND
        for item in items:
            label = self.mainframe.history_label(item)
            idx = self.listbox.Append(label, item)
            if current and item == current:
                selection = idx
        if selection != wx.NOT_FOUND:
            self.listbox.SetSelection(selection)

    def show_file(self, path: str, text: str) -> None:
        label = self.mainframe.history_label(path)
        self.viewer.SetValue(f"{label}\n\n{text}")

    def set_directory_label(self, path: str) -> None:
        self.dir_value.SetLabel(path or "(not set)")
        self.dir_value.Wrap(400)
        self.Layout()

    def update_metrics(self, text: str) -> None:
        self.metrics_label.SetLabel(text)
        self.metrics_label.Wrap(400)
        self.Layout()

    def on_change_dir(self, _evt):
        current = self.mainframe.get_conversation_dir() or ""
        dlg = wx.TextEntryDialog(self, "Enter conversation directory (WSL path):", "Set conversation directory", value=current)
        if dlg.ShowModal() == wx.ID_OK:
            new_dir = dlg.GetValue().strip()
            self.mainframe.set_conversation_dir(new_dir)
        dlg.Destroy()

    def on_load_path(self, _evt):
        dlg = wx.TextEntryDialog(self, "Enter full path to conversation file (WSL path):", "Load conversation")
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetValue().strip()
            if path:
                pw = self.mainframe.get_password()
                self.mainframe.worker.q.put({"action": "open_history", "password": pw if pw else None, "path": path})
                self.mainframe.set_current_conversation(path)
        dlg.Destroy()
