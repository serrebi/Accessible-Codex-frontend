"""Main wxPython frame for the Codex frontend."""
from __future__ import annotations

import os
import re
from typing import List, Optional

import wx

from . import backend, local_conf, settings
from .connection_dialog import ConnectionDialog
from .parsing import normalize_thinking_text
from .ui_panels import HistoryPanel, OptionsDialog, RunLogDialog
from .worker import Worker


class MainFrame(wx.Frame):
    def __init__(self):
        super().__init__(parent=None, title=settings.APP_TITLE, size=(960, 720))
        self.CreateStatusBar()
        self.SetStatusText("Ready")

        self.last_options_toml = ""
        self.current_conversation_path: Optional[str] = None
        self.conversation_dir: Optional[str] = settings.DEFAULT_CONVERSATION_DIR
        self.tokens_used: int = 0
        self.token_budget: int = settings.DEFAULT_CONVERSATION_TOKEN_BUDGET
        self.tokens_remaining: Optional[int] = self.token_budget
        self.thinking_history: List[str] = []
        self.conversation_log_lines: List[str] = []
        self.options_dialog: Optional[OptionsDialog] = None
        self.current_run_log_chunks: List[str] = []
        self.last_run_log: str = ""
        self.connection_mode: str = "local"
        self.worker: Optional[Worker] = None

        splitter = wx.SplitterWindow(self)
        splitter.SetMinimumPaneSize(200)
        self.history_panel = HistoryPanel(splitter, self)
        self.chat_panel = wx.Panel(splitter)
        splitter.SplitVertically(self.history_panel, self.chat_panel, 320)
        splitter.SetSashGravity(0.25)

        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(splitter, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

        panel = self.chat_panel
        pwd_lbl = wx.StaticText(panel, label="Password for sudo:")
        pwd_lbl.SetName("Password label")
        self.pwd_tc = wx.TextCtrl(panel, style=wx.TE_PASSWORD | wx.TE_PROCESS_ENTER)
        self.pwd_tc.SetName("Password input")

        self.save_pw_cb = wx.CheckBox(panel, label="Save password to conf file")
        self.save_pw_cb.SetName("Save password checkbox")

        self.start_btn = wx.Button(panel, label="&Start pipeline")
        self.start_btn.SetName("Start pipeline button")
        self.stop_btn = wx.Button(panel, label="S&top worker")
        self.stop_btn.SetName("Stop worker button")

        task_lbl_title = wx.StaticText(panel, label="Current task:")
        task_lbl_title.SetName("Current task label")
        self.task_lbl = wx.StaticText(panel, label="Idle")
        self.task_lbl.SetName("Task value label")

        out_lbl = wx.StaticText(panel, label="Conversation log:")
        out_lbl.SetName("Output label")
        self.output_tc = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.output_tc.SetName("Output log")
        self.token_metrics_lbl = wx.StaticText(panel, label="Tokens used: 0   Remaining: 0 (0.0% left)")
        self.token_metrics_lbl.SetName("Token metrics")
        thinking_lbl = wx.StaticText(panel, label="Thinking / telemetry:")
        thinking_lbl.SetName("Thinking label")
        self.thinking_tc = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.thinking_tc.SetName("Thinking log")

        prompt_lbl = wx.StaticText(panel, label="Prompt:")
        prompt_lbl.SetName("Prompt label")
        self.cmd_tc = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.cmd_tc.SetName("Prompt input")
        self.run_cmd_btn = wx.Button(panel, label="&Send prompt")
        self.run_cmd_btn.SetName("Run prompt button")

        self.copy_log_btn = wx.Button(panel, label="Copy &output")
        self.copy_log_btn.SetName("Copy output button")
        self.view_run_log_btn = wx.Button(panel, label="View &run log")
        self.view_run_log_btn.SetName("View run log button")
        self.new_conversation_btn = wx.Button(panel, label="&New conversation")
        self.new_conversation_btn.SetName("New conversation button")
        self.options_btn = wx.Button(panel, label="&Options…")
        self.options_btn.SetName("Options button")

        pwd_row = wx.BoxSizer(wx.HORIZONTAL)
        pwd_row.Add(pwd_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        pwd_row.Add(self.pwd_tc, 1, wx.ALIGN_CENTER_VERTICAL)
        pwd_row.Add(self.save_pw_cb, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 8)

        cmd_row = wx.BoxSizer(wx.HORIZONTAL)
        cmd_row.Add(self.cmd_tc, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        cmd_row.Add(self.run_cmd_btn, 0)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row.Add(self.start_btn, 0, wx.RIGHT, 6)
        btn_row.Add(self.stop_btn, 0, wx.RIGHT, 6)
        btn_row.Add(self.new_conversation_btn, 0, wx.RIGHT, 6)
        btn_row.Add(self.copy_log_btn, 0, wx.RIGHT, 6)
        btn_row.Add(self.view_run_log_btn, 0, wx.RIGHT, 6)
        btn_row.Add(self.options_btn, 0)

        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(pwd_row, 0, wx.EXPAND | wx.ALL, 6)
        layout.Add(btn_row, 0, wx.EXPAND | wx.ALL, 6)
        layout.Add(task_lbl_title, 0, wx.LEFT | wx.RIGHT, 6)
        layout.Add(self.task_lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        layout.Add(out_lbl, 0, wx.LEFT | wx.RIGHT, 6)
        layout.Add(self.output_tc, 3, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        layout.Add(self.token_metrics_lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)
        layout.Add(thinking_lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)
        layout.Add(self.thinking_tc, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        layout.Add(prompt_lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)
        layout.Add(cmd_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        panel.SetSizer(layout)

        self.password_widgets = [pwd_lbl, self.pwd_tc, self.save_pw_cb]
        self.password_controls_visible = True

        self._initialize_connection()

        self._build_menus()

        self.start_btn.Bind(wx.EVT_BUTTON, self.on_start)
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        self.run_cmd_btn.Bind(wx.EVT_BUTTON, self.on_run_cmd)
        self.cmd_tc.Bind(wx.EVT_TEXT_ENTER, self.on_run_cmd)
        self.pwd_tc.Bind(wx.EVT_TEXT_ENTER, self.on_start)
        self.copy_log_btn.Bind(wx.EVT_BUTTON, self.on_copy_log)
        self.view_run_log_btn.Bind(wx.EVT_BUTTON, self.on_view_run_log)
        self.new_conversation_btn.Bind(wx.EVT_BUTTON, self.on_new_conversation)
        self.options_btn.Bind(wx.EVT_BUTTON, self.on_open_options)

        self.update_token_metrics()

        entries = [
            (wx.ACCEL_CTRL, ord("S"), self.start_btn.GetId()),
            (wx.ACCEL_CTRL, ord("T"), self.stop_btn.GetId()),
            (wx.ACCEL_CTRL, ord("R"), self.run_cmd_btn.GetId()),
            (wx.ACCEL_CTRL, ord("C"), int(self.menu_id_copy_log)),
            (wx.ACCEL_CTRL, ord("H"), int(self.menu_id_refresh_history)),
            (wx.ACCEL_CTRL, ord("O"), int(self.menu_id_options)),
            (wx.ACCEL_CTRL, ord("N"), int(self.menu_id_new_conversation)),
            (wx.ACCEL_CTRL, ord("L"), self.view_run_log_btn.GetId()),
        ]
        self.SetAcceleratorTable(wx.AcceleratorTable(entries))

        self.restart_worker()

        self.auto_start_scheduled = False

        self.load_saved_password()
        self.update_password_visibility()
        self.schedule_auto_start()
        wx.CallAfter(self.cmd_tc.SetFocus)
        self.history_panel.set_directory_label(self.conversation_dir or "")
        self.update_token_metrics()
        self.schedule_history_refresh()

    # Menu ---------------------------------------------------------

    def _build_menus(self) -> None:
        menubar = wx.MenuBar()

        session_menu = wx.Menu()
        session_menu.Append(self.start_btn.GetId(), "Start Pipeline\tCtrl+S")
        session_menu.Append(self.stop_btn.GetId(), "Stop Worker\tCtrl+T")
        session_menu.AppendSeparator()
        self.menu_id_new_conversation = wx.NewIdRef()
        session_menu.Append(int(self.menu_id_new_conversation), "New Conversation\tCtrl+N")
        self.menu_id_refresh_history = wx.NewIdRef()
        session_menu.Append(int(self.menu_id_refresh_history), "Refresh History\tCtrl+H")
        self.menu_id_change_dir = wx.NewIdRef()
        session_menu.Append(int(self.menu_id_change_dir), "Change Conversation Directory…")
        self.menu_id_load_path = wx.NewIdRef()
        session_menu.Append(int(self.menu_id_load_path), "Load Conversation File…")
        session_menu.AppendSeparator()
        self.menu_id_clear_password = wx.NewIdRef()
        session_menu.Append(int(self.menu_id_clear_password), "Clear Saved Password")
        self.menu_id_show_password = wx.NewIdRef()
        session_menu.Append(int(self.menu_id_show_password), "Show Password Panel")
        menubar.Append(session_menu, "&Session")

        tools_menu = wx.Menu()
        self.menu_id_options = wx.NewIdRef()
        tools_menu.Append(int(self.menu_id_options), "Options…\tCtrl+O")
        self.menu_id_connection = wx.NewIdRef()
        tools_menu.Append(int(self.menu_id_connection), "Connection Settings…")
        menubar.Append(tools_menu, "&Tools")

        view_menu = wx.Menu()
        self.menu_id_copy_log = wx.NewIdRef()
        view_menu.Append(int(self.menu_id_copy_log), "Copy Conversation Log\tCtrl+C")
        menubar.Append(view_menu, "&View")

        self.SetMenuBar(menubar)

        self.Bind(wx.EVT_MENU, self.on_new_conversation, id=int(self.menu_id_new_conversation))
        self.Bind(wx.EVT_MENU, self.on_copy_log, id=int(self.menu_id_copy_log))
        self.Bind(wx.EVT_MENU, self.on_open_options, id=int(self.menu_id_options))
        self.Bind(wx.EVT_MENU, self.on_open_connection, id=int(self.menu_id_connection))
        self.Bind(wx.EVT_MENU, lambda evt: self.history_panel.on_refresh(evt), id=int(self.menu_id_refresh_history))
        self.Bind(wx.EVT_MENU, lambda evt: self.history_panel.on_change_dir(evt), id=int(self.menu_id_change_dir))
        self.Bind(wx.EVT_MENU, lambda evt: self.history_panel.on_load_path(evt), id=int(self.menu_id_load_path))
        self.Bind(wx.EVT_MENU, self.on_clear_pw, id=int(self.menu_id_clear_password))
        self.Bind(wx.EVT_MENU, lambda _evt: self.show_password_controls(), id=int(self.menu_id_show_password))

    # Password handling -------------------------------------------

    def show_password_controls(self) -> None:
        if backend.is_remote():
            return
        if self.password_controls_visible:
            return
        for widget in self.password_widgets:
            widget.Show()
        self.password_controls_visible = True
        self.Layout()

    def hide_password_controls(self) -> None:
        if not self.password_controls_visible:
            return
        for widget in self.password_widgets:
            widget.Hide()
        self.password_controls_visible = False
        self.Layout()

    def update_password_visibility(self) -> None:
        if backend.is_remote():
            self.hide_password_controls()
            self.save_pw_cb.SetValue(False)
            self.save_pw_cb.Enable(False)
            menubar = self.GetMenuBar()
            if menubar and hasattr(self, "menu_id_clear_password"):
                menubar.Enable(int(self.menu_id_clear_password), False)
                menubar.Enable(int(self.menu_id_show_password), False)
        else:
            self.save_pw_cb.Enable(True)
            if local_conf.get_saved_password():
                self.hide_password_controls()
                self.save_pw_cb.SetValue(True)
            else:
                self.show_password_controls()
                self.save_pw_cb.SetValue(False)
            menubar = self.GetMenuBar()
            if menubar and hasattr(self, "menu_id_clear_password"):
                menubar.Enable(int(self.menu_id_clear_password), True)
                menubar.Enable(int(self.menu_id_show_password), True)

    def _initialize_connection(self) -> None:
        settings_data = local_conf.get_connection_settings()
        mode = settings_data.get("mode", "local")
        host = settings_data.get("host")
        port = int(settings_data.get("port", 22))
        username = settings_data.get("username", "root") or "root"
        password = settings_data.get("password", "")

        if mode == "remote" and host:
            try:
                backend.use_remote_backend(host=host, port=port, username=username, password=password or "")
                self.connection_mode = "remote"
                self.append_log(f"Configured remote backend: {username}@{host}:{port}")
                self.hide_password_controls()
                self.save_pw_cb.SetValue(False)
                self.save_pw_cb.Enable(False)
            except Exception as exc:
                backend.use_local_backend()
                self.connection_mode = "local"
                self.append_log(f"Failed to initialize remote backend ({exc}); using local WSL instead.")
        else:
            backend.use_local_backend()
            self.connection_mode = "local"

        self.SetStatusText(f"Ready ({backend.backend_description()})")

    def load_saved_password(self) -> None:
        if backend.is_remote():
            self.pwd_tc.SetValue("")
            self.save_pw_cb.SetValue(False)
            self.hide_password_controls()
            return

        pw = local_conf.get_saved_password()
        if pw:
            self.pwd_tc.SetValue(pw)
            self.save_pw_cb.SetValue(True)
            self.append_log("Loaded saved password from conf file.")
            self.hide_password_controls()
        else:
            self.save_pw_cb.SetValue(False)
            self.show_password_controls()

    def schedule_auto_start(self) -> None:
        if getattr(self, "auto_start_scheduled", False):
            return
        conn_settings = local_conf.get_connection_settings()
        if backend.is_remote():
            host = conn_settings.get("host", "")
            password = conn_settings.get("password", "")
            if not host or not password:
                return

            self.auto_start_scheduled = True

            def _auto_start_remote():
                if self.worker.should_stop.is_set():
                    return
                username = conn_settings.get("username", "root") or "root"
                port = conn_settings.get("port", 22)
                self.append_log(
                    f"Detected remote credentials; starting Codex pipeline on {username}@{host}:{port}."
                )
                self.on_start(None)

            wx.CallAfter(_auto_start_remote)
            return

        has_password = bool(self.get_password())
        has_local_conf = settings.conf_path().exists()
        if not has_password and not has_local_conf:
            return

        self.auto_start_scheduled = True

        def _auto_start_local():
            if self.worker.should_stop.is_set():
                return
            if has_password:
                self.append_log("Detected saved password; starting Codex pipeline automatically.")
            elif has_local_conf:
                self.append_log("Detected existing frontend config; starting Codex pipeline automatically.")
            self.on_start(None)

        wx.CallAfter(_auto_start_local)

    def apply_connection_settings(
        self,
        mode: str,
        host: str,
        port: int,
        username: str,
        password: str,
    ) -> None:
        if mode == "remote":
            try:
                backend.use_remote_backend(host=host, port=port, username=username, password=password or "")
            except Exception as exc:
                wx.MessageBox(
                    f"Failed to configure remote backend:\n{exc}",
                    "Connection Error",
                    wx.ICON_ERROR | wx.OK,
                )
                return
            local_conf.save_connection_settings("remote", host, port, username, password)
            self.connection_mode = "remote"
            self.append_log(f"Switched to remote backend: {username}@{host}:{port}")
        else:
            backend.use_local_backend()
            local_conf.save_connection_settings("local", host, port, username, password)
            self.connection_mode = "local"
            self.append_log("Switched to local WSL backend.")

        self.update_password_visibility()
        self.load_saved_password()
        self.restart_worker()
        self.auto_start_scheduled = False
        self.schedule_auto_start()
        self.schedule_history_refresh()

    def get_password(self) -> Optional[str]:
        if backend.is_remote():
            return None
        return self.pwd_tc.GetValue().strip() or None

    # Worker interactions -----------------------------------------

    def restart_worker(self) -> None:
        if self.worker:
            self.worker.q.put({"action": "stop"})
            self.worker.should_stop.set()
            try:
                self.worker.join(timeout=2)
            except RuntimeError:
                pass
        self.worker = Worker(self)
        self.worker.start()
        self.SetStatusText(f"Idle ({backend.backend_description()})")

    def set_task(self, text: str) -> None:
        def _():
            self.task_lbl.SetLabel(text)
            if text.lower() == "idle":
                self.SetStatusText(f"Idle ({backend.backend_description()})")
            else:
                self.SetStatusText(text)

        wx.CallAfter(_)

    def _render_conversation_log(self) -> None:
        text = "\n".join(self.conversation_log_lines)
        if text:
            text += "\n"
        self.output_tc.SetValue(text)
        self.output_tc.ShowPosition(self.output_tc.GetLastPosition())

    def _append_conversation_line(self, text: str) -> None:
        self.conversation_log_lines.append(text)

        def _():
            self._render_conversation_log()

        wx.CallAfter(_)

    def clear_conversation_log(self) -> None:
        self.conversation_log_lines = []

        def _():
            self._render_conversation_log()

        wx.CallAfter(_)

    def append_log(self, text: str) -> None:
        if not text:
            return
        self._append_conversation_line(text)
        self._maybe_update_tokens(text)

    def append_worker_log(self, text: str) -> None:
        if not text:
            return
        self._append_conversation_line(text)
        self._maybe_update_tokens(text)

    def append_thinking_text(self, text: str) -> None:
        if not text:
            return
        clean = normalize_thinking_text(text)
        if not clean:
            return

        def _():
            self.thinking_history.append(clean)
            rendered = "\n\n".join(self.thinking_history) + "\n"
            self.thinking_tc.SetValue(rendered)
            self.thinking_tc.ShowPosition(self.thinking_tc.GetLastPosition())

        wx.CallAfter(_)
        self._maybe_update_tokens(clean)

    def begin_run_log(self) -> None:
        def _():
            self.current_run_log_chunks = []
            self.view_run_log_btn.Enable(False)

        wx.CallAfter(_)

    def append_run_log_chunk(self, chunk: str) -> None:
        if chunk is None:
            return

        def _():
            self.current_run_log_chunks.append(chunk)

        wx.CallAfter(_)

    def finish_run_log(self, success: bool) -> None:
        def _():
            text = "".join(self.current_run_log_chunks)
            self.last_run_log = text
            self.view_run_log_btn.Enable(bool(text.strip()))

        wx.CallAfter(_)

    # History ------------------------------------------------------

    def history_label(self, path: str) -> str:
        if not path:
            return path
        base = self.conversation_dir or ""
        if base and path.startswith(base.rstrip("/") + "/"):
            rel = path[len(base.rstrip("/")) + 1 :]
            return rel or path
        if path.startswith("/root/.codex/"):
            return path[len("/root/.codex/") :]
        return path

    def get_conversation_dir(self) -> Optional[str]:
        return self.conversation_dir

    def set_conversation_dir(self, path: Optional[str]) -> None:
        old = self.conversation_dir
        normalized = (path or "").strip() or None
        if normalized == old:
            self.history_panel.set_directory_label(path or "")
            self.schedule_history_refresh()
            return
        self.conversation_dir = normalized
        self.history_panel.set_directory_label(self.conversation_dir or "")
        self.clear_thinking()
        self.current_conversation_path = None
        self.tokens_used = 0
        self.tokens_remaining = self.token_budget if self.token_budget > 0 else None
        self.update_token_metrics()
        if self.conversation_dir:
            self.append_log(f"Conversation directory set to: {self.conversation_dir}")
        else:
            self.append_log("Conversation directory cleared.")
        self.schedule_history_refresh()

    def set_current_conversation(self, path: Optional[str]) -> None:
        self.current_conversation_path = path

    def set_options_from_toml(self, toml_text: str) -> None:
        def _():
            self.last_options_toml = toml_text
            if self.options_dialog and self.options_dialog.IsShown():
                self.options_dialog.set_from_toml(toml_text)

        wx.CallAfter(_)

    def populate_history_list(self, items: List[str]) -> None:
        wx.CallAfter(self.history_panel.populate, items)

    def show_history_file(self, path: str, text: str) -> None:
        self.set_current_conversation(path)
        wx.CallAfter(self.history_panel.show_file, path, text)

    def start_new_conversation(self, path: str) -> None:
        def _():
            self.current_conversation_path = path
            self.clear_conversation_log()
            self.clear_thinking()
            self.tokens_used = 0
            self.tokens_remaining = self.token_budget if self.token_budget > 0 else None
            self.update_token_metrics()
            label = self.history_label(path)
            self.append_log(f"Started new conversation: {label}")
            self.schedule_history_refresh()
            pw = self.get_password()
            self.worker.q.put({"action": "open_history", "password": pw if pw else None, "path": path})

        wx.CallAfter(_)

    def schedule_history_refresh(self) -> None:
        pw = self.get_password()
        self.worker.q.put(
            {
                "action": "refresh_history",
                "password": pw if pw else None,
                "conversation_dir": self.conversation_dir,
            }
        )

    def clear_thinking(self, initial_text: Optional[str] = None) -> None:
        def _():
            self.thinking_history = []
            self.thinking_tc.Clear()
            if initial_text:
                clean = normalize_thinking_text(initial_text)
                if clean:
                    self.thinking_history.append(clean)
                    self.thinking_tc.SetValue(clean + "\n")
                    self.thinking_tc.ShowPosition(self.thinking_tc.GetLastPosition())

        wx.CallAfter(_)

    # Token metrics ------------------------------------------------

    def _maybe_update_tokens(self, text: str) -> None:
        if not text:
            return
        updated = False

        def _update_used(value: int) -> bool:
            if value < 0:
                return False
            self.tokens_used = value
            if self.token_budget <= 0 or self.tokens_used > self.token_budget:
                self.token_budget = max(self.tokens_used, self.token_budget or 0)
            if self.token_budget > 0:
                self.tokens_remaining = max(self.token_budget - self.tokens_used, 0)
            else:
                self.tokens_remaining = None
            return True

        used_updated = False

        match = re.search(r"tokens\s+used:\s*([0-9,]+)", text, re.IGNORECASE)
        if match:
            try:
                used = int(match.group(1).replace(",", ""))
            except ValueError:
                used = -1
            if _update_used(used):
                used_updated = True

        if not used_updated:
            usage_match = re.search(r"token\s+usage[^:]*:\s*(.*)", text, re.IGNORECASE)
            if usage_match:
                payload = usage_match.group(1)
                total_match = re.search(r"total\s*(?:tokens?)?\s*=?\s*([0-9,]+)", payload, re.IGNORECASE)
                candidate = None
                if total_match:
                    candidate = total_match.group(1)
                else:
                    numbers = re.findall(r"([0-9][0-9,]*)", payload)
                    if numbers:
                        candidate = numbers[-1]
                if candidate:
                    try:
                        used = int(candidate.replace(",", ""))
                    except ValueError:
                        used = -1
                    if _update_used(used):
                        used_updated = True

        if not used_updated:
            total_only = re.search(r"total\s+tokens?:\s*([0-9,]+)", text, re.IGNORECASE)
            if total_only:
                try:
                    used = int(total_only.group(1).replace(",", ""))
                except ValueError:
                    used = -1
                if _update_used(used):
                    used_updated = True

        text_lower = text.lower()
        if "context" in text_lower or "ctx" in text_lower:
            rem_match = re.search(
                r"(?:context\s*(?:remaining|left|available)|(?:remaining|left)\s*(?:context|tokens?))[\s:=-]*([0-9][0-9,]*)",
                text,
                re.IGNORECASE,
            )
            if rem_match:
                try:
                    remaining = int(rem_match.group(1).replace(",", ""))
                except ValueError:
                    remaining = -1
                if remaining >= 0:
                    self.tokens_remaining = remaining
                    tail = text[rem_match.end() :]
                    pct_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", tail)
                    estimate = None
                    if pct_match:
                        try:
                            pct_val = float(pct_match.group(1)) / 100.0
                        except ValueError:
                            pct_val = 0.0
                        if 0.0 < pct_val <= 1.0 and remaining >= 0:
                            estimate = int(round(remaining / pct_val))
                    if estimate is None and self.tokens_used >= 0:
                        estimate = remaining + self.tokens_used
                    if estimate and estimate > 0 and estimate >= self.tokens_used:
                        self.token_budget = max(self.token_budget or 0, estimate)
                        self.tokens_remaining = min(remaining, self.token_budget)
                    else:
                        if self.token_budget <= 0:
                            self.token_budget = remaining + self.tokens_used
                        self.tokens_remaining = remaining
                    updated = True

        if used_updated or updated:
            self.update_token_metrics()

    def update_token_metrics(self) -> None:
        budget = self.token_budget if self.token_budget and self.token_budget > 0 else None
        if self.tokens_remaining is not None:
            remaining = max(self.tokens_remaining, 0)
        elif budget is not None:
            remaining = max(budget - self.tokens_used, 0)
        else:
            remaining = None

        if budget is not None and remaining is not None:
            remaining = min(remaining, budget)
            pct = (remaining / budget) * 100 if budget else 0.0
            text = f"Tokens used: {self.tokens_used:,}   Remaining: {remaining:,} ({pct:.1f}% left)"
        elif budget is not None:
            remaining = max(budget - self.tokens_used, 0)
            pct = (remaining / budget) * 100 if budget else 0.0
            text = f"Tokens used: {self.tokens_used:,}   Remaining: {remaining:,} ({pct:.1f}% left)"
        else:
            text = f"Tokens used: {self.tokens_used:,}"

        def _update_labels():
            if getattr(self, "token_metrics_lbl", None):
                self.token_metrics_lbl.SetLabel(text)
                self.token_metrics_lbl.Wrap(600)
            self.history_panel.update_metrics(text)

        wx.CallAfter(_update_labels)

    # Button/menu callbacks ---------------------------------------

    def on_start(self, _evt) -> None:
        pw = self.get_password()
        if not backend.is_remote() and self.save_pw_cb.GetValue():
            try:
                local_conf.save_password(pw or "")
                self.append_log("Password saved to conf file.")
            except Exception as exc:  # pragma: no cover - defensive
                self.append_log(f"Failed to save password: {exc}")
        self.worker.q.put({"action": "pipeline", "password": pw, "conversation_dir": self.conversation_dir})
        if not backend.is_remote():
            self.hide_password_controls()

    def on_stop(self, _evt) -> None:
        self.worker.q.put({"action": "stop"})
        self.append_log("Requested worker stop. Close the window to exit.")

    def on_clear_pw(self, _evt) -> None:
        if backend.is_remote():
            wx.MessageBox(
                "Local sudo password is not used while a remote backend is active.",
                "Information",
                wx.OK | wx.ICON_INFORMATION,
            )
            return
        local_conf.clear_saved_password()
        self.pwd_tc.SetValue("")
        self.save_pw_cb.SetValue(False)
        self.append_log("Cleared saved password in conf file.")
        self.show_password_controls()
        self.update_password_visibility()

    def on_run_cmd(self, _evt) -> None:
        prompt = self.cmd_tc.GetValue().strip()
        if not prompt:
            self.append_log("No prompt provided.")
            return
        pw = self.get_password()
        self.append_log(f"> {prompt}")
        self.worker.q.put(
            {
                "action": "run_cmd",
                "password": pw,
                "prompt": prompt,
                "conversation": self.current_conversation_path,
                "conversation_dir": self.conversation_dir,
            }
        )
        self.cmd_tc.Clear()
        self.cmd_tc.SetFocus()

    def on_copy_log(self, _evt) -> None:
        text = self.output_tc.GetValue()
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Close()
            self.SetStatusText("Output copied to clipboard.")
        else:
            self.SetStatusText("Clipboard not available.")

    def on_new_conversation(self, _evt) -> None:
        pw = self.get_password()
        self.worker.q.put({"action": "new_conversation", "password": pw, "conversation_dir": self.conversation_dir})

    def on_open_options(self, _evt) -> None:
        if self.options_dialog and self.options_dialog.IsShown():
            self.options_dialog.Raise()
            return
        dlg = OptionsDialog(self, self)
        self.options_dialog = dlg
        if self.last_options_toml:
            dlg.set_from_toml(self.last_options_toml)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()
            self.options_dialog = None

    def on_open_connection(self, _evt) -> None:
        settings_data = local_conf.get_connection_settings()
        dlg = ConnectionDialog(self, settings_data)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            values = dlg.get_values()
            mode = values.get("mode", "local")
            host = values.get("host", "").strip()
            port = int(values.get("port", 22))
            username = values.get("username", "root") or "root"
            password = values.get("password", "")

            if mode == "remote":
                if not host:
                    wx.MessageBox("Remote host is required.", "Connection Error", wx.ICON_ERROR | wx.OK)
                    return
                if not username:
                    wx.MessageBox("Username is required for remote connection.", "Connection Error", wx.ICON_ERROR | wx.OK)
                    return
                if not password:
                    wx.MessageBox("Password is required for remote connection.", "Connection Error", wx.ICON_ERROR | wx.OK)
                    return
            self.apply_connection_settings(mode, host, port, username, password)
        finally:
            dlg.Destroy()

    def on_view_run_log(self, _evt) -> None:
        text = self.last_run_log or "(no log captured)"
        dlg = RunLogDialog(self, text)
        dlg.ShowModal()
        dlg.Destroy()
