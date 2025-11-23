"""Parsing helpers for Codex output and telemetry."""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

TIMESTAMP_LINE_RE = re.compile(r"^\[[0-9]{4}-[0-9]{2}-[0-9]{2}T[^\]]*\]\s*(.*)$")


def split_codex_output(text: str) -> Tuple[List[str], str]:
    """Separate Codex 'thinking' sections from the rest of the transcript."""
    if not text:
        return [], ""

    lines = text.splitlines()
    thinking_segments: List[List[str]] = []
    current_segment: List[str] = []
    cleaned_lines: List[str] = []
    capturing = False

    for line in lines:
        match = TIMESTAMP_LINE_RE.match(line)
        if match:
            label = (match.group(1) or "").strip().lower()
            if capturing and current_segment:
                thinking_segments.append(current_segment)
                current_segment = []
            if label.startswith("thinking"):
                capturing = True
                continue
            capturing = False
            cleaned_lines.append(line)
            continue

        if capturing:
            current_segment.append(line)
        else:
            cleaned_lines.append(line)

    if capturing and current_segment:
        thinking_segments.append(current_segment)

    thinking_texts = ["\n".join(seg).strip() for seg in thinking_segments if any(s.strip() for s in seg)]
    cleaned_text = "\n".join(cleaned_lines)
    if text.endswith("\n"):
        cleaned_text += "\n"
    return thinking_texts, cleaned_text


class CodexIncrementalSplitter:
    """Incrementally separate Codex thinking blocks from console output."""

    def __init__(self):
        self.capturing = False
        self.current_segment: List[str] = []

    def feed_line(self, line: str) -> Tuple[List[str], Optional[str]]:
        text = line.rstrip("\r\n")
        thinking_blocks: List[str] = []
        cleaned_line: Optional[str] = None

        match = TIMESTAMP_LINE_RE.match(text)
        if match:
            label = (match.group(1) or "").strip().lower()
            if self.capturing and self.current_segment:
                block = "\n".join(self.current_segment).strip()
                if block:
                    thinking_blocks.append(block)
                self.current_segment = []
            if label.startswith("thinking"):
                self.capturing = True
            else:
                self.capturing = False
                cleaned_line = text
            return thinking_blocks, cleaned_line

        if self.capturing:
            if text or self.current_segment:
                self.current_segment.append(text)
        else:
            cleaned_line = text
        return thinking_blocks, cleaned_line

    def flush(self) -> List[str]:
        if self.capturing and self.current_segment:
            block = "\n".join(self.current_segment).strip()
            self.current_segment = []
            self.capturing = False
            if block:
                return [block]
        return []


def should_route_to_thinking(line: str) -> bool:
    clean = line.strip()
    if not clean:
        return False
    lower = clean.lower()
    if lower.startswith("thinking") or lower.startswith("[thinking"):
        return True
    if lower.startswith("**"):
        return True
    if "??" in clean and "search" in lower:
        return True
    if "searched:" in lower or "search query:" in lower:
        return True
    if lower.endswith(" codex") or lower == "codex":
        return True
    return False
def should_hide_from_output(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    candidate = stripped
    if candidate.startswith("["):
        close_idx = candidate.find("]")
        if close_idx != -1 and close_idx + 1 < len(candidate):
            candidate = candidate[close_idx + 1 :].lstrip()
    lower = stripped.lower()
    candidate_lower = candidate.lower()
    banner_prefixes = (
        "openai codex v",
        "workdir:",
        "model:",
        "provider:",
        "approval:",
        "sandbox:",
        "reasoning effort:",
        "reasoning summaries:",
        "user instructions:",
        "--------",
    )
    return lower.startswith("--------") or candidate_lower.startswith(banner_prefixes)


def normalize_thinking_text(text: str) -> str:
    lines: List[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        match = TIMESTAMP_LINE_RE.match(stripped)
        if match:
            stripped = (match.group(1) or "").strip()
        if stripped.lower() == "codex":
            stripped = "finished!"
        if stripped:
            lines.append(stripped)
    if not lines:
        stripped = text.strip()
        if not stripped:
            return ""
        match = TIMESTAMP_LINE_RE.match(stripped)
        if match:
            stripped = (match.group(1) or "").strip()
        if stripped.lower() == "codex":
            stripped = "finished!"
        return stripped
    return "\n".join(lines)

