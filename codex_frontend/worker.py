"""Background worker thread for the Codex frontend."""
from __future__ import annotations

import queue
import threading
from typing import Dict, List, Optional, Tuple
from pathlib import Path

import wx

from . import backend
from . import codex_exec
from . import configuration
from . import history
from . import parsing
from . import settings
from . import ui_panels
from .run_result import RunResult


class Worker(threading.Thread):
    def __init__(self, ui_ref):
        super().__init__(daemon=True)
        self.ui = ui_ref
        self.q: "queue.Queue[dict]" = queue.Queue()
        self.should_stop = threading.Event()
        self.session_ids: Dict[str, Optional[str]] = {}
        self.last_prompt_text: str = ""
        self.last_answer_first_line: str = ""

    def log(self, msg: str) -> None:
        if not msg:
            return
        lower = msg.strip().lower()
        if lower.startswith("[stderr] user") or lower == "user":
            return
        if lower.startswith("[cmd]") or lower.startswith("found ") or lower.startswith("conversation dir"):
            self.ui.append_thinking_text(msg)
            return
        if lower.startswith("[stderr]"):
            self.ui.append_thinking_text(msg)
            return
        self.ui.append_worker_log(msg)

    def set_task(self, msg: str) -> None:
        self.ui.set_task(msg)

    def run(self) -> None:  # pragma: no cover - thread loop
        while not self.should_stop.is_set():
            try:
                item = self.q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                action = item.get("action")
                if action == "pipeline":
                    self.pipeline(item.get("password"), item.get("conversation_dir"))
                elif action == "run_cmd":
                    self.run_cmd(
                        password=item.get("password"),
                        prompt=item.get("prompt"),
                        conversation=item.get("conversation"),
                        conversation_dir=item.get("conversation_dir"),
                    )
                elif action == "load_config":
                    self.load_config(item.get("password"))
                elif action == "save_config":
                    self.save_config(
                        password=item.get("password"),
                        model=item.get("model"),
                        approval_policy=item.get("approval_policy"),
                        sandbox_mode=item.get("sandbox_mode"),
                        web_search=item.get("web_search"),
                        intelligence=item.get("intelligence"),
                        reasoning_level=item.get("reasoning_level"),
                        auto_update_codex=item.get("auto_update_codex"),
                        trust_paths=item.get("trust_paths"),
                    )
                elif action == "refresh_history":
                    self.refresh_history(item.get("password"), item.get("conversation_dir"))
                elif action == "open_history":
                    self.open_history(item.get("password"), item.get("path"))
                elif action == "new_conversation":
                    self.new_conversation(item.get("password"), item.get("conversation_dir"))
                elif action == "update_conversation_directory":
                    self.update_conversation_directory(item.get("password"))
                elif action == "stop":
                    self.should_stop.set()
            except Exception as exc:  # pragma: no cover - defensive
                self.log(f"Worker exception: {exc}")
    
    def update_conversation_directory(self, password: Optional[str]) -> None:
        self.set_task("Updating conversation directory")
        conv_dir = self._get_conversation_dir_for_model(password)
        self.ui.set_conversation_dir(conv_dir)
        # Refresh history can be slow on remote hosts; skip for remote to stay responsive.
        if backend.is_remote():
            self.set_task("Idle")
            return

        self.refresh_history(password, conv_dir)
        self.set_task("Idle")

    def _extract_model_from_toml(self, toml_text: str) -> Optional[str]:
        for line in toml_text.splitlines():
            if line.strip().startswith("model ="):
                try:
                    return line.split("=", 1)[1].strip().strip('"')
                except IndexError:
                    pass
        return None

    # Pipeline -----------------------------------------------------

    def pipeline(self, password: Optional[str], conversation_dir: Optional[str]) -> None:
        # Keep Codex CLI current (local only). Remote check skipped for speed.
        if getattr(self.ui, "auto_update_codex", settings.DEFAULT_AUTO_UPDATE_CODEX):
            if backend.is_windows():
                self.set_task("Checking for Codex updates...")
                ok, msg = codex_exec.ensure_windows_codex_latest()
                self.ui.append_thinking_text(msg)
                self.ui.append_thinking_text("Codex update check finished.")
                if not ok:
                    self.log(f"Codex update failed: {msg}")
                    self.set_task("Idle")
                    return

        # Ensure authentication before continuing; skip if existing config is present
        ok_auth, auth_msg = codex_exec.ensure_codex_authenticated(self._prompt_auth_choice)
        self.ui.append_thinking_text(auth_msg)
        if not ok_auth:
            self.set_task("Idle")
            return

        if conversation_dir:
            ok, msg = history.ensure_conversation_dir(password, conversation_dir)
            if not ok:
                self.log(f"Conversation dir error: {msg}")
            else:
                self.log(f"Conversation dir ready: {msg}")

        # Load existing config if present; otherwise write a safe default.
        self.set_task("Loading codex config")
        config_text = configuration.read_config_as_root(password)
        if config_text.strip().lower() != "no config":
            self.log("Using existing codex config.")
            # Suppressed verbose config dump
            self.ui.set_options_from_toml(config_text)
        else:
            self.set_task("Writing default 'no-approval' config")
            ok, conf_msg = configuration.apply_config_as_root(
                password=password,
                model=settings.DEFAULT_MODEL or None,
                approval_policy=settings.DEFAULT_APPROVAL_POLICY,
                sandbox_mode=settings.DEFAULT_SANDBOX_MODE,
                web_search=settings.DEFAULT_ENABLE_WEB_SEARCH,
                trust_paths=settings.DEFAULT_TRUST_PATHS,
                intelligence=settings.DEFAULT_INTELLIGENCE,
            )
            self.log(conf_msg)
            config_text = configuration.read_config_as_root(password)
            # self.log(new_cfg) # Suppressed
            if ok:
                self.ui.set_options_from_toml(config_text)

        # Determine and set the conversation directory based on model
        # Reuse config_text to avoid re-reading from remote
        model = self._extract_model_from_toml(config_text)
        conv_dir = self._resolve_conversation_dir(model)
        self.ui.set_conversation_dir(conv_dir)

        self.refresh_history(password, conv_dir)
        self.set_task("Idle")

    def _resolve_conversation_dir(self, model: Optional[str]) -> str:
        is_gemini_model = model is not None and "gemini" in model.lower()
        
        if is_gemini_model:
            if self.ui.connection_mode == "wsl":
                return settings.windows_to_wsl_path(settings.DEFAULT_GEMINI_CONVERSATION_DIR)
            elif self.ui.connection_mode == "windows":
                return settings.DEFAULT_GEMINI_CONVERSATION_DIR
            elif self.ui.connection_mode == "remote":
                return "~/.gemini/sessions" 
        
        if self.ui.connection_mode == "wsl":
            return "/root/.codex/sessions"
        elif self.ui.connection_mode == "windows":
            return settings.DEFAULT_WINDOWS_CONVERSATION_DIR
        elif self.ui.connection_mode == "remote":
            return "~/.codex/sessions"
            
        return settings.DEFAULT_WINDOWS_CONVERSATION_DIR

    # Command execution -------------------------------------------

    def run_cmd(
        self,
        password: Optional[str],
        prompt: str,
        conversation: Optional[str],
        conversation_dir: Optional[str],
    ) -> None:
        if not prompt or not prompt.strip():
            self.log("No prompt provided.")
            return
        self.last_prompt_text = prompt.strip()
        # Show prompt in log just before we stream the answer
        self.ui.append_log(f"user: {self.last_prompt_text}")

        conversation_path = conversation
        base_dir = conversation_dir or self.ui.get_conversation_dir() or settings.DEFAULT_CONVERSATION_DIR
        if base_dir and base_dir != conversation_dir:
            self.log(f"Using fallback conversation directory: {base_dir}")
        elif not base_dir:
            self.log("Conversation directory not set; history will not be saved.")

        is_newly_created_conversation = False # Flag to track if create_new_conversation was just called
        if not conversation_path and base_dir:
            ok, msg = history.create_new_conversation(password, base_dir)
            if ok:
                conversation_path = msg
                is_newly_created_conversation = True
                self.log(f"Auto-created conversation file: {conversation_path}")
                self.ui.start_new_conversation(conversation_path)
                self.session_ids[conversation_path] = None
            else:
                self.log(f"Failed to prepare conversation file: {msg}")

        self.ui.begin_run_log()
        self.ui.reset_live_activity()
        session_state_before = codex_exec.session_snapshot(password)
        self.set_task("Running codex exec")
        self.ui.append_thinking_text(f"Executing prompt: {prompt}")

        stdout_parser = parsing.CodexIncrementalSplitter()
        stderr_parser = parsing.CodexIncrementalSplitter()
        stdout_chunks: List[str] = []
        stderr_chunks: List[str] = []
        stdout_tail = ""
        stderr_tail = ""
        last_tokens_label = False
        first_answer_line = True

        def _handle_stdout_line(line: str) -> None:
            thinking_blocks, cleaned_line = stdout_parser.feed_line(line)
            for block in thinking_blocks:
                self.ui.append_thinking_text(block)
            if cleaned_line is not None:
                if parsing.should_hide_from_output(cleaned_line):
                    return
                text_line = cleaned_line.strip()
                # Filter token lines from log but still track metrics
                if text_line.lower().startswith("tokens used"):
                    self.ui._maybe_update_tokens(text_line)
                    return
                if text_line.lower().startswith("context") and "token" in text_line.lower():
                    self.ui._maybe_update_tokens(text_line)
                    return
                if text_line.lower() == "user":
                    return
                if parsing.should_route_to_thinking(cleaned_line):
                    self.ui.append_thinking_text(cleaned_line)
                else:
                    nonlocal first_answer_line
                    if first_answer_line:
                        self.last_answer_first_line = cleaned_line.strip()
                        first_answer_line = False
                    self.ui.append_log(cleaned_line)

        def _handle_stderr_line(line: str) -> None:
            thinking_blocks, cleaned_line = stderr_parser.feed_line(line)
            for block in thinking_blocks:
                self.ui.append_thinking_text(block)
            if cleaned_line is not None:
                if parsing.should_hide_from_output(cleaned_line):
                    return
                nonlocal last_tokens_label
                clean = cleaned_line.strip()
                if not clean:
                    return
                lower = clean.lower()
                # Session IDs: ignore in UI (kept internally elsewhere)
                if lower.startswith("[stderr] session id") or lower.startswith("session id"):
                    return
                # Drop duplicated prompt/answer echos coming from stderr
                if clean == self.last_prompt_text or clean == f"user: {self.last_prompt_text}":
                    return
                if self.last_answer_first_line and clean.startswith(self.last_answer_first_line):
                    return
                # Collapse token usage lines into a single readable entry
                if last_tokens_label and clean.replace(",", "").isdigit():
                    self.ui._maybe_update_tokens(f"tokens used: {clean}")
                    last_tokens_label = False
                    return
                if lower.startswith("tokens used"):
                    last_tokens_label = True
                    return
                # Classify stderr lines: commands/diagnostics to thinking, content to log
                tech_noise = (
                    lower.startswith("mcp startup")
                    or lower.startswith("exec")
                    or "pwsh.exe" in lower
                    or "wmic" in lower
                    or "get-computerinfo" in lower
                )
                plan_keywords = ("i'm ", "i am ", "i'll ", "i will ", "planning", "i'm putting", "let me", "here's the plan")
                is_plan = any(lower.startswith(k) for k in plan_keywords)
                if clean.startswith("- ") or clean.startswith("•"):
                    routed = False  # treat as answer content
                elif tech_noise or is_plan:
                    routed = True
                else:
                    routed = parsing.should_route_to_thinking(cleaned_line) or lower.startswith("thinking")

                target_text = clean if routed else f"[stderr] {clean}"
                if routed:
                    self.ui.append_thinking_text(target_text)
                else:
                    self.ui.append_log(target_text)

        def process_stdout(chunk: str) -> None:
            nonlocal stdout_tail
            stdout_chunks.append(chunk)
            stdout_tail += chunk
            self.ui.append_run_log_chunk(chunk)
            self.ui.append_live_activity_raw(chunk)
            while True:
                idx = stdout_tail.find("\n")
                if idx == -1:
                    break
                line = stdout_tail[: idx + 1]
                self.ui.append_live_activity_raw(line)
            stdout_tail = stdout_tail[idx + 1 :]
            _handle_stdout_line(line)

        def process_stderr(chunk: str) -> None:
            nonlocal stderr_tail
            stderr_chunks.append(chunk)
            stderr_tail += chunk
            self.ui.append_run_log_chunk(chunk)
            self.ui.append_live_activity_raw(chunk)
            while True:
                idx = stderr_tail.find("\n")
                if idx == -1:
                    break
                line = stderr_tail[: idx + 1]
                self.ui.append_live_activity_raw(line)
            stderr_tail = stderr_tail[idx + 1 :]
            _handle_stderr_line(line)

        session_id = self.session_ids.get(conversation_path or "") if conversation_path else None

        if session_id:
            res = codex_exec.codex_resume_prompt_stream(
                prompt,
                password,
                session_id,
                process_stdout,
                process_stderr,
            )
            if not res.ok:
                self.log(f"Resume failed (session {session_id}), falling back to new session: rc={res.code}")
                if conversation_path:
                    self.session_ids[conversation_path] = None
                res = codex_exec.codex_exec_prompt_stream(prompt, password, process_stdout, process_stderr)
        else:
            res = codex_exec.codex_exec_prompt_stream(prompt, password, process_stdout, process_stderr)

        if stdout_tail:
            _handle_stdout_line(stdout_tail)
            stdout_tail = ""
        if stderr_tail:
            _handle_stderr_line(stderr_tail)
            stderr_tail = ""

        # Flush remaining thinking blocks to thinking panel only (not live)
        for block in stdout_parser.flush() + stderr_parser.flush():
            self.ui.append_thinking_text(block)

        self.log(f"[cmd] rc={res.code}")

        stdout_raw = "".join(stdout_chunks)
        stderr_raw = "".join(stderr_chunks)

        session_state_after = codex_exec.session_snapshot(password)

        if conversation_path:
            ok, msg = history.append_conversation_entry(conversation_path, prompt, stdout_raw, stderr_raw, password)
            if not ok:
                self.log(f"Conversation append failed: {msg}")
            else:
                self.open_history(password, conversation_path)
            if res.ok:
                new_session_id = self._determine_session_id(session_state_before, session_state_after)
                if new_session_id:
                    self.session_ids[conversation_path] = new_session_id
                
                # Auto-label if this was a newly created conversation and not yet labeled
                if is_newly_created_conversation and res.ok and not self.ui.conversation_has_been_labeled:
                    self._auto_label_conversation(password, conversation_path, prompt)

        refresh_dir = base_dir or conversation_dir
        self.refresh_history(password, refresh_dir)
        self.ui.finish_run_log(res.ok)

    def _auto_label_conversation(self, password: Optional[str], current_path: str, user_prompt: str) -> None:
        self.ui.append_thinking_text("Generating conversation title...")
        
        title_prompt = (
            f"Summarize the following prompt into a concise, safe filename (max 5 words, use underscores instead of spaces, no extensions): \"{user_prompt}\". Return ONLY the filename."
        )
        
        # Use a separate, ephemeral execution to avoid polluting the main session context with meta-instructions
        # unless we want the AI to know it labeled it. For now, ephemeral is cleaner.
        res = codex_exec.codex_exec_prompt(title_prompt, password, timeout=30)
        
        if not res.ok or not res.stdout:
            self.ui.append_thinking_text("Title generation failed.")
            return

        new_title = res.stdout.strip()
        # Sanity check
        if len(new_title) > 100 or "\n" in new_title:
             new_title = new_title.splitlines()[0][:50]
        
        ok, new_path, err = history.rename_conversation_file(password, current_path, new_title)
        if ok:
            self.log(f"Renamed conversation to: {new_path}")
            
            # Update session tracking
            sid = self.session_ids.pop(current_path, None)
            if sid:
                self.session_ids[new_path] = sid
            
            # Update UI
            self.ui.set_current_conversation(new_path)
            self.ui.show_history_file(new_path, history.read_history_file(new_path, password))
        else:
            self.log(f"Failed to rename conversation: {err}")

    def _prompt_auth_choice(self) -> Optional[dict]:
        """Block in worker thread while prompting on UI thread for auth method."""
        result: dict = {"value": None}
        evt = threading.Event()

        def _show():
            try:
                dlg = ui_panels.AuthDialog(self.ui)
                if dlg.ShowModal() == wx.ID_OK:
                    result["value"] = dlg.get_values()
            finally:
                dlg.Destroy()
                evt.set()

        wx.CallAfter(_show)
        evt.wait()
        return result.get("value")

    def _determine_session_id(self, before: Dict[str, float], after: Dict[str, float]) -> Optional[str]:
        candidates: List[Tuple[float, str]] = []
        for path, ts in after.items():
            previous = before.get(path)
            if previous is None or ts > previous:
                sid = codex_exec.session_id_from_path(path)
                if sid:
                    candidates.append((ts, sid))
        if candidates:
            candidates.sort(key=lambda item: item[0])
            return candidates[-1][1]
        return None

    def _get_conversation_dir_for_model(self, password: Optional[str]) -> str:
        # Read the current model from the config
        toml_text = configuration.read_config_as_root(password)
        model = None
        for line in toml_text.splitlines():
            if line.strip().startswith("model ="):
                try:
                    model = line.split("=", 1)[1].strip().strip('"')
                except IndexError:
                    pass
                break

        is_gemini_model = model is not None and "gemini" in model.lower()
        
        if is_gemini_model:
            if self.ui.connection_mode == "wsl":
                return settings.windows_to_wsl_path(settings.DEFAULT_GEMINI_CONVERSATION_DIR)
            elif self.ui.connection_mode == "windows":
                return settings.DEFAULT_GEMINI_CONVERSATION_DIR
            elif self.ui.connection_mode == "remote":
                # For remote, if gemini is selected, use .gemini in user's home dir
                # Assuming ~/.gemini/sessions (remote home dir)
                return "~/.gemini/sessions" 
        
        # Default behavior for non-Gemini models or if model not specified
        if self.ui.connection_mode == "wsl":
            return "/root/.codex/sessions"
        elif self.ui.connection_mode == "windows":
            return settings.DEFAULT_WINDOWS_CONVERSATION_DIR
        elif self.ui.connection_mode == "remote":
            # For remote and non-gemini, use ~/.codex (user's home)
            return "~/.codex/sessions"
            
        return settings.DEFAULT_WINDOWS_CONVERSATION_DIR # Fallback

    # Config -------------------------------------------------------

    def load_config(self, password: Optional[str]) -> None:
        self.set_task("Loading config from WSL")
        txt = configuration.read_config_as_root(password)
        self.ui.set_options_from_toml(txt)
        self.log("Loaded config:")
        self.log(txt)
        self.set_task("Idle")

    def save_config(
        self,
        password: Optional[str],
        model: Optional[str],
        approval_policy: str,
        sandbox_mode: str,
        web_search: bool,
        trust_paths: List[str],
        intelligence: Optional[str],
        reasoning_level: Optional[str],
        auto_update_codex: Optional[bool] = None,
    ) -> None:
        self.set_task("Saving config to WSL")
        ok, msg = configuration.apply_config_as_root(
            password=password,
            model=model,
            approval_policy=approval_policy,
            sandbox_mode=sandbox_mode,
            web_search=web_search,
            trust_paths=trust_paths,
            intelligence=intelligence,
            reasoning_level=reasoning_level,
        )
        self.log(msg)
        cfg = configuration.read_config_as_root(password)
        self.log(cfg)
        if ok:
            self.ui.set_options_from_toml(cfg)
            # After saving config, re-evaluate conversation directory
            conv_dir = self._get_conversation_dir_for_model(password)
            self.ui.set_conversation_dir(conv_dir)
        if auto_update_codex is not None:
            settings.DEFAULT_AUTO_UPDATE_CODEX = bool(auto_update_codex)
            try:
                self.ui.auto_update_codex = bool(auto_update_codex)
            except Exception:
                pass
        self.set_task("Idle")

    # History ------------------------------------------------------

    def refresh_history(self, password: Optional[str], conversation_dir: Optional[str]) -> None:
        if backend.is_remote():
            # Silent no-op for remote to avoid noisy logs and latency.
            self.set_task("Idle")
            return

        label = conversation_dir or "(not set)"
        self.set_task(f"Scanning conversation directory: {label}")
        if not conversation_dir:
            self.log("Conversation directory not set.")
            self.ui.populate_history_list([])
            self.set_task("Idle")
            return
        ok, msg = history.ensure_conversation_dir(password, conversation_dir)
        if not ok:
            self.log(f"Conversation dir error: {msg}")
        items, err = history.list_codex_history(password, conversation_dir)
        self.ui.populate_history_list(items)
        if err:
            self.log(f"History scan error: {err}")
        self.log(f"Found {len(items)} history files.")
        self.set_task("Idle")

    def open_history(self, password: Optional[str], path: str) -> None:
        if not path:
            return
        self.set_task(f"Opening: {path}")
        text = history.read_history_file(path, password)
        self.ui.show_history_file(path, text)
        self.set_task("Idle")

    def new_conversation(self, password: Optional[str], conversation_dir: Optional[str]) -> None:
        self.set_task("Starting new conversation")
        if not conversation_dir:
            self.log("Conversation directory not set. Set it before starting a new conversation.")
            self.set_task("Idle")
            return
        ok, path = history.create_new_conversation(password, conversation_dir)
        if ok:
            self.log(f"New conversation file: {path}")
            self.session_ids[path] = None
            self.ui.start_new_conversation(path)
        else:
            self.log(f"Failed to start conversation: {path}")
        self.set_task("Idle")
