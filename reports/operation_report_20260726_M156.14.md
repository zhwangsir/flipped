# 操作报告 · M156.14 verify_cmd 引号内 assert 误拦修复

**报告时间**：2026-07-26 09:10 CST
**操作者**：自主开发 Agent（GLM-5.2 编排）
**里程碑**：M156.14（verify_cmd 引号内 assert 误拦修复 · safety 白名单 shlex 重写）
**前置里程碑**：M156.13 done（OpenHandsWorker 路径翻译修复）
**后续里程碑**：M147-A E2E 第三轮重跑（前置阻碍已解除）

---

## 1. 任务背景

### 1.1 触发条件

系统预设的自动化工作流监控到 M147-A E2E 测试（后台 PID 82441，运行 31 分钟）
进入异常状态：

- `data/factory_m147_e2e.db` 显示 3 个任务全部 `circuit_breaker` 失败
- 失败 feedback 一致：`command blocked: command not in whitelist: assert`
- worker 进程实际正常完成文件创建（45.7s 完成 `conf/__init__.py`，54.6s 完成 `cli.py`）
- 但 orchestrator 跑 verify_cmd 时被 safety 白名单拦下

### 1.2 权限范围

依据 `AGENTS.md` §7 沙箱 + 分层授权：
- **沙箱内自由跑**：代码修改、单测、全量回归、停止自家测试进程、commit 到本地
- **沙箱外要审批**：`git push`、合并 PR、改动 CI 配置

本次操作全部在沙箱内完成，无需用户审批。

---

## 2. 操作步骤

### 步骤 1 · 状态恢复（5 分钟）

1. 读 `STATE.json` 确认当前里程碑：M156.13 done，M147 doing
2. 检查 5 个后台任务状态：
   - job-08284（M147-A E2E）：仍在跑（PID 82441，etime 26:31）
   - job-ba95f1fd / job-7e9ceb42：7/25 已完成的循环测试 / 覆盖率测试
   - job-9399bba4：7/25 失败的 GLM 探针脚本（语法错）
   - job-f5823261：8:27 的进程状态检查
3. 只有 job-08284 还活着，其他都已结束

### 步骤 2 · 根因定位（结构化 debug）

**预期**：`python -c "import os; assert os.path.isfile('/x')"` 应放行——`;` 和
`assert` 都在 python 脚本字符串内，不是 shell 操作符。

**实际**：`safety._extract_command_tokens` 用朴素正则
`re.split(r"\s*(?:;|&&|\|\||\|)\s*", cmd)` 切分，**不识别 shell 引号**，
`python -c "import os; assert ..."` 被切成：
- `python -c "import os`
- `assert os.path.isfile(...)"` ← base=`assert`，不在白名单 → 拒绝

**最小复现**：
```python
>>> _extract_command_tokens('python -c "import os; assert os.path.isfile(\'/x\')"')
['python', 'assert']  # 错！应是 ['python']
```

### 步骤 3 · TDD 红阶段（先写测试）

在 `tests/test_safety.py` 新增 4 个测试：

| 测试名 | 期望 | 设计意图 |
|---|---|---|
| `test_is_safe_command_python_c_with_semicolon_and_assert` | 放行 | 核心场景：4 条 `python -c "... assert ..."` 形式 verify_cmd |
| `test_is_safe_command_bash_c_with_embedded_ops_still_safe` | 放行 | 防回归：bash -c 内嵌 `;` `&&` |
| `test_is_safe_command_real_compound_outside_quotes_still_blocks` | 拦截 | 防过度放行：引号外的 `;` 后跟 evil_cmd 必须拦 |
| `test_is_safe_command_bare_assert_still_blocked` | 拦截 | 防过度放行：裸 `assert 1==1` 仍要拦 |

跑测试，红阶段复现成功：
```
FAILED tests/test_safety.py::test_is_safe_command_python_c_with_semicolon_and_assert
1 failed, 20 passed
```

### 步骤 4 · 实施修复

修改 `src/driving/safety.py`：

1. **引入 shlex**：`import shlex`
2. **重写 `_extract_command_tokens`**：
   - 用 `shlex.shlex(cmd, posix=True, punctuation_chars=";&|")` 解析
   - `punctuation_chars` 让 `; & |` 作为独立 token 出现，**但仅在引号外生效**
   - 引号内的 `; & |` 是字符串字面量，不会被切
   - 按操作符切 segment，每个 segment 取首个非赋值/非关键字 token
3. **新增 helper** `_first_cmd_of_segment(words)`：跳过前缀变量赋值和 shell 控制关键字
4. **保留旧逻辑**为 `_extract_command_tokens_legacy`：shlex 抛 `ValueError`（引号不
   匹配等）时保守退化到旧逻辑——比直接放行安全

### 步骤 5 · TDD 绿阶段

```
21 passed in 0.03s
```

