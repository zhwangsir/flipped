# Skill · verify-quality

> 对标 Claude Code 核心收益项（REFERENCE_CLAUDE_CODE_TRAE_AGENT.md §1.1）。
> 把 `scripts/quality_gate.sh` 从"被动执行的 shell 脚本"升级为"主动验证的 Verification Skill"。
> Agent 收到失败信号后能直接定位修复，而不是读长日志猜。

## Trigger

满足以下任一条件时，**必须**主动调用本 Skill 跑验证：

- 用户说"完成 / done / 搞定 / 收工 / 验收"等完成语义词时
- 里程碑标记 `done` 前（写 STATE.json status=done 之前）
- `git commit` 前（特别是里程碑提交、合并到主干前）
- AGENTS.md §3 强制条款触发时

## Scope

**读**（只读，不修改）：
- `src/` — 后端 Python 源码（被 pytest/coverage 检查）
- `console/src/` — 前端 TypeScript 源码（被 vitest/tsc/build 检查）
- `tests/` — 测试套件（被 pytest/vitest 执行）
- `reports/` — 已有报告（bandit.json / coverage.json / coverage-summary.json）
- `STATE.json` — 当前里程碑状态（决定是否收尾）
- `AGENTS.md` §3 — 测试协议契约

**写**（产出物）：
- `reports/quality_metrics.json` — 本次运行的指标快照（shell_lint / py_coverage / fe_lines_cov / tsc_errors / build_ok 等）
- `reports/findings.jsonl` — 结构化失败信号（每行一个 JSON finding，机器可读，驱动 Repair）
- `TEST_LOG.md` — 追加本次验证证据（命令 + 输出摘要 + 结论）

**调用**：
```bash
bash scripts/quality_gate.sh                # 全量（含全量 pytest + 覆盖率）
bash scripts/quality_gate.sh --quick        # 快速（跳过全量 pytest，跑子集 + 前端 + 类型 + 构建）
bash scripts/quality_gate.sh --no-cov       # 跳过覆盖率（更快，无 coverage 指标）
bash scripts/quality_gate.sh --quick --no-cov  # 最快反馈
```

环境变量（可选）：
- `FLIPPED_PY_COV_FLOOR`（默认 80）— Python 覆盖率下限
- `FLIPPED_FE_COV_FLOOR`（默认 28）— 前端行覆盖率下限
- `FLIPPED_FINDINGS_PATH`（默认 reports/findings.jsonl）— 失败信号输出路径
- `FLIPPED_MAX_VERIFY_LOOPS`（默认 3）— Repair 循环上限，防无限循环

## Criteria

PASS 条件（全部满足才算通过，与 quality_gate.sh 退出码对齐）：

| 门禁 | rule（失败时 emit） | expected | 来源 |
|------|---------------------|----------|------|
| G0 shell lint | `QG_SHELL_LINT_FAILED` | 无 `$VAR<非 ASCII>` 陷阱 | `scripts/check_shell_lint.sh` exit 0 |
| G1 pytest | `QG_PYTEST_FAILED` | pytest exit 0 | `PYTHONPATH=src .venv/bin/python -m pytest` |
| G2 py coverage | `QG_PY_COVERAGE_BELOW_FLOOR` | `py_coverage >= 80%` | `coverage.json` totals.percent_covered |
| G3 vitest | `QG_VITEST_FAILED` | vitest exit 0 | `cd console && npx vitest run` |
| G3 fe coverage | `QG_FE_COVERAGE_BELOW_FLOOR` | `fe_lines_cov >= 28%` | `console/coverage/coverage-summary.json` |
| G4 tsc | `QG_TSC_ERRORS` | `tsc_errors = 0` | `cd console && npx tsc --noEmit` |
| G5 build | `QG_BUILD_FAILED` | `build_ok = 1` | `cd console && npm run build` |

附加 PASS 条件（独立于 quality_gate.sh）：
- `reports/bandit.json` 中 `HIGH` 严重度问题数 = 0（由 `scripts/security_scan.sh` 产出）

一句话：**`quality_gate.sh` exit 0 + bandit HIGH=0**。

## Evidence

每次门禁失败，`scripts/quality_gate.sh` 调用 `scripts/_emit_finding.py` 往 `reports/findings.jsonl` 追加一行 JSON。schema：

```json
{
  "ts":             "2026-07-27T03:04:11.100637+00:00",
  "rule":           "QG_PY_COVERAGE_BELOW_FLOOR",
  "location":       "src/",
  "expected":       ">= 80% (FLIPPED_PY_COV_FLOOR)",
  "actual":         "78.5%",
  "suggested_fix":  "见 coverage.json uncovered lines，补测试到低覆盖模块",
  "retryable":      true
}
```

