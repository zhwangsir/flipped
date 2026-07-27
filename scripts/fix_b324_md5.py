#!/usr/bin/env python3
"""fix_b324_md5.py · 批量修复 bandit B324 误报。

为所有 hashlib.md5(...) / _hashlib.md5(...) 调用添加 usedforsecurity=False 参数，
明确标记为非密码学用途（缓存键/指纹生成）。bandit 检测到该参数自动跳过 B324。

只处理不含 usedforsecurity 的调用，幂等可重复执行。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# 匹配 hashlib.md5( 或 _hashlib.md5( （注意 _hashlib 是 design_context.py 的别名）
PATTERN = re.compile(r'(_?hashlib\.md5)\(')


def fix_content(content: str) -> tuple[str, int]:
    """在 content 中为所有 hashlib.md5(...) 调用添加 usedforsecurity=False。

    返回 (修复后内容, 修复处数)。
    """
    result: list[str] = []
    i = 0
    fixes = 0

    while i < len(content):
        m = PATTERN.search(content, i)
        if not m:
            result.append(content[i:])
            break

        # 追加匹配前的内容 + 函数名 + 左括号
        result.append(content[i:m.start()])
        result.append(m.group(0))  # "hashlib.md5(" 或 "_hashlib.md5("

        # 从左括号后开始，找匹配的右括号（深度计数，处理嵌套）
        depth = 1
        j = m.end()
        args_start = j
        while j < len(content) and depth > 0:
            ch = content[j]
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    break
            # 跳过字符串字面量（避免字符串里的括号干扰计数）
            elif ch in ('"', "'"):
                quote = ch
                j += 1
                while j < len(content) and content[j] != quote:
                    if content[j] == '\\':
                        j += 1  # 跳过转义字符
                    j += 1
            j += 1

        if depth != 0:
            # 括号不匹配，放弃修复这一处
            result.append(content[m.end():])
            i = m.end()
            continue

        args = content[args_start:j]
        # 检查是否已有 usedforsecurity（幂等）
        if 'usedforsecurity' in args:
            result.append(args)
            result.append(')')
        else:
            result.append(args)
            result.append(', usedforsecurity=False')
            result.append(')')
            fixes += 1

        i = j + 1  # 跳过右括号

    return ''.join(result), fixes


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    targets = [
        root / 'src/driving/stuck_detector.py',
        root / 'src/driving/visual_feedback.py',
        root / 'src/driving/visual_regression.py',
        root / 'src/driving/design_context.py',
        root / 'src/driving/knowledge_preflight.py',
        root / 'src/driving/adaptive_loop.py',
        root / 'src/driving/skill_registry.py',
        root / 'src/driving/gold_memory.py',
        root / 'src/driving/failure_kb.py',
    ]

    total_fixes = 0
    for path in targets:
        if not path.exists():
            print(f'  ⚠️ 跳过（不存在）: {path}')
            continue
        original = path.read_text(encoding='utf-8')
        fixed, count = fix_content(original)
        if count > 0:
            path.write_text(fixed, encoding='utf-8')
            print(f'  ✅ {path.relative_to(root)}: {count} 处修复')
            total_fixes += count
        else:
            print(f'  -  {path.relative_to(root)}: 无需修复（已含 usedforsecurity 或无 md5 调用）')

    print(f'\n总计修复: {total_fixes} 处')
    return 0


if __name__ == '__main__':
    sys.exit(main())
