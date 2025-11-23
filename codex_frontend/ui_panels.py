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
        self.model_cb = wx.ComboBox(
            self,
            choices=[
                "gpt-5.1-codex-max",
                "gpt-5.1-codex",
                "gpt-5.1-codex-mini",
                "gpt-5.1",
                "gemini-2.0-flash-thinking-exp-1219",
                "",
                "text-davinci-003",
            ],
            style=wx.CB_DROPDOWN,
        )
        self.intel_lbl = wx.StaticText(self, label="Intelligence:")
        self.intel_cb = wx.ComboBox(
            self,
            choices=["balanced", "precise", "creative", "fast"],
            style=wx.CB_READONLY,
        )
        self.reason_lbl = wx.StaticText(self, label="Reasoning level:")
        self.reason_cb = wx.ComboBox(
            self,
            choices=["low", "medium", "high", "extra high"],
            style=wx.CB_READONLY,
        )
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
        self.auto_update_cb = wx.CheckBox(self, label="Auto-update Codex at launch")
        self.features_lbl = wx.StaticText(self, label="Features:")
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

        row(self.model_lbl, self.model_cb)
        row(self.intel_lbl, self.intel_cb)
        row(self.approval_lbl, self.approval_cb)
        row(self.sandbox_lbl, self.sandbox_cb)
        row(self.reason_lbl, self.reason_cb)

        sizer.Add(self.features_lbl, 0, wx.LEFT | wx.TOP, 6)
        sizer.Add(self.web_search_cb, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        sizer.Add(self.auto_update_cb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
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
        try:
            self.model_cb.SetValue(settings.DEFAULT_MODEL)
        except Exception:
            pass
        self.intel_cb.SetStringSelection(settings.DEFAULT_INTELLIGENCE)
        self.reason_cb.SetStringSelection(settings.DEFAULT_REASONING_LEVEL)
        self.auto_update_cb.SetValue(getattr(settings, "DEFAULT_AUTO_UPDATE_CODEX", True))
        self.trust_txt.SetValue("\n".join(settings.DEFAULT_TRUST_PATHS))

        self.load_btn.Bind(wx.EVT_BUTTON, self.on_load)
        self.save_btn.Bind(wx.EVT_BUTTON, self.on_save)

    def on_load(self, _evt):
        pw = self.mainframe.get_password()
        self.mainframe.worker.q.put({"action": "load_config", "password": pw if pw else None})

    def on_save(self, _evt):
        pw = self.mainframe.get_password()
        model = self.model_cb.GetValue().strip() or None
        intelligence = self.intel_cb.GetStringSelection() or settings.DEFAULT_INTELLIGENCE
        reasoning = self.reason_cb.GetStringSelection() or settings.DEFAULT_REASONING_LEVEL
        approval = self.approval_cb.GetStringSelection()
        sandbox = self.sandbox_cb.GetStringSelection()
        web_search = self.web_search_cb.GetValue()
        auto_update = self.auto_update_cb.GetValue()
        trust_paths = [ln.strip() for ln in self.trust_txt.GetValue().splitlines() if ln.strip()]
        try:
            self.mainframe.auto_update_codex = auto_update
        except Exception:
            pass
        self.mainframe.worker.q.put(
            {
                "action": "save_config",
                "password": pw if pw else None,
                "model": model,
                "approval_policy": approval,
                "sandbox_mode": sandbox,
                "web_search": web_search,
                "intelligence": intelligence,
                "reasoning_level": reasoning,
                "auto_update_codex": auto_update,
                "trust_paths": trust_paths,
            }
        )

    def set_from_toml(self, toml_text: str) -> None:
        model = settings.DEFAULT_MODEL
        approval = settings.DEFAULT_APPROVAL_POLICY
        sandbox = settings.DEFAULT_SANDBOX_MODE
        web_search = settings.DEFAULT_ENABLE_WEB_SEARCH
        intelligence = settings.DEFAULT_INTELLIGENCE
        reasoning = settings.DEFAULT_REASONING_LEVEL
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
                    elif key == "intelligence":
                        intelligence = value
                    elif key == "reasoning_level":
                        reasoning = value
                elif section == "tools" and key == "web_search":
                    web_search = value.lower() in ("1", "true", "yes", "on")
            if section.startswith('projects."') and line.startswith("trust_level"):
                path = section[len('projects."'):-1]
                trust_paths.append(path)

        self.model_cb.SetValue(model)
        if approval in ["untrusted", "on-failure", "on-request", "never"]:
            self.approval_cb.SetStringSelection(approval)
        if sandbox in ["read-only", "workspace-write", "danger-full-access"]:
            self.sandbox_cb.SetStringSelection(sandbox)
        if intelligence in ["balanced", "precise", "creative", "fast"]:
            self.intel_cb.SetStringSelection(intelligence)
        if reasoning in ["low", "medium", "high", "extra high"]:
            self.reason_cb.SetStringSelection(reasoning)
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
        self.filter_txt = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.filter_txt.SetHint("Filter history by name or path")
        self.result_count = wx.StaticText(self, label="Showing 0 items")
        self.dir_label = wx.StaticText(self, label="Directory:")
        self.dir_value = wx.StaticText(self, label="-")
        self.listbox = wx.ListBox(self)
        self.open_btn = wx.Button(self, label="&Open selected")
        # Metrics label will be created on demand to stay out of the accessibility tree when hidden
        self.metrics_label: wx.StaticText | None = None
        self.viewer = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.all_items: List[str] = []
        self.metrics_insert_index = 0
        self.metrics_in_sizer = False

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        dir_row = wx.BoxSizer(wx.HORIZONTAL)
        dir_row.Add(self.dir_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        dir_row.Add(self.dir_value, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        controls_row = wx.BoxSizer(wx.HORIZONTAL)
        controls_row.Add(self.refresh_btn, 0, wx.RIGHT, 4)
        controls_row.Add(self.change_dir_btn, 0, wx.RIGHT, 4)
        controls_row.Add(self.load_path_btn, 0, wx.RIGHT, 4)
        controls_row.Add(self.open_btn, 0)

        filter_row = wx.BoxSizer(wx.HORIZONTAL)
        filter_row.Add(wx.StaticText(self, label="Search:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        filter_row.Add(self.filter_txt, 1, wx.EXPAND | wx.RIGHT, 6)
        filter_row.Add(self.result_count, 0, wx.ALIGN_CENTER_VERTICAL)

        main_sizer.Add(dir_row, 0, wx.EXPAND | wx.ALL, 6)
        main_sizer.Add(controls_row, 0, wx.LEFT | wx.RIGHT, 6)
        self.metrics_insert_index = main_sizer.GetItemCount()
        # Metrics label is inserted dynamically when enabled; ensure hidden by default
        self.metrics_in_sizer = False
        main_sizer.Add(filter_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        main_sizer.Add(self.listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        main_sizer.Add(self.viewer, 1, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(main_sizer)

        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
        self.open_btn.Bind(wx.EVT_BUTTON, self.on_open)
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.on_open)
        self.change_dir_btn.Bind(wx.EVT_BUTTON, self.on_change_dir)
        self.load_path_btn.Bind(wx.EVT_BUTTON, self.on_load_path)
        self.filter_txt.Bind(wx.EVT_TEXT, self.on_filter_change)
        self.filter_txt.Bind(wx.EVT_TEXT_ENTER, self.on_filter_enter)

        # Hide on-surface controls; actions remain via menus
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
        self.all_items = items
        self.apply_filter()

    def show_file(self, path: str, text: str) -> None:
        label = self.mainframe.history_label(path)
        self.viewer.SetValue(f"{label}\n\n{text}")

    def set_directory_label(self, path: str) -> None:
        self.dir_value.SetLabel(path or "(not set)")
        self.dir_value.Wrap(400)
        self.Layout()

    def _ensure_metrics_label(self) -> wx.StaticText:
        if self.metrics_label is None or not self.metrics_label:
            self.metrics_label = wx.StaticText(self, label="")
            self.metrics_label.Hide()
        return self.metrics_label

    def _destroy_metrics_label(self) -> None:
        if self.metrics_label is not None:
            try:
                self.metrics_label.Destroy()
            except Exception:
                pass
            self.metrics_label = None
        self.metrics_in_sizer = False

    def set_metrics_visible(self, show: bool) -> None:
        sizer = self.GetSizer()
        if not sizer:
            if show:
                self._ensure_metrics_label().Show()
            return
        if not show:
            if self.metrics_in_sizer:
                try:
                    sizer.Detach(self.metrics_label)
                except Exception:
                    pass
                self.metrics_in_sizer = False
            if self.metrics_label:
                self.metrics_label.Hide()
                self.metrics_label.Disable()
            self._destroy_metrics_label()
        elif show and not self.metrics_in_sizer:
            lbl = self._ensure_metrics_label()
            sizer.Insert(self.metrics_insert_index, lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
            self.metrics_in_sizer = True
            lbl.Show()
            lbl.Enable()
        self.Layout()

    def update_metrics(self, text: str) -> None:
        if not self.metrics_label:
            return
        self.metrics_label.SetLabel(text)
        self.metrics_label.Wrap(400)
        self.Layout()

    def on_filter_change(self, _evt):
        self.apply_filter()

    def on_filter_enter(self, _evt):
        if self.listbox.GetCount() and self.listbox.GetSelection() == wx.NOT_FOUND:
            self.listbox.SetSelection(0)
            self.on_open(None)

    def apply_filter(self) -> None:
        term = self.filter_txt.GetValue().strip().lower()
        self.listbox.Clear()
        current = self.mainframe.current_conversation_path
        selection = wx.NOT_FOUND
        displayed = 0
        for item in self.all_items:
            label = self.mainframe.history_label(item)
            haystack = f"{label.lower()} {item.lower()}"
            if term and term not in haystack:
                continue
            idx = self.listbox.Append(label, item)
            displayed += 1
            if current and item == current:
                selection = idx
        if selection != wx.NOT_FOUND:
            self.listbox.SetSelection(selection)
        self.result_count.SetLabel(f"Showing {displayed} of {len(self.all_items)}")
        self.Layout()

    def on_change_dir(self, _evt):
        current_wsl = self.mainframe.get_conversation_dir() or ""
        start_path = settings.wsl_to_windows_path(current_wsl) if current_wsl else ""
        dlg = wx.DirDialog(self, "Choose conversation directory", defaultPath=start_path)
        if dlg.ShowModal() == wx.ID_OK:
            chosen = dlg.GetPath()
            wsl_path = settings.windows_to_wsl_path(chosen)
            if not wsl_path:
                wx.MessageBox(
                    "Could not convert selected path to a WSL path. Please enter it manually.",
                    "Path conversion failed",
                    wx.OK | wx.ICON_WARNING,
                )
            else:
                self.mainframe.set_conversation_dir(wsl_path)
        dlg.Destroy()

    def on_load_path(self, _evt):
        current_wsl = self.mainframe.get_conversation_dir() or ""
        start_path = settings.wsl_to_windows_path(current_wsl) if current_wsl else ""
        style = wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        dlg = wx.FileDialog(self, "Select conversation file", defaultDir=start_path, style=style)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            wsl_path = settings.windows_to_wsl_path(path)
            if wsl_path:
                pw = self.mainframe.get_password()
                self.mainframe.worker.q.put({"action": "open_history", "password": pw if pw else None, "path": wsl_path})
                self.mainframe.set_current_conversation(wsl_path)
            else:
                wx.MessageBox(
                    "Could not convert selected file path to a WSL path. Please enter it manually.",
                    "Path conversion failed",
                    wx.OK | wx.ICON_WARNING,
                )
        dlg.Destroy()


class AuthDialog(wx.Dialog):
    def __init__(self, parent: wx.Window):
        super().__init__(parent, title="Codex Authentication", size=(420, 260))
        self.method_cb = wx.ComboBox(
            self,
            choices=["ChatGPT browser login (recommended)", "API key"],
            style=wx.CB_READONLY,
        )
        self.method_cb.SetSelection(0)
        self.api_key_txt = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.api_key_txt.Enable(False)

        sizer = wx.BoxSizer(wx.VERTICAL)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(self, label="Authentication method:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(self.method_cb, 1, wx.EXPAND)
        sizer.Add(row, 0, wx.EXPAND | wx.ALL, 10)

        sizer.Add(wx.StaticText(self, label="API key (if selected above):"), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sizer.Add(self.api_key_txt, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btns, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizerAndFit(sizer)

        self.method_cb.Bind(wx.EVT_COMBOBOX, self._on_method_change)
        self._on_method_change(None)

    def _on_method_change(self, _evt):
        is_api = self.method_cb.GetSelection() == 1
        self.api_key_txt.Enable(is_api)

    def get_values(self):
        method = "chatgpt" if self.method_cb.GetSelection() == 0 else "api_key"
        return {"method": method, "api_key": self.api_key_txt.GetValue().strip()}