字段语义：
- `ts` — ISO8601 时间戳（UTC，含时区）
- `rule` — 大写蛇形，白名单 7 个（见 Criteria 表）；未知 rule 会被 `_emit_finding.py` 拒绝
- `location` — 文件路径 / 模块 / 命令（Agent 据此直接定位修复点）
- `expected` — 阈值或期望（Agent 据此知道目标）
- `actual` — 实测值（Agent 据此知道差距）
- `suggested_fix` — 可执行建议（Agent 据此形成修复假设，而非读长日志猜）
- `retryable` — `true` 表示 Agent 重试可能修复（如补测试、修类型）；`false` 表示需人工介入（如缺凭据）

每次运行 `quality_gate.sh` 开头会清空 `reports/findings.jsonl`，保证文件只反映本次运行。

## Repair

收到失败信号后的修复循环（最多 `FLIPPED_MAX_VERIFY_LOOPS` 次，默认 3）：

```
1. 读 reports/findings.jsonl（每行一个 finding）
2. 对每条 finding：
   a. 读 rule + location + expected + actual → 形成修复假设
   b. 按 suggested_fix 改最小范围（不破坏其他代码）
   c. 跑对应门禁验证修复（如 QG_TSC_ERRORS → 只跑 npx tsc --noEmit）
3. 全部 finding 修完 → 重跑 bash scripts/quality_gate.sh 全量验证
4. 通过 → 进入 Exit（PASS 收尾）
5. 未通过 → 读新 findings.jsonl，重复 1-4
6. 达到 FLIPPED_MAX_VERIFY_LOOPS 仍失败 → 进入 Exit（升级人工）
```

修复原则（对齐 AGENTS.md §3 红线）：
- 禁止注释掉测试、禁止把断言改宽松、禁止 `--skip`
- 优先修代码，不修测试（除非测试本身有 bug）
- 每次只改最小范围，改完立即重跑对应门禁
- 同一 finding 修 ≥3 次仍失败 → 触发循环熔断（AGENTS.md §6），停止升级人工

## Exit

三种收尾路径：

### PASS（验证通过）
1. `quality_gate.sh` exit 0 且 `reports/findings.jsonl` 为空
2. 追加证据到 `TEST_LOG.md`（标题 `## M<里程碑号> <里程碑名>`，含命令 + 输出摘要 + 结论）
3. 更新 `STATE.json` 对应里程碑 `status: "done"` + `completed_at` + `note`
4. 可继续 `git commit`（commit message 引用 TEST_LOG 证据）

### FAIL（3 次修复仍失败）
1. 读 `reports/findings.jsonl` 最后一次的 findings
2. 在 `DEFECT_LOG.md` 追加新缺陷条目（编号 D-XXXX，含 rule/location/expected/actual/suggested_fix/已尝试修复/失败原因）
3. 更新 `STATE.json` 对应里程碑 `status: "blocked"` + `note` 写明卡点
4. 向人类报告（对齐 AGENTS.md §6）：当前卡点 / 已尝试什么 / 各自结果 / 建议的 2-3 个下一步选项
5. **禁止**标记 done，**禁止**假装成功

### ERROR（verifier 自身故障）
1. 若 `quality_gate.sh` 自身崩溃（如 `scripts/_emit_finding.py` 缺失、`reports/` 不可写、shell 语法错误）
2. 立即停止，**不要**把 verifier 故障混为代码失败
3. 在 `DEFECT_LOG.md` 记录 verifier 故障（独立条目，标 `verifier-bug`）
4. 向人类报告 verifier 自身需修复（这是基础设施问题，不是代码问题）

---

## 设计依据

- REFERENCE_CLAUDE_CODE_TRAE_AGENT.md §1.1：Verification Loop 打包成 Skill 是 Claude Code 最高优先级借鉴项。Boris Cherny 原话："give Claude a way to verify its work. If Claude has that feedback loop, it will 2-3x the quality of the final result."
- REFERENCE_CLAUDE_CODE_TRAE_AGENT.md §1.2：结构化失败信号 JSON（rule + location + expected + actual + suggested_fix + retryable）把搜索空间压到有限区域，Agent 可形成修复假设、改最小范围、再跑同一检查。
- AGENTS.md §3：测试与验证协议（本 Skill 是其代码级强制手段）。
- AGENTS.md §6：停止条件与熔断（FLIPPED_MAX_VERIFY_LOOPS 默认 3 对齐"同一 bug 修 ≥3 次仍失败"熔断）。
