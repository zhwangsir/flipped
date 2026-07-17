# M134 · 孤岛模块接入主链路 — repo_map + visual_regression

> 背景：M133 完成 UI/UX 深度修复与全量 E2E 绿。盘点发现 ~10 个模块"建好了没通车"，
> 本里程碑把 ROI 最高的两个接入主链路：**repo_map**（喂给 Supervisor，让 GLM 调度看见项目结构）
> 和 **visual_regression**（叠加进 factory verify，让 UI 任务有视觉校验）。
> 两者接口已存在，属于"接线"而非"新建"，风险低、见效快。

## 当前状态盘点

### 已就位（无需改动）
- `driving/repo_map.py:build_repo_map(root)` — 纯函数，把项目压成 ≤2500 字符结构概览
- `driving/visual_regression.py:make_visual_verifier(threshold)` — 标准 verifier 签名 `(cmd_list, cwd) -> (bool, str)`
- `driving/orchestrator.py:OrchestratorState.repo_map` — TypedDict 字段已声明（L71）
- `driving/orchestrator.py:drive_orchestrated(..., repo_map="")` — 参数已接受（L1349）并写入 state（L1365）
- `driving/orchestrator.py:_build_supervisor_prompt` — 已消费 `state["repo_map"]`（L424-425）
- `tests/test_repo_map.py` / `tests/test_visual_regression.py` — 模块自身测试已绿

### 缺口（本次要补）
1. `factory_loop._run_single_task` 构造 kwargs 时**没传 `repo_map`** → Supervisor 永远拿不到项目结构
2. `factory_loop` 的 verifier 装配（L622-650）只叠加了 design/a11y/parallel，**没叠加 visual_regression**

## 里程碑计划

### M134.1 · repo_map 接入 factory_loop
**改动点**：`src/driving/factory_loop.py` 的 `_run_single_task`（L685-698 kwargs 构造处）

**实现**：
- 在 kwargs 构造前调用 `build_repo_map(Path(state.cwd))`
- 结果传入 `kwargs["repo_map"]`
- 加 try/except fail-open（repo_map 失败不阻塞任务）
- 缓存：同一 factory 内 cwd 不变，避免每个 task 重扫——用 `state` 上的私有属性缓存

**验收**：
- 新增 `tests/test_factory_repo_map_injection.py`
  - mock `build_repo_map` 返回固定串，断言 `drive_orchestrated` 收到的 kwargs 含 `repo_map`
  - `build_repo_map` 抛异常时任务仍能跑（fail-open）
  - 同一 factory 第二次调用时不重复调用 `build_repo_map`（缓存生效）
- 全量 pytest 无回归

### M134.2 · visual_regression 接入 factory_loop verifier
**改动点**：`src/driving/factory_loop.py` 的 verifier 装配段（L622-650 UI 任务分支内）

**实现**：
- 仅在 `_looks_like_ui_task` 分支内追加 `make_visual_verifier()` 组合
- 用 `FLIPPED_USE_VISUAL_REGRESSION=1` 环境变量 opt-in（默认关，避免无 Playwright 的环境噪音）
- 组合顺序：base → design_lint → a11y → design_quality → **visual_regression**（warning 级，不阻断）
- fail-open：import 失败或截图失败均退回原 verifier

**验收**：
- 新增 `tests/test_factory_visual_regression.py`
  - 设置 `FLIPPED_USE_VISUAL_REGRESSION=1` + UI 任务时，断言 verifier 被 visual_regression 包装
  - 未设置环境变量时，verifier 不含 visual_regression
  - import 失败时退回原 verifier（fail-open）
- 全量 pytest 无回归

### M134.3 · 集成验证 + 文档
- 跑一次真实 factory 任务（如"做一个 landing page"），观察：
  - supervisor 首轮 prompt 是否包含"项目结构"段
  - UI 任务 verify 阶段是否触发视觉校验（截图保存到 `data/visual_baseline/`）
- 更新 `TEST_LOG.md`：记录两次接入的测试证据
- 更新 `STATE.json`：M134 标 done
- git commit

## 技术约束

1. **fail-open 原则**：两个接入点都必须 try/except，模块异常不阻塞主流程（与 M103-M107 一致）
2. **opt-in 默认关**：visual_regression 走环境变量开关，避免影响现有 79 个 E2E
3. **不改 orchestrator**：`OrchestratorState` / `drive_orchestrated` 接口已就位，本次只改 factory_loop
4. **小步提交**：M134.1 和 M134.2 各自独立 commit，可独立回滚

## 风险与缓解

| 风险 | 概率 | 缓解 |
|---|---|---|
| repo_map 输出过长污染 prompt | 低 | 模块自身已 cap 在 2500 字符；Supervisor prompt 已有截断 |
| visual_regression 依赖 Playwright 在非 UI 环境报错 | 中 | opt-in 开关 + fail-open 双重保护 |
| 缓存导致跨项目串味 | 低 | 缓存 key 用 `state.cwd`，项目切换自动失效 |
