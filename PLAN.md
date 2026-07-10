# M14 · 双模型并行验证监督架构（D19）

> 用户原话："两个模型需要同时进行使用，一个用来跑代码的时候另外一个用来验证监督"
> 当前架构（serial）：supervisor(GLM) → worker(Kimi) → overseer(GLM) → verify(确定性)
> 新架构：worker 跑代码的**同时**，GLM 并行对产物做语义验证监督（双模型并行使用）

## 1. 设计目标

- **并行使用两个模型**：Kimi 生成代码时，GLM 同时对产物做语义监督（不是事后 overseer 的方向判断，而是对**代码产物本身**的验证）
- **跨模型族验证**：Kimi 产代码 → GLM 验证（避免同模型自偏，呼应 D15）
- **与确定性 verify 并行**：GLM 语义验证 + 确定性 verify_cmd/design-lint/a11y 同时跑，合并结果
- **不破坏现有架构**：作为可选 verifier 注入，默认行为不变

## 2. 架构设计

### 2.1 ParallelVerifier 模块（src/driving/parallel_verifier.py）

```
worker(Kimi 产代码)
       ↓
   ┌───────────────────────────┐
   │  ThreadPoolExecutor 并行   │
   ├───────────┬───────────────┤
   │ GLM 语义  │ 确定性三重校验 │
   │ 验证监督  │ (verify_cmd + │
   │ (读产物)  │  design-lint  │
   │          │  + a11y)       │
   └───────────┴───────────────┘
       ↓ 合并结果
   ok = deterministic_ok AND glm_severity != "blocker"
   msg = 合并两侧发现
```

### 2.2 GLM 语义验证器职责

- 读取 cwd 下产物（index.html 等）
- 让 GLM 评判：设计系统一致性、结构完整性、潜在 bug、a11y hints
- 输出结构化 `SemanticVerdict`：severity(blocker/warning/ok) + issues + rationale
- **blocker 级**才算失败（避免过度挑剔阻断流程）

### 2.3 接入点

`orchestrator.build_orchestrator` 的 `verifier` 参数可换成 `make_parallel_verifier(base_verifier)`。
`factory_loop` 用 `combined_verifier_with_a11y` 时也可包一层 `make_parallel_verifier`。

## 3. 实施步骤

### M14.1 ParallelVerifier 模块
- `src/driving/parallel_verifier.py`：`SemanticVerdict` + `make_glm_semantic_verifier()` + `make_parallel_verifier(base_verifier, glm_alias)`
- 并行执行用 `concurrent.futures.ThreadPoolExecutor`
- GLM 调用复用 `_direct_glm_tool_call` 风格（httpx + trust_env=False + enable_thinking=false）
- 优雅降级：GLM 不可用时 fail-open（只返回确定性结果，不阻塞）

### M14.2 orchestrator 接入
- `build_orchestrator` 默认 verifier 改为 `make_parallel_verifier(_safe_default_verifier)`（可选，环境变量控制）
- 状态字段新增 `parallel_verdict`（可选）

### M14.3 测试覆盖
- `tests/test_parallel_verifier.py`：
  - 注入 fake_llm + fake_base_verifier
  - 测试并行执行（两侧都调用）
  - 测试结果合并（blocker 失败 / warning 通过 / GLM fail-open）
  - 测试超时降级
  - 测试读产物文件

### M14.4 STATE.json 更新 + git commit
- 记录 M14 完成 + D19 决策
- commit message 说明双模型并行架构

## 4. 验收标准（DoD）

1. `python -m pytest tests/test_parallel_verifier.py -v` 全过
2. 全量 `python -m pytest tests/ -q` 不回归（390+ passed）
3. ParallelVerifier 在 GLM 不可用时 fail-open（不阻塞）
4. GLM 与确定性 verifier 真正并行（用 ThreadPoolExecutor）
5. STATE.json + DECISIONS.md 记录 D19
6. git commit

## 5. 风险与缓解

- **GLM 调用慢（240s 超时）**：用 ThreadPoolExecutor，确定性 verifier 先完成不阻塞；GLM 超时 fail-open
- **过度挑剔阻断流程**：只 blocker 级才失败，warning 只记录不阻断
- **prompt 过长触发 reasoning**：复用 compact brief 风格，限制产物读取长度
