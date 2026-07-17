# M135 · 质量趋势前端可视化（B）→ memory_hierarchy 替换 context_summary（C）

> 用户定方向：先 B 后 C。
> B = 把 `quality_grading` 接到 factory_loop 的 task 完成钩子，数据喂给 FactoryPanel 画趋势。
> C = 用 `memory_hierarchy` 替换简陋的 `context_summary`（150 字符截断），提升长任务上下文质量。

## M135-B · 质量趋势前端可视化

### 数据源映射
- `design` → `design_score(cwd)[0]`（M36 已有，0-100）
- `functionality` → verify 通过=85 / 失败=40（二元映射）
- `code_quality` / `maintainability` / `performance` → 默认 60（缺数据，后续可接 lint/性能测试）

### 实现步骤

#### B.1 FactoryState 加 quality_history 字段
- 新 dataclass `QualityRecord(task_id, timestamp, score: QualityScore)`
- `FactoryState.quality_history: list[QualityRecord]`
- SQLite 迁移：`quality_history_json` 列

#### B.2 task 完成钩子打分
- 位置：`factory_loop.py` L1121 `if result.verified:` 分支内
- 调 `grade_quality(metrics)` → 追加到 `state.quality_history`
- fail-open：打分异常不阻塞

#### B.3 API 暴露趋势
- `GET /factory/{factory_id}/quality-trend`
- 调 `get_quality_trend(history)` → 返回 direction/delta/latest_grade + 完整 history（前端画曲线）
- fail-open：无数据时返回 `{"direction": "insufficient_data"}`

#### B.4 前端 FactoryPanel 展示
- 仿照 `FactoryRcaHistorySection` 加 `FactoryQualityTrendSection`
- 默认折叠，展开时拉取 `/quality-trend`
- 显示：趋势方向 badge（improving/stable/degrading）+ 最新评级 + 历史分数迷你曲线（纯 CSS bar chart，不引第三方库）

#### B.5 测试
- `test_factory_quality_trend.py`：
  - task 完成时 quality_history 被追加
  - grade_quality 异常时 fail-open
  - quality_history 持久化 roundtrip
  - API 返回正确结构（空数据/有数据两种情况）
- 前端 vitest：组件渲染空态/有数据态
- 全量 pytest + vitest 回归

## M135-C · memory_hierarchy 替换 context_summary

### 现状
[factory_loop.py:1136](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/driving/factory_loop.py#L1136)：
```python
state.context_summary += f"\n[{task.id}] {task.description}: done. artifacts={task.artifacts}"
```
然后 L662 `ctx_tail = state.context_summary[-150:]` — **150 字符截断**，长任务丢光上下文。

### 目标
用 `memory_hierarchy` 的分层记忆（short/mid/long term）替换，让 supervisor 能看到：
- 最近 3 个任务的完整摘要
- 关键决策和教训的压缩版
- 项目级长期记忆

### 实现步骤（B 完成后再细化）
- 盘点 `memory_hierarchy` 接口
- 设计迁移路径（保留 context_summary 兼容旧 factory）
- 接入 supervisor prompt 构造

## 技术约束

1. **fail-open**：所有打分/趋势分析异常不阻塞主流程
2. **不引第三方前端库**：曲线用纯 CSS bar chart
3. **兼容旧 factory**：quality_history 为空时前端显示空态，不报错
4. **小步提交**：B.1-B.5 每个阶段独立 commit

## 验收标准（B）

- [ ] task 完成后 quality_history 有新记录
- [ ] API 返回趋势方向和最新评级
- [ ] 前端 FactoryPanel 显示趋势 badge + 迷你曲线
- [ ] 全量 pytest + vitest 零回归
- [ ] TEST_LOG.md 记录证据
