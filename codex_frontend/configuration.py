"""Root configuration read/write helpers."""
from __future__ import annotations

from typing import List, Optional, Tuple
from pathlib import Path

from . import settings, backend


def build_config_toml(
    model: Optional[str],
    approval_policy: str,
    sandbox_mode: str,
    web_search: bool,
    trust_paths: List[str],
    intelligence: Optional[str] = None,
    reasoning_level: Optional[str] = None,
) -> str:
    lines = []
    if model:
        lines.append(f'model = "{model}"')
    if intelligence:
        lines.append(f'intelligence = "{intelligence}"')
    if reasoning_level:
        lines.append(f'reasoning_level = "{reasoning_level}"')
    lines.append(f'approval_policy = "{approval_policy}"')
    lines.append(f'sandbox_mode = "{sandbox_mode}"')
    if web_search:
        lines.append("")
        lines.append("[tools]")
        lines.append("web_search = true")
    if trust_paths:
        for path in trust_paths:
            clean = path.strip()
            if not clean:
                continue
            lines.append("")
            lines.append(f'[projects."{clean}"]')
            lines.append('trust_level = "trusted"')
    return "\n".join(lines) + "\n"


def apply_config_as_root(
    password: Optional[str],
    model: Optional[str],
    approval_policy: str,
    sandbox_mode: str,
    web_search: bool,
    trust_paths: List[str],
    intelligence: Optional[str] = None,
    reasoning_level: Optional[str] = None,
) -> Tuple[bool, str]:
    # Windows backend: write directly to %USERPROFILE%\.codex
    if backend.is_windows():
        try:
            cfg_dir = Path.home() / ".codex"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            path = cfg_dir / "config.toml"
            content = build_config_toml(
                model, approval_policy, sandbox_mode, web_search, trust_paths, intelligence, reasoning_level
            )
            path.write_text(content, encoding="utf-8")
            return True, f"config.toml written to {path}"
        except Exception as exc:
            return False, f"failed to write config.toml: {exc}"

    content = build_config_toml(
        model,
        approval_policy,
        sandbox_mode,
        web_search,
        trust_paths,
        intelligence,
        reasoning_level,
    )
    cmd = (
        "install -m 700 -d ~/.codex && "
        "cat > ~/.codex/config.toml <<'EOF'\n"
        f"{content}"
        "EOF\n"
        "chmod 600 ~/.codex/config.toml && echo OK"
    )
    result = backend.run_as_root(cmd, password, timeout=60)
    if result.ok and "OK" in result.stdout:
        return True, "config.toml written for root user."
    return False, f"failed to write config.toml: rc={result.code} out={result.stdout.strip()} err={result.stderr.strip()}"


def read_config_as_root(password: Optional[str]) -> str:
    if backend.is_windows():
        path = Path.home() / ".codex" / "config.toml"
        try:
            if path.exists():
                return path.read_text(encoding="utf-8")
            return "no config"
        except Exception as exc:
            return f"no config ({exc})"
    result = backend.run_as_root(
        "test -f ~/.codex/config.toml && cat ~/.codex/config.toml || echo 'no config'",
        password,
        timeout=30,
    )
    return (result.stdout or result.stderr or "").strip()
