# M102 · Skill 沉淀系统 — Self-Improving Loop 核心第一步

> Loop Engineering 核心：The swarm that ran your task yesterday should be smarter
> than the one running it today. 每次成功任务都沉淀为可复用 Skill，下次同类任务
> 直接加载而非从零摸索。

## 1. 目标

实现 Skill 沉淀系统：factory 任务通过后自动沉淀为 Skill；新 factory 创建时自动
从 Skill Library 检索最相似的 Skill 并加载，让系统越跑越强。

## 2. Skill 数据模型

```
Skill:
  skill_id: str              # 唯一标识（hash of signature+style）
  product_type: str          # 产品类型（landing_page/timer_app/note_app 等）
  design_style: str          # 设计风格（film_atelier/minimalism/...）
  description: str           # 任务描述（用于语义检索）
  description_vector: list[float]  # 向量嵌入（语义检索）
  verify_cmd: list[str]      # 验证命令（复用经过验证的验收标准）
  design_brief: dict         # 设计简报快照（hex/字体/组件状态等关键参数）
  worker_prompt_hints: list[str]  # worker 提示词增强项（从成功任务中提炼的有效约束）
  constraints: list[str]     # 验证通过的硬规则（从 CONSTRAINTS 风格提炼）
  success_count: int         # 成功次数
  last_used: str             # 最近使用时间
  created_at: str
```

存储：SQLite `skills` 表，`data/skills.db`。

## 3. 核心功能

1. **save_skill(task, state, result)** — 任务通过后自动沉淀 Skill
2. **query_similar_skill(description, design_style)** — 语义检索最相似 Skill
   - 复用 gold_memory 的 embedding + cosine similarity 逻辑
   - 相似度阈值 0.6，取 Top-1
3. **apply_skill_to_state(state, skill)** — 把 Skill 应用到 factory state
   - 注入 design_brief（覆盖/增强默认）
   - 注入 verify_cmd 模式（给 planner 参考）
   - 注入 worker_prompt_hints 到 context_summary
   - 注入 constraints 到 project_rules

## 4. 集成点

- **factory_loop 出口**：`result.verified == True` 时调 `save_skill`
- **factory_loop 入口**：新 factory 创建时（planner 前）调 `query_similar_skill`
  - 命中则 `apply_skill_to_state`，把 Skill 注入 state.design_context 和 state.context_summary
  - 未命中则沿用默认行为（fail-open）

## 5. 验收标准（DoD）

1. `test_skill_registry.py` 全过，覆盖：
   - save + query 语义命中
   - apply_skill 正确注入 state
   - 相似度不足时返回 None
   - embedding 不可用时 fallback 到关键词签名
   - 并发写入安全（WAL + 锁）
   - 空 DB 查询返回 None
2. factory_loop 集成测试：
   - 验证通过后 Skill 被写入
   - 新 factory 创建时自动加载相似 Skill
3. 全量回归测试通过（1016+ tests）
4. STATE.json M102=done
5. git commit

## 6. 实施步骤

1. 写本 PLAN.md ✓
2. 写 test_skill_registry.py（TDD，先红）
3. 实现 src/driving/skill_registry.py
4. 集成到 factory_loop.py（入口+出口）
5. 跑测试 → 修 → 全绿
6. 全量回归测试
7. 更新 TEST_LOG.md + STATE.json
8. git commit

> 用户原话:"当前模型已经加载完成可以正常使用,你现在用这个平台监控两个模型跑一个超长的大型任务看看能否自主完成,一个包含前端后端的完整任务,你只给一个方向然后让这个平台开发一个新产品,从调研到测试全流程中间全部由它自行决策进行,并保持70%以内的上下文长度追求高质量产品,真正实现AI自动化开发工厂的能力"

## 1. 目标

验证 flipped 平台的 AI 自动化开发工厂能力:给一个方向 → 平台自行调研/设计/写码/测试/修复/提交 → 产出完整前后端产品。全程双模型(GLM-5.2 编排 + Kimi-K2.7-Code 执行)自主协作,人类只监控不介入。

## 2. 任务方向(给平台的唯一输入)

> **开发一个本地优先的极简 Markdown 笔记应用 NoteEdge**