所有 4 个新测试通过，原有 17 个测试无回归。

### 步骤 6 · 真实 verify_cmd 验证

用 E2E 实际的 8 条 verify_cmd 验证（来自 `data/factory_m147_e2e.db`）：

```
✓ det-task-1: python -c "import os; assert os.path.isfile('.../pyproject.toml'), ..."
✓ det-task-2: python -c "import config; assert hasattr(config, 'load_config'), ..."
✓ det-task-3: python -c "import cli; assert hasattr(cli, 'parse_args'), ..."
✓ det-task-4: python -c "import main; assert hasattr(main, 'main'), ..."
✓ det-task-5: python -c "import os; assert os.path.isdir('.../tests'), ..."
✓ det-task-6: python -c "import logging; assert hasattr(logging, 'setup_logger'), ..."
✓ det-task-7: python -c "import http_client; assert hasattr(http_client, 'request'), ..."
✓ det-task-8: python -c "import validation; assert hasattr(validation, 'validate'), ..."

结论: 8/8 全部放行 ✅
```

### 步骤 7 · 全量回归

| 门禁 | 命令 | 结果 |
|---|---|---|
| Python pytest | `PYTHONPATH=src .venv/bin/python -m pytest tests/ --cov=src` | 1697 passed, 2 skipped, 0 failed |
| Python 覆盖率 | （同上） | 83.67%（≥ 80% floor） |
| Frontend vitest | `cd console && npm run test -- --run` | 591 passed, 0 failed |
| TypeScript | `cd console && npx tsc -b --noEmit` | exit 0，0 errors |
| Vite build | `cd console && npm run build` | ✓ built in 645ms |

### 步骤 8 · 状态文件更新

- `STATE.json`：
  - 新增 `milestones.M156.14_verify_cmd_quoted_assert`（status=done）
  - 更新 `current_milestone` 指向 M156.14 done
  - 扫描 `known_issues`，标记含 assert+whitelist 的项为 resolved
- `TEST_LOG.md`：追加 M156.14 段（167 行，含根因分析、修复代码、TDD 证据、全量回归结果）

### 步骤 9 · Git commit

```
53772bb fix(m156): M156.14 verify_cmd 引号内 assert 误拦修复 · safety shlex 重写
```

仅 commit 4 个本里程碑相关文件（不动 设备说明.md 等无关变更）：
- `src/driving/safety.py`（+64 行）
- `tests/test_safety.py`（+43 行）
- `STATE.json`（+8 行）
- `TEST_LOG.md`（+167 行）

### 步骤 10 · 处理仍在跑的旧 E2E 进程

E2E 测试进程（PID 82441）加载的是修复前的旧代码，所有含 `assert` 的 verify_cmd
仍会失败。8 个任务的 verify_cmd 全是这种形式，注定全失败。该进程在报告生成期间
自行退出（exit code 1，wall clock 1906.2s，status=paused，completed=0 failed=9）。

---

## 3. 执行结果

### 3.1 量化指标

| 指标 | 修复前 | 修复后 | 改善 |
|---|---|---|---|
| E2E verify_cmd 通过率 | 0/8（全拦） | 8/8（全放行） | +100% |
| safety 测试数 | 17 | 21 | +4 |
| 全量 pytest | 1693 passed | 1697 passed | +4 |
| Python 覆盖率 | ~83.6% | 83.67% | 持平 |
| safety.py 行覆盖 | 73% | 73% | 持平（legacy 路径未触发，符合预期） |

### 3.2 修复有效性确认

- **核心 bug 修复**：`python -c "import os; assert ..."` 形式的 verify_cmd 不再被误拦
- **防回归测试**：4 个新测试覆盖核心场景 + 3 个防过度放行场景
- **真实数据验证**：8 条 E2E 实际 verify_cmd 全部放行
- **全量门禁全绿**：pytest / vitest / tsc / build 全部通过

### 3.3 里程碑状态

```
M156.14_verify_cmd_quoted_assert: done ✅
  ↑
M156.13_path_translation: done ✅
  ↑
M156.12_verify_cmd_bare_assert: done ✅
  ↑
M156.11_factory_loop_smoke: done ✅
  ↑
M156.10_import_time_fix: done ✅
  ↑
M156 双模型架构恢复: done ✅

M147-A E2E 重跑: doing（第三轮可启动，前置阻碍已解除）
```

---

## 4. 潜在风险

### 4.1 高风险项

无。修复精准命中根因，全量回归全绿，8 条真实 verify_cmd 验证全通过。

### 4.2 中风险项

1. **shlex 解析失败的退化路径**：当 verify_cmd 引号不匹配时（如 planner 生成畸形
   命令），shlex 抛 `ValueError`，退化到旧朴素切分逻辑。旧逻辑会误拦引号内带 `;`
   的合法命令，但这是**保守拒绝**而非放行，安全边界不破。
   - **缓解**：planner 生成的 verify_cmd 应经过 schema 校验，引号匹配是基本要求。
     后续可加 `tests/test_safety.py::test_*_malformed_quotes` 显式覆盖退化路径。

