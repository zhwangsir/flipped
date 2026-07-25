# flipped · 缺陷日志（DEFECT_LOG.md）

> 循环测试过程中发现的所有缺陷流水。格式见 TEST_PLAN.md §5。
> 每条缺陷结构化记录，便于趋势分析与复发检测。

| ID | 轮次 | 级别 | 类型 | 现象 | 根因 | 修复 | 验证 | 状态 | 复发 |
|---|---|---|---|---|---|---|---|---|---|
| D-0001 | R1 | P1 | 回归 | quality_gate.sh L82/84/129/131 + loop_test.sh L85/103/112 共 7 处 `$VAR<全角字符>` 触发 `set -u` 下 `PY_FAILED\xxx: unbound variable`，门禁误判失败（实际 pytest 1639 passed/0 failed/82.85% cov 全绿） | M144-A 节警告过的陷阱复发：bash 在某些 locale 下把 `$IDENT` 后的多字节字符（`）`、`，`）当作变量名一部分 | 7 处统一改 `${VAR}` 显式大括号；新增 `scripts/check_shell_lint.sh` 守卫接入 G0 门禁；同顺手修 await_glm_capstone.sh L21 同类 | `bash scripts/check_shell_lint.sh` 28 文件全绿 | fixed | 0（M144-A 警告过 → 本次为复发，已加自动化守卫根治） |

