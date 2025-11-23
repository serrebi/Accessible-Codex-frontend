"""Main wxPython frame for the Codex frontend."""
from __future__ import annotations

import re
from typing import List, Optional
from pathlib import Path

import wx

from . import backend, local_conf, settings
from .connection_dialog import ConnectionDialog
from .parsing import normalize_thinking_text
from .ui_panels import HistoryPanel, OptionsDialog, RunLogDialog, AuthDialog
from .worker import Worker


class NoFocusPanel(wx.Panel):
    """Panel that refuses keyboard focus to stay out of tab order."""

    def AcceptsFocus(self) -> bool:  # pragma: no cover - GUI focus control
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # pragma: no cover - GUI focus control
        return False


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
        self.live_activity_raw: List[str] = []
        self.live_activity_calllater = None
        self.conversation_log_lines: List[str] = []
        self.options_dialog: Optional[OptionsDialog] = None
        self.current_run_log_chunks: List[str] = []
        self.last_run_log: str = ""
        self.status_footer: str = ""
        self.show_tokens: bool = False
        self.show_thinking: bool = True
        self.connection_mode: str = "local"
        self.remote_password: Optional[str] = None  # Track remote sudo/SSH password for worker tasks
        self.worker: Optional[Worker] = None
        self.conversation_has_been_labeled: bool = False # New flag

        splitter = wx.SplitterWindow(self)
        splitter.SetMinimumPaneSize(200)
        self.history_panel = HistoryPanel(splitter, self)
        self.chat_panel = wx.Panel(splitter)
        splitter.SplitVertically(self.history_panel, self.chat_panel, 320)
        splitter.SetSashGravity(0.25)

        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(splitter, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

        # Main Right Panel Layout
        main_layout = wx.BoxSizer(wx.VERTICAL)
        
        # Top Controls (Password & Help)
        top_controls_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.help_lbl = wx.StaticText(
            self.chat_panel,
            label="Tip: Ctrl+S starts the pipeline, Ctrl+R sends the prompt, Ctrl+L opens the run log.",
        )
        self.help_lbl.SetName("Shortcut help")
        top_controls_sizer.Add(self.help_lbl, 0, wx.EXPAND | wx.ALL, 6)

        pwd_lbl = wx.StaticText(self.chat_panel, label="Password for sudo:")
        pwd_lbl.SetName("Password label")
        self.pwd_tc = wx.TextCtrl(self.chat_panel, style=wx.TE_PASSWORD | wx.TE_PROCESS_ENTER)
        self.pwd_tc.SetName("Password input")
        self.save_pw_cb = wx.CheckBox(self.chat_panel, label="Save password to conf file")
        self.save_pw_cb.SetName("Save password checkbox")
        
        pwd_row = wx.BoxSizer(wx.HORIZONTAL)
        pwd_row.Add(pwd_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        pwd_row.Add(self.pwd_tc, 1, wx.ALIGN_CENTER_VERTICAL)
        pwd_row.Add(self.save_pw_cb, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 8)
        top_controls_sizer.Add(pwd_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        
        # Buttons (Start/Stop/New)
        self.start_btn = wx.Button(self.chat_panel, label="&Start pipeline")
        self.start_btn.SetName("Start pipeline button")
        self.stop_btn = wx.Button(self.chat_panel, label="S&top worker")
        self.stop_btn.SetName("Stop worker button")
        self.start_btn.Hide() # Keep hidden as per original
        self.stop_btn.Hide()

        self.new_conversation_btn = wx.Button(self.chat_panel, label="&New conversation")
        self.new_conversation_btn.SetName("New conversation button")
        self.options_btn = wx.Button(self.chat_panel, label="&Options…")
        self.options_btn.SetName("Options button")
        self.options_btn.Hide()

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row.Add(self.new_conversation_btn, 0, wx.RIGHT, 6)
        top_controls_sizer.Add(btn_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        main_layout.Add(top_controls_sizer, 0, wx.EXPAND)

        # Task Status
        task_row = wx.BoxSizer(wx.HORIZONTAL)
        task_lbl_title = wx.StaticText(self.chat_panel, label="Current task:")
        task_lbl_title.SetName("Current task label")
        self.task_lbl = wx.StaticText(self.chat_panel, label="Idle")
        self.task_lbl.SetName("Task value label")
        task_row.Add(task_lbl_title, 0, wx.RIGHT, 6)
        task_row.Add(self.task_lbl, 1, wx.EXPAND)
        main_layout.Add(task_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # Notebook for Chat and Thinking
        self.notebook = wx.Notebook(self.chat_panel)
        
        # Tab 1: Chat
        self.chat_tab = wx.Panel(self.notebook)
        chat_tab_sizer = wx.BoxSizer(wx.VERTICAL)
        self.output_tc = wx.TextCtrl(self.chat_tab, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.output_tc.SetName("Output log")
        chat_tab_sizer.Add(self.output_tc, 1, wx.EXPAND | wx.ALL, 6)
        self.chat_tab.SetSizer(chat_tab_sizer)
        
        # Tab 2: Thinking
        self.thinking_tab = wx.Panel(self.notebook)
        thinking_tab_sizer = wx.BoxSizer(wx.VERTICAL)
        # Use plain, non-rich edit controls to keep screen readers stable
        self.thinking_tc = wx.TextCtrl(
            self.thinking_tab,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        self.thinking_tc.SetName("Thinking log")
        self.live_activity_lbl = wx.StaticText(self.thinking_tab, label="Live output (raw stdout/stderr):")
        self.live_activity_lbl.SetName("Live activity label")
        # Live output shows latest lines (plain, multiline) but we throttle updates for SR stability
        self.live_activity_tc = wx.TextCtrl(
            self.thinking_tab,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        self.live_activity_tc.SetName("Live activity output")

        thinking_tab_sizer.Add(self.thinking_tc, 1, wx.EXPAND | wx.ALL, 6)
        thinking_tab_sizer.Add(self.live_activity_lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)
        thinking_tab_sizer.Add(self.live_activity_tc, 1, wx.EXPAND | wx.ALL, 6)
        self.thinking_tab.SetSizer(thinking_tab_sizer)

        self.notebook.AddPage(self.chat_tab, "Chat")
        self.notebook.AddPage(self.thinking_tab, "Thinking")
        
        main_layout.Add(self.notebook, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        # Bottom Controls (Prompt)
        bottom_controls_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Token Metrics (Placeholder for insertion)
        self.token_metrics_insert_index = main_layout.GetItemCount() - 1 # Insert before notebook? No, inside main layout? 
        # Let's handle token metrics differently. We'll add a placeholder sizer item in main_layout
        # Or we can just add it to bottom_controls_sizer.
        
        prompt_lbl = wx.StaticText(self.chat_panel, label="Prompt:")
        prompt_lbl.SetName("Prompt label")
        self.cmd_tc = wx.TextCtrl(self.chat_panel, style=wx.TE_PROCESS_ENTER)
        self.cmd_tc.SetName("Prompt input")
        self.run_cmd_btn = wx.Button(self.chat_panel, label="&Send prompt")
        self.run_cmd_btn.SetName("Run prompt button")

        cmd_row = wx.BoxSizer(wx.HORIZONTAL)
        cmd_row.Add(self.cmd_tc, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        cmd_row.Add(self.run_cmd_btn, 0)

        bottom_controls_sizer.Add(prompt_lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)
        bottom_controls_sizer.Add(cmd_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        
        main_layout.Add(bottom_controls_sizer, 0, wx.EXPAND)
        
        self.chat_panel.SetSizer(main_layout)

        # Metrics handling needs adjustment since layout changed
        self.token_metrics_panel = None
        self.token_metrics_lbl = None
        self.token_metrics_in_layout = False
        self.token_metrics_sizer_item = None # Not used in new logic directly
        
        # Thinking controls used for visibility toggling (legacy ref)
        self.thinking_controls = [self.thinking_tab] # We will show/hide the page or tab

        self._apply_accessibility_defaults()
        self.password_widgets = [pwd_lbl, self.pwd_tc, self.save_pw_cb]
        self.password_controls_visible = True

        self._initialize_connection()

        self._build_menus()
        self._apply_visibility_defaults()

        self.start_btn.Bind(wx.EVT_BUTTON, self.on_start)
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        self.run_cmd_btn.Bind(wx.EVT_BUTTON, self.on_run_cmd)
        self.cmd_tc.Bind(wx.EVT_TEXT_ENTER, self.on_run_cmd)
        self.pwd_tc.Bind(wx.EVT_TEXT_ENTER, self.on_start)
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
        ]
        self.SetAcceleratorTable(wx.AcceleratorTable(entries))

        self.restart_worker()

        # Ensure conversation dir matches the initial model/connection state
        self.worker.q.put({"action": "update_conversation_directory", "password": self.get_password()})

        self.auto_start_scheduled = False
        self.auto_update_codex = settings.DEFAULT_AUTO_UPDATE_CODEX

        self.load_saved_password()
        self.update_password_visibility()
        self.schedule_auto_start()
        wx.CallAfter(self.cmd_tc.SetFocus)
        self.history_panel.set_directory_label(self.conversation_dir or "")
        self.update_token_metrics()
        self.schedule_history_refresh()

    # Menu ---------------------------------------------------------

    def _apply_accessibility_defaults(self) -> None:
        """Apply small UI tweaks that make text easier to digest quickly."""
        mono = wx.Font(11, wx.FONTFAMILY_MODERN, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        for ctrl in (self.output_tc, self.thinking_tc):
            try:
                ctrl.SetFont(mono)
            except Exception:
                pass
        self.cmd_tc.SetHint("Type a prompt and press Enter or Ctrl+R")
        self.pwd_tc.SetHint("WSL sudo password (optional)")
        self.help_lbl.Wrap(880)
        if self.token_metrics_lbl:
            self.token_metrics_lbl.Wrap(600)

    def _apply_visibility_defaults(self) -> None:
        # Thinking visible by default
        self._set_thinking_visible(True)
        # Token metrics hidden by default
        self._force_hide_token_metrics()
        # Sync menu checks
        menubar = self.GetMenuBar()
        if menubar:
            menubar.Check(int(self.menu_id_toggle_thinking), True)
            menubar.Check(int(self.menu_id_toggle_tokens), False)

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
        self.menu_id_clear_log = wx.NewIdRef()
        view_menu.Append(int(self.menu_id_clear_log), "Clear Conversation Log")
        self.menu_id_view_run_log = wx.NewIdRef()
        view_menu.Append(int(self.menu_id_view_run_log), "View Run Log")
        self.menu_id_toggle_thinking = wx.NewIdRef()
        view_menu.AppendCheckItem(int(self.menu_id_toggle_thinking), "Show Full Token View (Thinking)")
        view_menu.Check(int(self.menu_id_toggle_thinking), True)
        self.menu_id_toggle_tokens = wx.NewIdRef()
        view_menu.AppendCheckItem(int(self.menu_id_toggle_tokens), "Show Token Metrics")
        view_menu.Check(int(self.menu_id_toggle_tokens), False)
        menubar.Append(view_menu, "&View")

        self.SetMenuBar(menubar)

        self.Bind(wx.EVT_MENU, self.on_new_conversation, id=int(self.menu_id_new_conversation))
        self.Bind(wx.EVT_MENU, self.on_copy_log, id=int(self.menu_id_copy_log))
        self.Bind(wx.EVT_MENU, self.on_clear_log, id=int(self.menu_id_clear_log))
        self.Bind(wx.EVT_MENU, self.on_open_options, id=int(self.menu_id_options))
        self.Bind(wx.EVT_MENU, self.on_open_connection, id=int(self.menu_id_connection))
        self.Bind(wx.EVT_MENU, self.on_view_run_log, id=int(self.menu_id_view_run_log))
        self.Bind(wx.EVT_MENU, self.on_toggle_thinking, id=int(self.menu_id_toggle_thinking))
        self.Bind(wx.EVT_MENU, self.on_toggle_tokens, id=int(self.menu_id_toggle_tokens))
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
        if backend.is_remote() or backend.is_windows():
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

    def update_title(self) -> None:
        mode_map = {
            "windows": "Windows",
            "wsl": "WSL",
            "remote": "Remote",
        }
        label = mode_map.get(self.connection_mode, "Unknown")
        self.SetTitle(f"{settings.APP_TITLE} ({label})")

    def _initialize_connection(self) -> None:
        settings_data = local_conf.get_connection_settings()
        mode = settings_data.get("mode", "windows")
        host = settings_data.get("host")
        port = int(settings_data.get("port", 22))
        username = settings_data.get("username", "root") or "root"
        password = settings_data.get("password", "")

        if mode == "remote" and host:
            try:
                backend.use_remote_backend(host=host, port=port, username=username, password=password or "")
                self.connection_mode = "remote"
                self.remote_password = password or ""
                self.append_log(f"Configured remote backend: {username}@{host}:{port}")
                self.hide_password_controls()
                self.save_pw_cb.SetValue(False)
                self.save_pw_cb.Enable(False)
            except Exception as exc:
                backend.use_local_backend()
                self.connection_mode = "windows"
                self.remote_password = None
                self.append_log(f"Failed to initialize remote backend ({exc}); using local Windows instead.")
        elif mode == "wsl":
            try:
                backend.use_wsl_backend()
                self.connection_mode = "wsl"
                self.remote_password = None
                self.append_log("Configured local WSL backend.")
            except Exception as exc:
                backend.use_windows_backend()
                self.connection_mode = "windows"
                self.remote_password = None
                self.append_log(f"Failed to initialize WSL ({exc}); using local Windows instead.")
        else:
            backend.use_windows_backend()
            self.connection_mode = "windows"
            self.remote_password = None

        self.SetStatusText(f"Ready ({backend.backend_description()})")
        self.update_title()

    def load_saved_password(self) -> None:
        if backend.is_remote() or backend.is_windows():
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
        # Clear fields for new connection context (apply to all modes)
        self.clear_conversation_log()
        self.clear_thinking()
        self.set_task("Idle")

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
            self.remote_password = password or ""
            self.append_log(f"Switched to remote backend: {username}@{host}:{port}")
            
            # Skip remote OS detection for speed
            self.SetStatusText(f"Ready ({backend.backend_description()})")

        elif mode == "wsl":
            try:
                backend.use_wsl_backend()
            except Exception as exc:
                wx.MessageBox(
                    f"WSL is not available:\n{exc}",
                    "WSL Error",
                    wx.ICON_ERROR | wx.OK,
                )
                return
            local_conf.save_connection_settings("wsl", host, port, username, password)
            self.connection_mode = "wsl"
            self.remote_password = None
            self.append_log("Switched to local WSL backend.")
        else:
            backend.use_windows_backend()
            local_conf.save_connection_settings("windows", host, port, username, password)
            self.connection_mode = "windows"
            self.remote_password = None
            self.append_log("Switched to local Windows backend.")

        self.update_password_visibility()
        self.load_saved_password()
        self.restart_worker()
        self.auto_start_scheduled = False
        self.schedule_auto_start()
        self.schedule_history_refresh()
        self.update_title()
        self.worker.q.put({"action": "update_conversation_directory", "password": password})

    def get_password(self) -> Optional[str]:
        if backend.is_remote():
            # Use the stored remote password (needed for sudo and remote pipeline tasks)
            if self.remote_password:
                return self.remote_password
            # Fallback to config on disk if memory copy is missing
            return local_conf.get_connection_settings().get("password") or None
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
            self.status_footer = text if text.lower() != "idle" else ""
            self._render_thinking_text()

        wx.CallAfter(_)

    def _render_conversation_log(self) -> None:
        text = "\n".join(self.conversation_log_lines)
        if text:
            text += "\n"
        self._set_text_preserve_view(self.output_tc, text)

    def _append_conversation_line(self, text: str) -> None:
        self.conversation_log_lines.append(text)

        def _():
            if wx.GetApp():
                self._render_conversation_log()

        if wx.GetApp():
            wx.CallAfter(_)

    def _prepend_conversation_line(self, text: str) -> None:
        self.conversation_log_lines.insert(0, text)

        def _():
            if wx.GetApp():
                self._render_conversation_log()

        if wx.GetApp():
            wx.CallAfter(_)

    def _should_suppress_conversation_line(self, text: str) -> bool:
        """Hide noisy plumbing lines from the user-facing log."""
        stripped = (text or "").strip()
        if not stripped:
            return False
        lower = stripped.lower()
        if stripped.startswith("[stderr]"):
            return True
        if stripped.startswith("[cmd]"):
            return True
        if stripped.startswith("Found ") and "history files" in stripped:
            return True
        if stripped.startswith("Started new conversation:"):
            return True
        if stripped.startswith("Conversation append failed"):
            return True
        if lower.startswith("tokens used"):
            return True
        return False

    def _set_text_preserve_view(self, ctrl: wx.TextCtrl, text: str) -> None:
        """Update text without yanking the user's scroll position."""
        try:
            caret = ctrl.GetInsertionPoint()
            vpos = ctrl.GetScrollPos(wx.VERTICAL)
            hpos = ctrl.GetScrollPos(wx.HORIZONTAL)
            last = ctrl.GetLastPosition()
        except Exception:
            ctrl.SetValue(text)
            return
        ctrl.Freeze()
        ctrl.SetValue(text)
        try:
            caret = min(caret, ctrl.GetLastPosition())
            ctrl.SetInsertionPoint(caret)
            # Restore scroll offsets to avoid jump
            try:
                if last == 0:
                    return
                ctrl.ScrollLines(vpos - ctrl.GetScrollPos(wx.VERTICAL))
                ctrl.SetScrollPos(wx.HORIZONTAL, hpos, refresh=False)
            except Exception:
                pass
        finally:
            ctrl.Thaw()

    def _safe_set_text_preserve_view(self, ctrl: wx.TextCtrl, text: str, scroll_to_end: bool = False) -> None:
        """Safer variant to guard against screen-reader/driver quirks."""
        try:
            self._set_text_preserve_view(ctrl, text)
            if scroll_to_end:
                try:
                    ctrl.ShowPosition(ctrl.GetLastPosition())
                except Exception:
                    pass
        except Exception:
            try:
                ctrl.SetValue(text)
            except Exception:
                pass

    def _set_token_metrics_visible(self, show: bool) -> None:
        self.show_tokens = bool(show)
        panel = getattr(self, "token_metrics_panel", None)
        
        # Layout where metrics should appear (above prompt)
        # We need to find the bottom_controls_sizer.
        # In __init__, we added bottom_controls_sizer to self.chat_panel.GetSizer() as the last item.
        main_sizer = self.chat_panel.GetSizer() if hasattr(self, "chat_panel") else None
        if not main_sizer:
            return
            
        # The bottom controls are the last item in the vertical main_sizer
        try:
            bottom_item = main_sizer.GetItem(main_sizer.GetItemCount() - 1)
            bottom_sizer = bottom_item.GetSizer() if bottom_item else None
        except Exception:
            bottom_sizer = None

        if not bottom_sizer:
            # Fallback if layout is unexpected
            return

        def ensure_panel_exists() -> wx.Panel:
            if getattr(self, "token_metrics_panel", None):
                return self.token_metrics_panel
            # Recreate panel and label
            pnl = NoFocusPanel(self.chat_panel)
            sizer = wx.BoxSizer(wx.VERTICAL)
            self.token_metrics_lbl = wx.StaticText(
                pnl, label="Tokens used: 0   Remaining: 0 (0.0% left)"
            )
            self.token_metrics_lbl.SetName("Token metrics")
            self.token_metrics_lbl.Wrap(600)
            sizer.Add(self.token_metrics_lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)
            pnl.SetSizer(sizer)
            self.token_metrics_panel = pnl
            return pnl

        if not show:
            self._force_hide_token_metrics()
        else:
            panel = ensure_panel_exists()
            # Insert at top of bottom_sizer (index 0)
            # Check if it's already there
            is_in_sizer = False
            for child in bottom_sizer.GetChildren():
                if child.GetWindow() == panel:
                    is_in_sizer = True
                    break
            
            if not is_in_sizer:
                bottom_sizer.Insert(0, panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 0)
            
            panel.Show()
            panel.Enable()
            if self.token_metrics_lbl:
                self.token_metrics_lbl.Wrap(600)
            self.chat_panel.Layout()

        try:
            self.history_panel.set_metrics_visible(show)
            if show and self.token_metrics_lbl:
                self.history_panel.update_metrics(self.token_metrics_lbl.GetLabel())
        except Exception:
            pass

    def _force_hide_token_metrics(self) -> None:
        """Hide token metrics in both chat panel and history panel, and keep them out of tab order."""
        self.show_tokens = False
        panel = getattr(self, "token_metrics_panel", None)

        # Remove from chat bottom sizer if present
        main_sizer = self.chat_panel.GetSizer() if hasattr(self, "chat_panel") else None
        if main_sizer:
            try:
                bottom_item = main_sizer.GetItem(main_sizer.GetItemCount() - 1)
                bottom_sizer = bottom_item.GetSizer() if bottom_item else None
            except Exception:
                bottom_sizer = None
            if bottom_sizer and panel:
                try:
                    bottom_sizer.Detach(panel)
                except Exception:
                    pass
        if panel:
            try:
                panel.Hide()
                panel.Disable()
                panel.Destroy()
            except Exception:
                pass
            self.token_metrics_panel = None
            self.token_metrics_lbl = None

        # Hide history metrics label
        try:
            self.history_panel.set_metrics_visible(False)
            # Also clear the label so screen readers won't announce lingering text
            self.history_panel.metrics_label.SetLabel("")
            self.history_panel.metrics_label.Hide()
            self.history_panel.metrics_in_sizer = False
        except Exception:
            pass

        try:
            self.chat_panel.Layout()
        except Exception:
            pass

    def _set_thinking_visible(self, show: bool) -> None:
        self.show_thinking = bool(show)
        # Manage Notebook pages
        if not hasattr(self, "notebook"):
            return
            
        # Check if Thinking page is present
        page_count = self.notebook.GetPageCount()
        thinking_page_index = -1
        for i in range(page_count):
            if self.notebook.GetPageText(i) == "Thinking":
                thinking_page_index = i
                break
        
        if show:
            if thinking_page_index == -1:
                # Add it back
                self.notebook.AddPage(self.thinking_tab, "Thinking")
        else:
            if thinking_page_index != -1:
                # Remove it (but don't destroy the window, just remove from notebook)
                self.notebook.RemovePage(thinking_page_index)

    def _render_thinking_text(self) -> None:
        body = "\n\n".join(self.thinking_history).strip()
        footer = f"Status: {self.status_footer}" if self.status_footer else ""
        parts = [p for p in (body, footer) if p]
        combined = "\n\n".join(parts)
        if combined:
            combined += "\n"
        self._safe_set_text_preserve_view(self.thinking_tc, combined)

    def reset_live_activity(self) -> None:
        self.live_activity_raw = []
        self.live_activity_pending = False
        def _():
            self.live_activity_tc.SetValue("")
        if wx.GetApp():
            wx.CallAfter(_)

    def append_live_activity_raw(self, chunk: str) -> None:
        """Append raw stdout/stderr chunks to the live activity box without filtering."""
        if chunk is None:
            return
        if isinstance(chunk, bytes):
            try:
                chunk = chunk.decode("utf-8", errors="replace")
            except Exception:
                return
        if not chunk:
            return
        # Split into lines and keep even blank lines to preserve shape
        lines = chunk.splitlines()
        if not lines:
            return

        self.live_activity_raw.extend(lines)
        # Keep a rolling buffer
        if len(self.live_activity_raw) > 600:
            self.live_activity_raw = self.live_activity_raw[-600:]

        # Throttle UI updates to reduce screen reader load.
        def _flush():
            tail = self.live_activity_raw[-10:]
            text = "\n".join(tail)
            self._safe_set_text_preserve_view(self.live_activity_tc, text, scroll_to_end=True)

        if wx.GetApp():
            def _schedule():
                # Coalesce updates: restart a one-shot CallLater at 300ms
                if self.live_activity_calllater is None:
                    self.live_activity_calllater = wx.CallLater(300, _flush)
                else:
                    try:
                        self.live_activity_calllater.Start(300, oneShot=True)
                    except Exception:
                        # Fallback: recreate
                        self.live_activity_calllater = wx.CallLater(300, _flush)
            wx.CallAfter(_schedule)

    def clear_conversation_log(self) -> None:
        self.conversation_log_lines = []

        def _():
            if wx.GetApp():
                self._render_conversation_log()

        if wx.GetApp():
            wx.CallAfter(_)

    def append_log(self, text: str) -> None:
        if not text:
            return
        if self._should_suppress_conversation_line(text):
            self._maybe_update_tokens(text)
            return
        self._append_conversation_line(text)
        self._maybe_update_tokens(text)

    def prepend_log(self, text: str) -> None:
        if not text:
            return
        if self._should_suppress_conversation_line(text):
            self._maybe_update_tokens(text)
            return
        self._prepend_conversation_line(text)
        self._maybe_update_tokens(text)

    def append_worker_log(self, text: str) -> None:
        if not text:
            return
        if self._should_suppress_conversation_line(text):
            self._maybe_update_tokens(text)
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
            self._render_thinking_text()

        if wx.GetApp():
            wx.CallAfter(_)
        self._maybe_update_tokens(clean)

    def begin_run_log(self) -> None:
        def _():
            self.current_run_log_chunks = []
            self.last_run_log = ""
            self.status_footer = "Running..."
            self._render_thinking_text()

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
            self.status_footer = "Idle" if success else "Completed with errors"
            self._render_thinking_text()

        wx.CallAfter(_)

    # History ------------------------------------------------------

    def history_label(self, path: str) -> str:
        if not path:
            return path
        base = self.conversation_dir or ""
        normalized_path = path.replace("\\", "/")
        normalized_base = base.replace("\\", "/")
        if normalized_base and normalized_path.startswith(normalized_base.rstrip("/") + "/"):
            rel = normalized_path[len(normalized_base.rstrip("/")) + 1 :]
            return rel or path
        if normalized_path.startswith("/root/.codex/"):
            return normalized_path[len("/root/.codex/") :]
        win_default = settings.DEFAULT_WINDOWS_CONVERSATION_DIR.replace("\\", "/")
        if normalized_path.startswith(win_default.rstrip("/") + "/"):
            rel = normalized_path[len(win_default.rstrip("/")) + 1 :]
            return rel or path
        return path

    def get_conversation_dir(self) -> Optional[str]:
        return self.conversation_dir

    def set_conversation_dir(self, path: Optional[str]) -> None:
        def _():
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
        
        wx.CallAfter(_)

    def set_current_conversation(self, path: Optional[str]) -> None:
        self.current_conversation_path = path
        if path:
            # Check if it's a default-named conversation
            filename = Path(path).name
            # Pattern for "conversation_YYYYMMDDTHHMMSS.md" or "conversation_YYYYMMDDTHHMMSS_N.md"
            if re.match(r"conversation_\d{8}T\d{6}(_\d+)?\.md", filename):
                self.conversation_has_been_labeled = False
            else:
                self.conversation_has_been_labeled = True
        else:
            self.conversation_has_been_labeled = False

    def set_options_from_toml(self, toml_text: str) -> None:
        def _():
            self.last_options_toml = toml_text
            if self.options_dialog and self.options_dialog.IsShown():
                self.options_dialog.set_from_toml(toml_text)
            try:
                # Update cached auto-update flag from settings (may be mutated by worker)
                self.auto_update_codex = getattr(settings, "DEFAULT_AUTO_UPDATE_CODEX", True)
            except Exception:
                pass

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
            self.schedule_history_refresh()
            self.conversation_has_been_labeled = False # Reset flag for new conversation
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
            self._render_thinking_text()

        wx.CallAfter(_)

    def on_toggle_thinking(self, evt) -> None:
        checked = evt.IsChecked() if evt is not None else True
        self._set_thinking_visible(checked)

    def on_toggle_tokens(self, evt) -> None:
        checked = evt.IsChecked()
        self._set_token_metrics_visible(checked)

    # Token metrics ------------------------------------------------

    def _maybe_update_tokens(self, text: str) -> None:
        if not text:
            return
        updated = False
        normalized = text
        if normalized.lower().startswith("[stderr]"):
            normalized = normalized[len("[stderr]") :].lstrip()

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

        match = re.search(r"tokens?\s+used[:\s-]*([0-9,]+)", normalized, re.IGNORECASE)
        if match:
            try:
                used = int(match.group(1).replace(",", ""))
            except ValueError:
                used = -1
            if _update_used(used):
                used_updated = True

        if not used_updated:
            usage_match = re.search(r"token\s+usage[^:]*:\s*(.*)", normalized, re.IGNORECASE)
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
            total_only = re.search(r"total\s+tokens?:\s*([0-9,]+)", normalized, re.IGNORECASE)
            if total_only:
                try:
                    used = int(total_only.group(1).replace(",", ""))
                except ValueError:
                    used = -1
                if _update_used(used):
                    used_updated = True

        text_lower = normalized.lower()
        if "context" in text_lower or "ctx" in text_lower:
            rem_match = re.search(
                r"(?:context\s*(?:remaining|left|available)|(?:remaining|left)\s*(?:context|tokens?))[\s:=-]*([0-9][0-9,]*)",
                normalized,
                re.IGNORECASE,
            )
            if rem_match:
                try:
                    remaining = int(rem_match.group(1).replace(",", ""))
                except ValueError:
                    remaining = -1
                if remaining >= 0:
                    self.tokens_remaining = remaining
                    tail = normalized[rem_match.end() :]
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

        if not self.show_tokens:
            # Ensure both chat panel and history panel metrics stay hidden and out of tab order
            self._force_hide_token_metrics()
            return

        def _update_labels():
            if getattr(self, "token_metrics_lbl", None):
                self.token_metrics_lbl.SetLabel(text)
                self.token_metrics_lbl.Wrap(600)
            self.history_panel.update_metrics(text)
            if not self.show_tokens:
                # Ensure hidden state stays enforced even if downstream calls try to show it.
                try:
                    self._set_token_metrics_visible(False)
                except Exception:
                    pass

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
        self.worker.q.put(
            {
                "action": "run_cmd",
                "password": pw,
                "prompt": prompt,
                "conversation": self.current_conversation_path,
                "conversation_dir": self.conversation_dir,
            }
        )
        # Keep prompt text so the user can review/edit after sending
        self.cmd_tc.SetFocus()

    def on_copy_log(self, _evt) -> None:
        text = self.output_tc.GetValue()
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Close()
            self.SetStatusText("Output copied to clipboard.")
        else:
            self.SetStatusText("Clipboard not available.")

    def on_clear_log(self, _evt) -> None:
        self.clear_conversation_log()
        self.SetStatusText("Conversation log cleared.")

    def on_clear_thinking(self, _evt) -> None:
        self.clear_thinking()
        self.SetStatusText("Thinking log cleared.")

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
