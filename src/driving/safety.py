"""Safety validation: secrets and command filtering (M5.5)."""
from __future__ import annotations

import os
import re
from pathlib import Path
from types import SimpleNamespace

# Dangerous shell command patterns that are always blocked.
DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bdd\s+if=.*\bof=/dev/", re.IGNORECASE),
    re.compile(r"\bcurl\b.*\|.*\bsh\b", re.IGNORECASE),
    re.compile(r"\bwget\b.*\|.*\bsh\b", re.IGNORECASE),
    re.compile(r"\bnc\s+-[a-zA-Z]*e\b", re.IGNORECASE),
    re.compile(r"\bbash\s+-i\b", re.IGNORECASE),
    re.compile(r"\bpython[3]?\s+.*-c\s+.*socket", re.IGNORECASE),
    re.compile(r"\bsudo\b", re.IGNORECASE),
]

# Commands considered safe for verification or execution by default.
SAFE_BASE_COMMANDS = {
    "python", "python3", "pytest", "pytest-3", "npm", "node", "git", "cat", "ls", "cd",
    "echo", "mkdir", "touch", "cp", "mv", "rm", "find", "grep", "sed", "awk", "pip", "uv",
    "make", "cargo", "rustc", "go", "javac", "java", "docker", "docker-compose", "pwd",
    "which", "dirname", "basename", "head", "tail", "wc", "sort", "uniq", "xargs", "tar",
    "zip", "unzip", "chmod", "chown", "curl", "wget", "sh", "bash", "zsh",
}


def normalize_command(command: str) -> str:
    """Strip shell wrappers and surrounding quotes from a command string."""
    cmd = (command or "").strip()
    for prefix in ("bash -c ", "sh -c ", "zsh -c "):
        if cmd.startswith(prefix):
            cmd = cmd[len(prefix):].strip()
    if (cmd.startswith('"') and cmd.endswith('"')) or (cmd.startswith("'") and cmd.endswith("'")):
        cmd = cmd[1:-1]
    return cmd


def is_safe_command(command: str) -> tuple[bool, str]:
    """Return (ok, reason) for a shell command.

    If `SAFETY_ALLOW_UNSAFE_COMMANDS=1`, every command is allowed (for tests only).
    """
    if not command or not command.strip():
        return True, ""
    if os.environ.get("SAFETY_ALLOW_UNSAFE_COMMANDS") == "1":
        return True, ""
    cmd = normalize_command(command)
    for pat in DANGEROUS_PATTERNS:
        if pat.search(cmd):
            return False, f"blocked by pattern: {pat.pattern}"
    base = cmd.split()[0].split("/")[-1]
    if base in SAFE_BASE_COMMANDS:
        return True, ""
    return False, f"command not in whitelist: {base}"


def is_dangerous_command(command: str) -> tuple[bool, str]:
    """Return (dangerous, reason). Only checks dangerous patterns, not whitelist."""
    if not command or not command.strip():
        return False, ""
    cmd = normalize_command(command)
    for pat in DANGEROUS_PATTERNS:
        if pat.search(cmd):
            return True, f"blocked by pattern: {pat.pattern}"
    return False, ""


def scan_source_for_secrets(root: Path | str = ".") -> list[str]:
    """Scan Python source files for suspicious hardcoded secrets."""
    root = Path(root)
    findings = []
    seen = set()
    secret_patterns = [
        re.compile(r"(api_key|apikey|token|secret|password)\s*=\s*['\"][A-Za-z0-9_\-]{20,}['\"]", re.IGNORECASE),
        re.compile(r"(EXO_API_KEY|LITELLM_MASTER_KEY|OPENAI_API_KEY)\s*=\s*['\"][^'\"]+['\"]"),
    ]
    for p in root.rglob("*.py"):
        if any(part in (".venv", "node_modules", "tests") for part in p.parts):
            continue
        text = p.read_text(errors="ignore")
        for line_no, line in enumerate(text.splitlines(), 1):
            for pat in secret_patterns:
                if pat.search(line):
                    key = (str(p), line_no, line.strip())
                    if key not in seen:
                        seen.add(key)
                        findings.append(f"{p}:{line_no}: {line.strip()}")
    return findings


def validate_secrets(root: Path | str = ".") -> tuple[bool, list[str]]:
    """Validate that no secrets are hardcoded in source and `.env`/env is configured.

    Returns (ok, findings). Missing `.env` or missing `EXO_API_KEY` is reported as a finding.
    """
    root = Path(root)
    findings = scan_source_for_secrets(root)
    env_file = root / ".env"
    if not env_file.exists() and not os.environ.get("EXO_API_KEY"):
        findings.append("missing .env and EXO_API_KEY is not set in environment")
    return (len(findings) == 0), findings


def audit_openhands_events(events: list) -> list[str]:
    """Audit OpenHands action events for dangerous terminal commands."""
    violations = []
    for event in events:
        if type(event).__name__ != "ActionEvent":
            continue
        if getattr(event, "tool_name", None) != "terminal":
            continue
        action = getattr(event, "action", None)
        if action is None:
            continue
        command = getattr(action, "command", None)
        if not command:
            continue
        dangerous, reason = is_dangerous_command(command)
        if dangerous:
            violations.append(f"terminal command blocked: {command} ({reason})")
    return violations


def create_mock_action_event(tool_name: str, command: str | None = None):
    """Utility for tests: build a minimal mock OpenHands ActionEvent."""
    action = SimpleNamespace(command=command) if command else None
    ActionEvent = type("ActionEvent", (SimpleNamespace,), {})
    return ActionEvent(tool_name=tool_name, action=action)
