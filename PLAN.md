# M89 · F8 真机长任务验证 — AI 自动化开发工厂能力实证

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
