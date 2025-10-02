"""Background worker thread for the Codex frontend."""
from __future__ import annotations

import queue
import threading
from typing import Dict, List, Optional, Tuple

from . import codex_exec
from . import configuration
from . import history
from . import parsing
from . import settings
from .run_result import RunResult


class Worker(threading.Thread):
    def __init__(self, ui_ref):
        super().__init__(daemon=True)
        self.ui = ui_ref
        self.q: "queue.Queue[dict]" = queue.Queue()
        self.should_stop = threading.Event()
        self.session_ids: Dict[str, Optional[str]] = {}

    def log(self, msg: str) -> None:
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
                        trust_paths=item.get("trust_paths"),
                    )
                elif action == "refresh_history":
                    self.refresh_history(item.get("password"), item.get("conversation_dir"))
                elif action == "open_history":
                    self.open_history(item.get("password"), item.get("path"))
                elif action == "new_conversation":
                    self.new_conversation(item.get("password"), item.get("conversation_dir"))
                elif action == "stop":
                    self.should_stop.set()
            except Exception as exc:  # pragma: no cover - defensive
                self.log(f"Worker exception: {exc}")

    # Pipeline -----------------------------------------------------

    def pipeline(self, password: Optional[str], conversation_dir: Optional[str]) -> None:
        self.set_task("Checking backend shell")
        ok, msg = codex_exec.check_shell_ready()
        self.log(msg)
        if not ok:
            self.set_task("Idle")
            return

        self.set_task("Checking codex CLI")
        ok, msg = codex_exec.check_codex_installed()
        self.log(msg)
        if not ok:
            self.set_task("Idle")
            return

        if conversation_dir:
            ok, msg = history.ensure_conversation_dir(password, conversation_dir)
            if not ok:
                self.log(f"Conversation dir error: {msg}")
            else:
                self.log(f"Conversation dir ready: {msg}")

        self.set_task("codex help")
        help_text = codex_exec.log_codex_help()
        if help_text:
            self.log(help_text)

        self.set_task("Writing default 'no-approval' config")
        ok, conf_msg = configuration.apply_config_as_root(
            password=password,
            model=None,
            approval_policy=settings.DEFAULT_APPROVAL_POLICY,
            sandbox_mode=settings.DEFAULT_SANDBOX_MODE,
            web_search=settings.DEFAULT_ENABLE_WEB_SEARCH,
            trust_paths=settings.DEFAULT_TRUST_PATHS,
        )
        self.log(conf_msg)
        self.log(configuration.read_config_as_root(password))

        self.set_task("Running codex exec health check")
        res = codex_exec.codex_exec_prompt(settings.DEFAULT_EXEC_PROMPT, password)
        self.log(f"[codex exec] rc={res.code}")
        stdout = (res.stdout or "").strip()
        if stdout:
            self.log(stdout)
        stderr = (res.stderr or "").strip()
        if stderr:
            self.log("[stderr] " + stderr)

        self.refresh_history(password, conversation_dir)
        self.set_task("Idle")

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

        conversation_path = conversation
        base_dir = conversation_dir or self.ui.get_conversation_dir() or settings.DEFAULT_CONVERSATION_DIR
        if base_dir and base_dir != conversation_dir:
            self.log(f"Using fallback conversation directory: {base_dir}")
        elif not base_dir:
            self.log("Conversation directory not set; history will not be saved.")

        if not conversation_path and base_dir:
            ok, msg = history.create_new_conversation(password, base_dir)
            if ok:
                conversation_path = msg
                self.log(f"Auto-created conversation file: {conversation_path}")
                self.ui.start_new_conversation(conversation_path)
                self.session_ids[conversation_path] = None
            else:
                self.log(f"Failed to prepare conversation file: {msg}")

        self.ui.begin_run_log()
        session_state_before = codex_exec.session_snapshot(password)
        self.set_task("Running codex exec")
        self.ui.append_thinking_text(f"Executing prompt: {prompt}")

        stdout_parser = parsing.CodexIncrementalSplitter()
        stderr_parser = parsing.CodexIncrementalSplitter()
        stdout_chunks: List[str] = []
        stderr_chunks: List[str] = []
        stdout_tail = ""
        stderr_tail = ""

        def _handle_stdout_line(line: str) -> None:
            thinking_blocks, cleaned_line = stdout_parser.feed_line(line)
            for block in thinking_blocks:
                self.ui.append_thinking_text(block)
            if cleaned_line is not None:
                if parsing.should_hide_from_output(cleaned_line):
                    return
                if parsing.should_route_to_thinking(cleaned_line):
                    self.ui.append_thinking_text(cleaned_line)
                else:
                    self.ui.append_log(cleaned_line)

        def _handle_stderr_line(line: str) -> None:
            thinking_blocks, cleaned_line = stderr_parser.feed_line(line)
            for block in thinking_blocks:
                self.ui.append_thinking_text(block)
            if cleaned_line is not None:
                if parsing.should_hide_from_output(cleaned_line):
                    return
                routed = parsing.should_route_to_thinking(cleaned_line)
                target_text = cleaned_line if routed else f"[stderr] {cleaned_line}"
                if routed:
                    self.ui.append_thinking_text(target_text)
                else:
                    self.ui.append_log(target_text)

        def process_stdout(chunk: str) -> None:
            nonlocal stdout_tail
            stdout_chunks.append(chunk)
            stdout_tail += chunk
            self.ui.append_run_log_chunk(chunk)
            while True:
                idx = stdout_tail.find("\n")
                if idx == -1:
                    break
                line = stdout_tail[: idx + 1]
                stdout_tail = stdout_tail[idx + 1 :]
                _handle_stdout_line(line)

        def process_stderr(chunk: str) -> None:
            nonlocal stderr_tail
            stderr_chunks.append(chunk)
            stderr_tail += chunk
            self.ui.append_run_log_chunk(chunk)
            while True:
                idx = stderr_tail.find("\n")
                if idx == -1:
                    break
                line = stderr_tail[: idx + 1]
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

        refresh_dir = base_dir or conversation_dir
        self.refresh_history(password, refresh_dir)
        self.ui.finish_run_log(res.ok)

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
    ) -> None:
        self.set_task("Saving config to WSL")
        ok, msg = configuration.apply_config_as_root(
            password=password,
            model=model,
            approval_policy=approval_policy,
            sandbox_mode=sandbox_mode,
            web_search=web_search,
            trust_paths=trust_paths,
        )
        self.log(msg)
        cfg = configuration.read_config_as_root(password)
        self.log(cfg)
        if ok:
            self.ui.set_options_from_toml(cfg)
        self.set_task("Idle")

    # History ------------------------------------------------------

    def refresh_history(self, password: Optional[str], conversation_dir: Optional[str]) -> None:
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
