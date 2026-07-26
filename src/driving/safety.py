"""Safety validation: secrets and command filtering (M5.5)."""
from __future__ import annotations

import os
import re
import shlex
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
    "true", "false", "test", "expr", "bc", "python-config",
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


_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S")

# Shell control keywords that should be skipped when extracting command tokens.
_SHELL_KEYWORDS = frozenset({
    "if", "then", "else", "elif", "fi", "for", "do", "done", "while",
    "until", "case", "esac", "in", "!", "{", "}", "[", "]",
})


def _extract_command_tokens(cmd: str) -> list[str]:
    """Extract actual command names from a (possibly compound) shell command.

    Handles:
    - Variable assignments as prefixes (f=/path; actual_cmd ...)
    - Compound commands joined by ; && || |
    - Shell quoting (single/double quotes) — operators inside quotes are NOT
      treated as shell operators. This is critical for ``python -c "import os;
      assert os.path.isfile('/x')"`` where the ``;`` and ``assert`` are inside
      the python script, not shell operators. (M156.14)

    Returns list of base command tokens (basename, no path) to validate.
    """
    if not cmd or not cmd.strip():
        return []
    # 用 shlex 解析：punctuation_chars 让 ; & | 作为独立 token 出现，
    # 但仅在引号外生效——引号内的 ; & | 被当成字符串字面量。
    # posix=True 启用 POSIX 引用语义（'...' 字面量、"..." 允许 \" 转义）。
    # whitespace_split=True 让普通空白作为分隔符。
    try:
        lexer = shlex.shlex(cmd, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        toks = list(lexer)
    except ValueError:
        # 引号不匹配等解析失败：保守退化到旧朴素切分（仍能拦未知命令，
        # 只是会误拦引号内带 ; 的合法命令——比直接放行安全）。
        return _extract_command_tokens_legacy(cmd)

    # 按操作符切 segment；每个 segment 取首个非赋值、非关键字 token 作为命令。
    tokens: list[str] = []
    seg_words: list[str] = []
    for tok in toks:
        if tok in (";", "&", "&&", "|", "||"):
            tokens.extend(_first_cmd_of_segment(seg_words))
            seg_words = []
            continue
        seg_words.append(tok)
    tokens.extend(_first_cmd_of_segment(seg_words))
    return tokens


def _first_cmd_of_segment(words: list[str]) -> list[str]:
    """从一个 segment 的 token 列表里取首个真正的命令 base name。

    跳过前缀变量赋值（f=value）和 shell 控制关键字（then/do/...）。
    返回空列表表示该 segment 没有命令（纯赋值或纯关键字）。
    """
    if not words:
        return []
    i = 0
    while i < len(words) and _ASSIGN_RE.match(words[i]):
        i += 1
    if i >= len(words):
        return []
    cmd_tok = words[i]
    if cmd_tok in _SHELL_KEYWORDS:
        for w in words[i + 1:]:
            if w not in _SHELL_KEYWORDS:
                cmd_tok = w
                break
        else:
            return []
    return [cmd_tok.split("/")[-1]]


def _extract_command_tokens_legacy(cmd: str) -> list[str]:
    """旧版（朴素正则切分）作为 shlex 解析失败时的退化路径。

    不识别引号——会误把 ``python -c "import os; assert ..."`` 切错。
    仅在 shlex 抛 ValueError（引号不匹配等）时使用，确保保守拒绝。
    """
    parts = re.split(r"\s*(?:;|&&|\|\||\|)\s*", cmd)
    tokens: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Strip leading variable assignments: f=value, PATH=$PATH:...
        # \s* (not \s+) so assignment-at-end-of-string (no trailing space) is consumed
        while _ASSIGN_RE.match(part):
            new_part = re.sub(r"^[A-Za-z_][A-Za-z0-9_]*=\S+\s*", "", part, count=1).strip()
            if new_part == part:
                # No progress made — avoid infinite loop
                break
            part = new_part
        if not part:
            continue
        words = part.split()
        if not words:
            continue
        base = words[0].split("/")[-1]
        if base in _SHELL_KEYWORDS:
            # Take next word if first is a keyword (e.g. "then grep ...")
            for w in words[1:]:
                bw = w.split("/")[-1]
                if bw not in _SHELL_KEYWORDS:
                    tokens.append(bw)
                    break
            continue
        tokens.append(base)
    return tokens


def is_safe_command(command: str) -> tuple[bool, str]:
    """Return (ok, reason) for a shell command.

    Handles compound commands (``f=/path; test -f "$f" && grep ...``) by
    splitting on shell operators and checking each sub-command's actual
    command name after stripping variable assignments.

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
    tokens = _extract_command_tokens(cmd)
    if not tokens:
        # Only assignments / empty — safe
        return True, ""
    for base in tokens:
        if base not in SAFE_BASE_COMMANDS:
            return False, f"command not in whitelist: {base}"
    return True, ""


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