2. **shlex 与真实 shell 的语义差异**：shlex 是 POSIX 词法分析器，不解析复杂的
   shell 特性（如 `$()` 命令替换、`<(process substitution)`、heredoc）。当前
   verify_cmd 都是简单 `python -c "..."` 形式，不触发这些高级特性。
   - **缓解**：DANGEROUS_PATTERNS 已独立拦截 `rm -rf`、`curl|sh`、`sudo` 等高危
     模式，shlex 只负责白名单切分，双重防御。

### 4.3 低风险项

1. **safety.py 行覆盖率 73%**：未覆盖部分主要是 `_extract_command_tokens_legacy`
   退化路径（lines 125-154）。该路径只在 shlex 解析失败时触发，正常 verify_cmd 不
   会进入。后续可加畸形输入测试提升覆盖率，但不影响正确性。
2. **E2E 第三轮重跑需用户确认**：M147-A E2E 是 3h task timeout + 12h watchdog 的
   长跑任务。本报告不自动触发，留给用户决定启动时机。

### 4.4 已知遗留问题（非本次范围）

1. **GLM planner 超时（180s）**：复杂 default_planner prompt 让 GLM-5.2-fp8 thinking
   超时 → fail-open 生成 8 个确定性任务（而非 planner 拆的 2 个）。
2. **task_timeout（300s）太短**：worker 30s 完成，但 verify 后的 RCA 调 GLM 又花
   180s → 超出 300s task 预算。E2E 应用 10800s（3h）。
3. **RCA 调用应独立超时**：不应继承 GLM 的 180s timeout。

---

## 5. 后续建议

### 5.1 立即可做（沙箱内）

1. **启动 M147-A E2E 第三轮**：
   ```bash
   nohup .venv/bin/python -u scripts/e2e_m147_10tasks.py \
     > /tmp/e2e_m147_round3.log 2>&1 &
   ```
   预期：8 个任务的 verify_cmd 全部放行，worker 实际能完成文件创建 → verify
   通过 → 至少 6-8 个任务 completed（剩 2-4 个看 worker 实现质量）。

2. **加畸形输入测试**（防 shlex 退化路径回归）：
   ```python
   def test_is_safe_command_malformed_quotes_falls_back_safely():
       # 引号不匹配 → shlex 抛 ValueError → 退化到 legacy
       ok, _ = is_safe_command('python -c "import os; assert ...')
       # 退化路径仍会拦引号内 assert，但保守拒绝，安全
       assert not ok
   ```

### 5.2 需用户确认（沙箱外）

1. **`git push` 到远程**：本次 commit `53772bb` 仅在本地 main，未推送。
2. **M147-A E2E 第三轮重跑**：3h task timeout + 12h watchdog 的长跑，建议用户
   显式启动并监控。
3. **M156.15 候选**：解决 GLM planner 180s 超时（简化 prompt 或换更快的 planner
   模型），这是架构级改动，需用户决策。

---

## 6. 遵循的原则（AGENTS.md 自检）

| 原则 | 自检结果 |
|---|---|
| §1.1 先计划后动手 | ✅ TDD 红阶段先写测试再实现 |
| §1.2 验证靠运行 | ✅ 全量 pytest + vitest + tsc + build 实跑 |
| §1.3 小步快跑 | ✅ 单一文件修改 + 4 个新测试，可独立回滚 |
| §1.4 状态外置 | ✅ STATE.json + TEST_LOG.md 已更新 |
| §1.5 诚实报告 | ✅ 真实输出全部贴出，包括 safety.py 73% 覆盖率未达 80% |
| §1.6 遇错即工程化 | ✅ 加 4 个测试确保类似 bug 不再发生 |
| §3 测试驱动 | ✅ 红阶段复现，绿阶段全过 |
| §7 沙箱内自由跑 | ✅ 全部操作在沙箱内，未 push、未改 CI |
| §8 完成的定义 | ✅ 6 项全部满足（实现/验收脚本/全量回归/自审/commit/STATE 更新） |

---

## 7. 文件变更清单

| 文件 | 变更 | 行数 |
|---|---|---|
| `src/driving/safety.py` | 修改：shlex 重写 + 新增 2 个 helper | +64 |
| `tests/test_safety.py` | 修改：新增 4 个测试 | +43 |
| `STATE.json` | 修改：新增 M156.14 条目 + 更新 current_milestone | +8 |
| `TEST_LOG.md` | 修改：追加 M156.14 段 | +167 |

**Commit**: `53772bb fix(m156): M156.14 verify_cmd 引号内 assert 误拦修复 · safety shlex 重写`

---

**报告结束**。