要求:
- **前端**: 单页 HTML+CSS+JS。Markdown 编辑器(实时预览)、笔记列表、全文搜索、暗色模式、响应式、Film Atelier 设计风格(克制/物理感/呼吸式动效)
- **后端**: Python FastAPI + SQLite。REST API:创建/读取/更新/删除/列表/搜索笔记
- **测试**: 后端 pytest(覆盖 CRUD + 搜索);前端构建通过
- **调研**: 调研同类产品(Obsidian/Bear/Typora)最佳实践,沉淀到设计决策
- **交付**: 验收通过后沙盒内 git commit

## 3. 验收标准(DoD)

1. 平台自主完成 调研 → 设计 → 前端 → 后端 → 测试 全流程,无人工介入
2. 双模型实际协作:GLM-5.2 当 Supervisor/Overseer,Kimi-K2.7-Code 当 Worker
3. 产物完整:前端 index.html + 后端 main.py + requirements.txt + tests/ + README.md
4. 后端 pytest 全过;前端 design_score ≥ 70
5. 验收通过后沙盒内 git commit(注入安全,F7)
6. 全程上下文使用 ≤ 70%(通过 checkpoint/压缩/外置状态保证)
7. 完整事件流可观测(WS 推送 Supervisor/Worker/Overseer/Verify 每步)

## 4. 执行架构

```
人类(一次性) ─给方向→ orchestration-api(mode=auto)
                            ↓
                     F3 自动探测验证命令
                            ↓
                     F5 仓库记忆 + F6 项目规则
                            ↓
               ┌─ Supervisor(GLM-5.2) 拆子任务 ─┐
               │                                  │
               ↓                                  ↓
          Worker(Kimi)沙盒执行  ←并行→  GLM 语义验证(D19)
               │                                  │
               ↓                                  │
          Overseer(GLM) 监督方向/效率             │
               │                                  │
               ↓                                  │
          确定性 verify(pytest + design-lint + a11y)
               │
               ↓
          循环直到验收 → git commit(F7)
```

## 5. 监控策略(人类侧)

- 启动后端 + Console + OpenHands 沙盒
- 通过 API 创建会话 + mode=auto + 给方向
- 订阅 WS 事件流,记录关键节点到 TEST_LOG.md
- 不介入决策;只在以下情况停止(§6 熔断):
  - 同一 bug 修复 ≥3 次仍失败
  - infra_failure(集群故障)
  - 预算超限
- 上下文管理:每轮 checkpoint,接近窗口 70% 触发压缩

## 6. 阻塞依赖(启动前必须满足)

- [ ] exo 集群 LAUNCH `mlx-community/GLM-5.2-DQ4plus-q8`(Supervisor/Overseer)
- [ ] exo 集群 LAUNCH `mlx-community/Kimi-K2.7-Code-4bit`(Worker)
- [ ] :8000 端口空闲(当前 ComfyUI 占用,需停 ComfyUI 或换端口)
- [ ] SearXNG :8080 运行(调研联网;可选,失败 fail-open)

## 7. 实施步骤

1. 写本 PLAN.md ✓
2. 用户 LAUNCH 两模型 + 释放 :8000
3. `bash scripts/dev_up.sh` 起全栈(OpenHands 沙盒 + 后端 + Console)
4. 验证 /api/v1/health 绿(模型可达)
5. `POST /api/v1/projects` 创建项目 `noteedge`
6. `POST /api/v1/sessions` + `mode=auto` + 方向文本
7. 订阅 WS 事件流,监控全程
8. 验收:产物完整 + 测试通过 + design_score≥70 + git commit
9. 记录到 TEST_LOG.md,更新 STATE.json M89=done

## 8. 风险与缓解

- **模型未 LAUNCH**:阻塞,必须用户先在 exo Web UI LAUNCH
- **:8000 被 ComfyUI 占**:停 ComfyUI 或用 `FLIPPED_OH_PORT=8001` 换端口
- **长任务上下文爆炸**:checkpoint + 压缩 + 外置状态(已实装 M5.2)
- **worker 不遵守设计约束**:auto-fix 35 组确定性修复兜底(M15-M85)
- **集群故障**:infra_failure 优雅暂停 + 恢复(M16-M18)
