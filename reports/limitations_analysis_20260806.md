# 已知限制系统性分析报告（2026-08-06）

## 1. 总览

**总数：82**

| 分类 | 数量 |
| --- | --- |
| 未分类 | 24 |
| 功能缺口 | 19 |
| 架构取舍 | 19 |
| 安全 | 7 |
| 数据一致性 | 5 |
| 性能 | 4 |
| 测试覆盖 | 3 |
| 外部依赖 | 1 |

| 优先级 | 数量 |
| --- | --- |
| P0 | 5 |
| P1 | 18 |
| P2 | 59 |

| 状态 | 数量 |
| --- | --- |
| open | 51 |
| in_progress | 0 |
| resolved | 31 |
| wontfix | 0 |

## 2. 全量明细

### L-M171-1 · M171

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 数据一致性 | P1 | 中 | resolved | M185+ 候选（按 content_hash 清理残留 chunk） |

> 幂等 id=全文hash+chunk序号：文件改动后 chunk 数变少时尾部旧 chunk 残留（需按 content_hash 清理，后续增强）

影响：文件内容删减后旧 chunk 残留库中，检索可能召回已不存在的代码片段

处置：M189.1 消化：VectorStore 增 get_where/delete_ids 原语，ingest_file upsert 后按 source 过滤删除旧 content_hash 残留 chunk（fail-open）

### L-M171-2 · M171

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 性能 | P2 | 中 | open | 后续里程碑 |

> _git_files 以 repo toplevel 列举再按子目录过滤，超大 repo 有一次性列举开销（本地操作可接受）

影响：超大 monorepo 首次摄入有一次性全量文件列举延迟（本地操作，可接受）

### L-M171-3 · M171

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P2 | 中 | open | 后续里程碑 |

> markdown fenced code block 内行首 # 会被当标题切段（不豁免，留作后续增强）

影响：含 fenced code block 的 markdown 会被误切段，该文件检索粒度变粗

### L-M172-1 · M172

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | 后续里程碑（token 级预算候选） |

> 截断按字符数非 token（CJK/ASCII 等宽对待，max_chars=2400 是保守预算，token 只少不超）

影响：注入预算按字符截断偏保守，实际 token 占用只少不超，无上下文溢出风险

### L-M172-2 · M172

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 测试覆盖 | P2 | 低 | open | 后续里程碑 |

> 黑盒不覆盖接线层真 LLM 路径（system 注入/rag_chunks 证据在单测 mock 层，避免烧模型 flaky）

影响：system 注入/rag_chunks 接线层仅有单测 mock 证据，黑盒回归不覆盖真 LLM 路径

### L-M172-3 · M172

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 性能 | P2 | 中 | open | 后续里程碑（库规模增大后再评估异步化） |

> 注入检索为同步本地 Chroma 查询（毫秒级），未做异步化；若未来库极大可再优化

影响：同步 Chroma 查询当前毫秒级无感；库极大后可能阻塞请求线程

### L-M173-1 · M173

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P1 | 中 | resolved | 后续里程碑（深层变更感知或定时重建候选） |

> stale 判定只扫顶层文件+顶层目录 mtime：深层文件内容编辑不触发重建（重建成本低但全自动重建会在每次对话前扫全树，权衡后留给手动 regenerate 或顶层变动）

影响：深层文件编辑不触发地图重建，chat/plan 可能注入过时的项目结构（需手动 regenerate）

处置：M189.2 消化：_git_fingerprint（HEAD+porcelain 哈希）替代顶层 mtime 判 stale，深层内容/untracked/commit 全感知，非 git 回退 mtime

### L-M173-2 · M173

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | 后续里程碑 |

> 注入固定 max_chars=1600（保守预算，token 只少不超），无请求级调参

影响：地图注入预算固定 1600 字符偏保守，token 只少不超；暂不支持请求级调参

### L-M173-3 · M173

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | 后续里程碑 |

> 目录用途推断为启发式（目录名映射表），未知目录只列子项名不瞎编

影响：未知目录在地图中只有子项名无用途说明（宁缺毋滥不瞎编）

### L-M174-1 · M174

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P1 | 中 | resolved | 后续里程碑（软删除/回收站候选） |

> 编辑重跑不可逆：截断的事件不可恢复（前端编辑态即确认，端点层无二次确认）

影响：误触编辑重跑后，被截断的后续对话事件永久丢失（前端已确认，端点无二次确认）

处置：M190.1：session trash 机制 + POST /edit/undo + 前端截断 banner；撤销=丢弃重跑产物+按原 id 重挂（黑盒驱动契约修正），真歧义（新 user 消息/锚点丢失）409。verify_m190.sh 场景 a/b/c 通过

### L-M174-2 · M174

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | 后续里程碑 |

> agent 模式只回滚到该轮快照=该轮及之后文件改动全撤销；chat/plan 无文件操作纯对话截断

影响：agent 会话编辑重跑会连带撤销该轮及之后的全部文件改动，回滚范围需用户知晓

### L-M174-3 · M174

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | 后续里程碑（对话历史组装候选） |

> chat/plan _run_chat 本身无 LLM 对话历史（单消息无状态），重跑不带前序对话上下文——与现状行为一致，未额外引入历史组装

影响：chat/plan 重跑不带前序对话上下文（单消息无状态语义，与现状一致）

### L-M174-4 · M174

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 测试覆盖 | P2 | 低 | open | 后续里程碑（可用临时 git 仓库补黑盒） |

> 黑盒不覆盖 agent 模式 git restore（证据在单测 mock 层，不碰真实 git 仓库）

影响：agent 模式真实 git restore 路径无黑盒回归保障，仅靠单测 mock

### L-M175-1 · M175

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P1 | 中 | resolved | M185+ 候选（视觉端点验证后接入） |

> 图像附件未纳入（视觉端点未验证，列后续候选）

影响：用户无法 @ 图片等多模态附件（视觉端点未验证）

处置：M192：图像附件全链接入 chat/plan——后端 ImageAttachmentIn 契约/落盘/_run_chat 多模态 parts/vision 路由/attachments 取回端点 + 前端 Composer 上传粘贴预览/历史缩略图；verify_m192.sh 单测 34 例 + 黑盒 20 断言全绿。遗留：exo VL 数据面推理超时，登记 L-M192-1 待集群恢复复验

### L-M175-2 · M175

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | 后续里程碑 |

> 展开是发送时一次性行为（历史 @token 不重放；edit 重跑按新文本重新展开，行为自然正确）

影响：历史消息中的 @token 不回放展开（仅发送时一次性展开，edit 重跑按新文本重新展开）

### L-M175-3 · M175

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | 后续里程碑（限额调参候选） |

> 补全候选上限 8 条、单文件 32KB/总量 64KB/5 文件上限；skipped 状态仅提示不注入

影响：大文件/多文件 @ 引用受限额截断（32KB/64KB/5 文件），skipped 文件不进上下文仅提示

### L-M176-1 · M176

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P1 | 中 | resolved | M185+ 候选（verify_cmd 确定性校验 exit 0=达成） |

> judge 是 LLM 调用非确定性（verify_cmd 确定性校验 exit 0=达成列后续候选）

影响：goal 达成判定为 LLM 非确定性判断，偶发误判无确定性校验兜底

处置：M188.1 消化：CreateGoalRequest.verify_cmd 显式入参（argv 语义安全闸 422）+ _verify_deterministic 确定性优先（沙盒/host 双路径，exit 0=达成，source=verify_cmd），det 不可用 fail-safe 回落 LLM judge

### L-M176-2 · M176

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | 后续里程碑 |

> goal 运行中普通消息/edit/undo 全 409（wrapper 持 RUNNING_TASKS 全周期，与现状一致）

影响：goal 长跑期间会话被独占，普通消息/edit/undo 均被 409 拒绝

### L-M176-3 · M176

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 数据一致性 | P1 | 中 | resolved | 后续里程碑（goal 断点续跑候选） |

> goal loop 不跨进程重启恢复（状态可从事件流重建，循环本身不恢复）

影响：后端重启后进行中的 goal 循环中断不恢复，需人工重新发起（状态可从事件流重建）

处置：M188.2 消化：rebuild_running 从事件流重建循环态（半途轮整轮重跑）+ lifespan goal 恢复优先于 checkpoint/error（不按 status==running 过滤，dispatch 尾段覆写状态不可靠）+ 续跑防重入 409；paused goal 不续跑登记为新限制

### L-M176-4 · M176

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P2 | 中 | resolved | 后续里程碑 |

> objective 不走 M175 @ 展开（@ 引用走普通消息）；max_iterations 硬上限 20

影响：goal objective 不能 @ 文件引用；迭代超 20 轮被硬上限截断

处置：M194.1 消化 @ 展开部分：goal objective 走与 send 同款 expand_file_refs（refs 落用户消息 payload，响应保持原文）；max_iterations 部分此前已有 FLIPPED_GOAL_MAX_ITER env（硬上限 20 既定设计）

### L-M177-1 · M177

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | 后续里程碑 |

> revert 只动 worktree，绝不清 staging area、绝不整仓 reset/checkout

影响：revert 不影响 staging area（安全设计），已暂存改动需用户自行处理

### L-M177-2 · M177

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | 后续里程碑 |

> untracked 回滚=unlink 仅限 ls-files 判定的常规文件；symlink 删链不删目标（天然安全）

影响：symlink 回滚仅删链不删目标（天然安全）；非常规文件不纳入回滚

### L-M177-3 · M177

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | 后续里程碑 |

> 行内确认=ZCode rewind 安全摘要的最小等价（动作文案写清后果），不做二次 modal

影响：回滚确认仅行内文案摘要，无二次 modal 拦截（动作文案已写清后果）

### L-M177-4 · M177

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P1 | 高 | resolved | M187+ 候选 |

> 逐 hunk 接受/拒绝列后续候选（文件树仅变更过滤、AI commit message 已由 M186 消化）

影响：（待评估）

处置：M193：后端 POST /project/revert-hunk 单 hunk patch 反向应用 + 前端 diffHunks 内容指纹分组 + Review 面板 hunk 块接受/拒绝交互。语义决策：接受=无 git 副作用的审查进度标记（前端内存），拒绝=真实工作区反向应用——遵守 L-M177-1 不碰 staging 约束。tests/test_m193_hunk.py 15 例 + verify_m193.sh 黑盒 16 断言全绿

### L-M178-1 · M178

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | 后续里程碑（执行结果回填任务卡候选） |

> mark_run(done) 语义=「派发成功」非「任务执行完成」（执行结果在会话事件流，任务卡可跳转查看）

影响：任务卡状态=派发成功而非执行完成，执行结果需跳转会话事件流查看

### L-M178-2 · M178

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P1 | 中 | resolved | M185+ 候选（cron + PATCH 编辑） |

> cron 表达式、任务编辑（PATCH）、跨进程重启恢复 RUNNING_TASKS 映射列后续候选

影响：调度仅支持 once/interval 无 cron 表达式；任务不可编辑只能删除重建

处置：M187.1/M187.2/M187.3 全消化：cron.py 纯逻辑 5 字段解析（Vixie dom/dow OR，字段跳跃，4 年上限，本地时区语义）+ kind=cron 创建校验 422；PATCH /tasks/{id} 部分更新（白名单+合并校验+调度字段变更重算 next_run_at）；lifespan 恢复会话注册 RUNNING_TASKS 闭合防重入跨重启缺口。verify_m187.sh 黑盒 a-f 验证

### L-M178-3 · M178

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 数据一致性 | P1 | 中 | resolved | 后续里程碑（RUNNING 映射持久化候选） |

> scheduler 单进程内存态（重启后 due 任务按 next_run_at 自然补触发；RUNNING 防重入映射不跨重启）

影响：重启瞬间正在执行的任务失去防重入保护，可能被补触发重复派发

处置：M187.3：_resume_orchestrator 句柄注册 RUNNING_TASKS+done_callback pop（恢复中会话被防重入看见，重复派发缺口闭合）；stale running 无 checkpoint 会话启动时标 error（chat/plan 不再永远假 running）。黑盒 e 项验证

### L-M178-4 · M178

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 测试覆盖 | P2 | 低 | open | 后续里程碑 |

> 黑盒验证 chat 模式通路；agent/auto 模式的 git snapshot 分支由单测覆盖

影响：agent/auto 模式定时任务的 git snapshot 派发分支无黑盒保障，仅单测覆盖

### L-M179-1 · M179

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | 后续里程碑（预算内送新文件头部候选） |

> untracked 文件按契约只送路径+行数（不送内容），LLM 对新文件只能做有限评审——预算与注入防护的既定取舍

影响：新增文件评审深度有限（LLM 只见路径+行数不见内容），预算与注入防护的既定取舍

### L-M179-2 · M179

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P1 | 中 | resolved | M185+ 候选（评审历史持久化） |

> 评审结果不落盘（一次性请求-响应），历史评审持久化列后续候选

影响：评审结果一次性不落盘，刷新/关页后结论丢失无法追溯

处置：M186.1：评审结果持久化——review_store.py（save/list/load，cap 50 删最旧，原子写，id 穿越防护）+ review 端点 fail-open 落盘回传 review_id + GET /project/reviews（轻量列表）/reviews/{id}（完整详情）；前端历史下拉载入回放（historical 标记）。verify_m186.sh 黑盒 b1-b3 验证

### L-M179-3 · M179

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P2 | 中 | resolved | 后续里程碑 |

> 评审模型固定走 coder alias；reviewProject(model?) 已留参数位，前端 UI 暂未暴露模型选择

影响：评审模型固定 coder alias，前端无法切换（API 已留 model 参数位）

处置：M194.4 消化：ContextPanel 评审按钮旁加模型下拉（默认 coder / architect），选择透传 reviewProject(model)，结果区显示本次模型

### L-M179-4 · M179

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P1 | 中 | resolved | M185+ 候选（跳转编辑器对应行） |

> findings 行号仅文本展示，未做点击跳转编辑器对应行（列后续候选）

影响：findings 行号不可点击跳转，用户需手动定位文件行，评审可操作性打折

处置：M186.2：findings 行号点击跳转——openFile(path, line?) + openedFile.line + 文件视图 line-target 高亮 scrollIntoView 居中；ReviewFindingRow line!=null 时整行 button.review-jump。vitest 覆盖有/无 line 双路径

### L-M180-1 · M180

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P1 | 中 | resolved | M183 |

> 注入仅接 chat/plan；agent/auto 的 worker 规则注入列后续候选

影响：agent/auto 通路曾无 worker 规则注入（已由 M183 落地补齐）

处置：M183 消化：worker 规则注入系统落地（agent 通路手动 CRUD + auto 通路自动生成 + 版本回滚 + 执行效果统计）

### L-M180-2 · M180

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | 后续里程碑 |

> files 记录全部命中文件（含被截断丢弃的节），截断注记追加在预算外（可能略超 max_chars）

影响：截断注记追加在预算外，极端情况注入略超 max_chars（注记量级，token 影响极小）

### L-M180-3 · M180

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | 后续里程碑 |

> 内容空白的规则文件视为不命中（满足「空规则零注入」红线）

影响：空白规则文件静默不命中（空规则零注入红线），用户可能困惑为何不生效

### L-M180-4 · M180

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P2 | 中 | resolved | 后续里程碑 |

> Launcher 未加「规则」入口（与「地图」一致，仅从 ContextPanel tab 进入）

影响：规则面板入口较深（仅 ContextPanel tab，Launcher 无入口），发现性差

处置：M194.6 消化：Launcher 镜像「地图」入口加「规则」入口（IconScrollText），点击切 ContextPanel rules tab

### L-M181-1 · M181

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 安全 | P2 | 低 | open | 后续里程碑 |

> 远程面只读会话 + 发消息 + 审批三能力；不暴露文件树/终端/项目写/其他会话（token 绑定单会话）

影响：移动端仅三能力（只读/发消息/审批），桌面端能力不暴露（token 绑定单会话的安全围栏）

### L-M181-2 · M181

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 安全 | P2 | 低 | open | 后续里程碑 |

> token 单活制：同 session 重复签发旧 token 即失效；TTL 默认 1800s（FLIPPED_REMOTE_TTL_S）过期即 purge

影响：重复签发使旧手机端立即失效；30 分钟 TTL 过期需重新扫码

### L-M181-3 · M181

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | 后续里程碑 |

> 远程发消息走 canonical handler 缺省行为（不支持请求级 mode/model 覆盖），语义=console 发送

影响：手机端发消息固定 console 语义，不能按请求覆盖 mode/model

### L-M181-4 · M181

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P2 | 中 | open | 后续里程碑（一键局域网模式候选） |

> host=127.0.0.1 时仅 host_note 文案提示，不自动改绑定（需 --host 0.0.0.0 起后端或设 FLIPPED_REMOTE_HOST）

影响：默认 127.0.0.1 绑定下手机扫码不可达，需手动 --host 0.0.0.0 或设 FLIPPED_REMOTE_HOST（仅文案提示）

### L-M181-5 · M181

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P1 | 中 | resolved | M182 |

> Bot Channel（Telegram/微信等外部机器人）未做，依赖外部服务列后续候选

影响：外部机器人接入曾缺失（已由 M182 落地 Telegram+企业微信）

处置：M182 消化：Bot Channel 多平台接入落地（Telegram webhook + 企业微信回调 + 统一消息接口 + 状态监控）

### L-M181-6 · M181

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | 后续里程碑 |

> 移动页为零构建自包含 HTML（非 React），与 console 前端无共享组件

影响：移动页零构建自包含 HTML 与 React 主前端各自演进，样式/组件存在双倍维护面

### L-M182-1 · M182

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> 个人微信无官方 bot API，落地企业微信应用回调；个人微信接入不在路线图

影响：（待评估）

### L-M182-2 · M182

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 性能 | P2 | 中 | open | — |

> 入站回复经轮询 history 实现（FLIPPED_BOT_REPLY_TIMEOUT_S 默认 90s），超时发固定兜底文案；长任务超 90s 仅收兜底文案不阻塞后台执行

影响：（待评估）

### L-M182-3 · M182

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> 一 chat 绑定一会话（mode=chat）；bot 会话不暴露文件树/终端/项目写等 console 能力

影响：（待评估）

### L-M182-4 · M182

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> WeCom 依赖 pycryptodome，缺失时 available()=False 优雅降级（channels configured=false 不炸后端）

影响：（待评估）

### L-M182-5 · M182

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> outbound 走平台主动 send API（Telegram sendMessage/WeCom 应用消息），非 webhook 被动回复

影响：（待评估）

### L-M182-6 · M182

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> 身份映射 platform+chat_id→session_id 单映射，同 chat 多用户共享会话（群聊场景无逐用户隔离）

影响：（待评估）

### L-M183-1 · M183

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 安全 | P0 | 中 | resolved | — |

> 注入仅接 local_worker（agent/auto 通路）；chat 通路不注入 worker 规则（chat 走 M180 项目规则）

影响：（待评估）

处置：M185.1：chat/plan 通路注入 scope=all worker 规则（WORKER_RULES_CHAT_HEADER + build_worker_rules_text scopes 参数化），FLIPPED_WORKER_RULES_CHAT=0 可关，fail-open；payload.worker_rules_injected 标记。verify_m185.sh 黑盒验证

### L-M183-2 · M183

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P1 | 中 | resolved | — |

> auto-generate 缺省数据源 driving.failure_kb 最近失败，fail-open 空→added=[]；模板 ≥6 条固定 regex 模式，非 LLM 生成，未命中模式不产生候选

影响：（待评估）

处置：M190.2：_collect_failure_texts 多源汇聚（failure_kb ∪ 事件流 error）+ generate_auto_rules_llm 兜底（FLIPPED_RULES_LLM 开关，fail-open），响应增 llm_used。verify_m190.sh 场景 d/e/f 通过

### L-M183-3 · M183

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 安全 | P0 | 中 | resolved | — |

> stats 语义：applied 按注入次计数，outcome 按 verify 次计数（中间迭代记 failure）——规则效果=降低失败迭代数，非端到端任务成功率

影响：（待评估）

处置：M185.2：snapshot 派生 success_rate=success/(success+failure)（零 outcome→None）+ semantics 语义注记；前端 successRate 公式修正 + 语义注记渲染。契约快照已更新

### L-M183-4 · M183

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | resolved | — |

> worker 规则与项目规则共享 300 字符预算（worker 规则优先在前，超出尾部整条丢弃），超长规则可能不生效

影响：（待评估）

处置：M194.2 消化：build_worker_rules_text max_chars=None 时读 FLIPPED_WORKER_RULES_MAX_CHARS（默认 300 零行为变化），显式传参优先

### L-M183-5 · M183

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | resolved | — |

> history cap 20 版本，更早版本不可回滚

影响：（待评估）

处置：M194.3 消化：history cap 运行期读 FLIPPED_WORKER_RULES_HISTORY_CAP（默认 20，clamp [1,500]，非法回落 20）

### L-M183-6 · M183

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 安全 | P0 | 中 | resolved | — |

> GET /worker/rules 返回全量插入序（含停用），priority desc 排序职责在前端/注入层（D20 契约）

影响：（待评估）

处置：M185.3：GET /worker/rules 支持 enabled 过滤 + sort=priority（priority desc→id asc，与注入层同序）；缺省契约不变（全量插入序）

### L-M184-1 · M184

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> classify 为关键词启发式（六类映射），命中率依赖限制文本措辞，人工校正为准（不踩人工已分类条目）

影响：（待评估）

### L-M184-2 · M184

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 安全 | P0 | 中 | resolved | — |

> check 只验证「STATE.json 每条限制都在 registry」，不验证 registry 中状态/优先级真实性

影响：（待评估）

处置：M185.4：check 增强 registry 真实性校验——id 格式 ^L-M<n>-<i>$、id 里程碑段==milestone 字段、枚举字段合法（status/priority/difficulty）、resolved/wontfix 必须有 resolution_note、id 唯一性

### L-M184-3 · M184

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> registry 人工字段（priority/difficulty/target/impact）需人工维护，脚本不自动评估

影响：（待评估）

### L-M184-4 · M184

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> 报告按日生成同日覆盖（limitations_analysis_<YYYYMMDD>.md），历史报告无索引机制

影响：（待评估）

### L-M185-1 · M185

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | open | — |

> worker_rules_injected 标记只在事件层（events payload），history turn 不折叠（与 M173 map_injected 同设计），前端对话流不感知注入标记

影响：（待评估）

### L-M185-2 · M185

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P2 | 低 | resolved | — |

> sort/enabled 查询参数仅服务端便捷，前端 WorkerRulesPanel 未接入（仍本地排序全量拉取）

影响：（待评估）

处置：M194.7 消化：WorkerRulesPanel 带 sort/enabled 参数服务端拉取（M185.3 端点），失败回落本地排序；加 enabled 过滤开关

### L-M185-3 · M185

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P2 | 低 | open | — |

> check 增强校验覆盖 id/枚举/注记/唯一性，不验 target 字段指向的里程碑是否真实存在

影响：（待评估）

### L-M185-4 · M185

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 架构取舍 | P2 | 低 | resolved | — |

> chat 通路注入 max_chars=300 与 worker 通路共享预算常量，双通路独立调参需后续

影响：（待评估）

处置：M194.2 消化：chat 通路改读 FLIPPED_CHAT_RULES_MAX_CHARS（缺省回落 worker 值），双通路独立调参就绪

### L-M186-1 · M186

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> 评审历史存应用侧 data/reviews/，换机/清数据即失（非项目 git 资产）

影响：（待评估）

### L-M186-2 · M186

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> findings 跳转依赖 openFile 读文件成功；二进制/超 512KB/读失败静默降级无跳转

影响：（待评估）

### L-M186-3 · M186

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | resolved | — |

> commit message 质量取决于 worker 模型，无人工编辑框（复制后自行修改）

影响：（待评估）

处置：M194.5 消化：commit message 展示改 textarea 可编辑，复制按钮取编辑后文本

### L-M186-4 · M186

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | resolved | — |

> 逐 hunk 接受/拒绝仍遗留（L-M177-4 改窄保留）

影响：（待评估）

处置：M193 已交付逐 hunk 接受/拒绝（同 L-M177-4，重复条目一并关闭）

### L-M187-1 · M187

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> cron 按服务器本地时区解释，跨时区部署需注意（once/interval 仍为 UTC 语义）

影响：（待评估）

### L-M187-2 · M187

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 功能缺口 | P1 | 中 | resolved | — |

> cron 表达式为人类子集（*/n、范围、列表、数字），不支持英文名（JAN/MON）与特殊串（@daily）

影响：（待评估）

处置：M191.3 消化：cron _MONTHS/_DOWS/_MACROS 映射 + _parse 宏展开（@yearly/@annually/@monthly/@weekly/@daily/@midnight/@hourly，其余 @ 串 CronError）+ _parse_field names 参数（MON-FRI/MON,WED/MON/2 全兼容，未知名 CronError 含字段位置）。tests/test_m191_cron_names.py + verify_m191.sh 黑盒验证

### L-M187-3 · M187

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 数据一致性 | P1 | 中 | resolved | — |

> stale running 恢复只在启动时扫一次；运行中进程死亡（kill -9）无 watchdog

影响：（待评估）

处置：M191.4 消化：_STALE_SEEN 两击确认集 + _stale_sweep_once（首击记标记跳过派发竞态窗，次击 try_resume_goal→checkpoint resume→update_status(error)+bus 留痕；paused 不碰）+ _stale_watchdog（FLIPPED_WATCHDOG_SCAN_S 默认 60s）lifespan 并排启动。tests/test_m191_watchdog.py 覆盖两击确认/活句柄不碰

### L-M187-4 · M187

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> 编辑不触及 last_run_at/run_count 历史（历史只增不改）

影响：（待评估）

### L-M188-1 · M188

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 数据一致性 | P1 | 中 | resolved | — |

> paused（审批中）goal 不续跑（走 orchestrator checkpoint 恢复，goal wrapper 循环不重建）

影响：（待评估）

处置：M191.2 消化：has_pending_approval 逆序扫 approval_request/result + rebuild_running pending 守卫 return None + _resume_with_decision 尾段钩子（rebuild 命中 → emit status「goal 审批续跑」+ create_task _goal_loop(start, judge_first=True) 注册 RUNNING_TASKS）；summarize_goal_events paused 态。tests/test_m191_goal_pause_resume.py 覆盖

### L-M188-2 · M188

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> verify_cmd host 路径（chat/plan）在宿主直接执行 subprocess，安全依赖 _verify_cmd_safe 双闸（白名单+危险模式），无沙盒隔离

影响：（待评估）

### L-M188-3 · M188

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> 断点续跑以轮为原子单位：轮内 orchestrator checkpoint 不复用，半途轮整轮重跑

影响：（待评估）

### L-M188-4 · M188

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 安全 | P0 | 中 | resolved | — |

> 续跑重建的 _judge_errors/gap 签名序列从事件流恢复，judge 熔断计数跨重启保留

影响：（待评估）

处置：M191.1 消化：judge emit 增结构化 error=verdict is None（gap 文案不变前端兼容），rebuild_running 重放结构化优先、哨兵兜底旧格式——judge 熔断计数跨重启保留且不再被真实 judge gap 撞串污染。tests/test_m191_judge_error_field.py 覆盖 error 字段往返/哨兵兜底/撞串不误计

### L-M189-1 · M189

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 性能 | P2 | 中 | open | — |

> git 指纹边界：未 ignore 的巨大 untracked 目录会拖慢 git status（用户项目卫生问题，代码注释已说明）；非 git 项目仍回退顶层 mtime，深层编辑不感知（现状保留）

影响：（待评估）

### L-M189-2 · M189

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> chunk 清理为 fail-open：清理异常静默跳过，陈旧数据下次 ingest 再清（不影响检索正确性，因检索按新 hash 命中）

影响：（待评估）

### L-M192-1 · M192

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 外部依赖 | P1 | 低 | open | exo 集群 VL 实例恢复后复跑 scripts/verify_m192.sh + 真实红蓝图问答 |

> exo 集群 Qwen3-VL-4B 实例已放置（控制面 /state 可见 MlxRingInstance），但图像推理数据面 420s 超时无响应；对照 GLM 文本推理 60s 可返回。判定集群侧阻塞，代码侧多模态链路已经假 LLM 黑盒验证。2026-08-06 复验#2：实例曾被卸载，重新放置（POST /instance）后数据面仍 6×120s 超时，排除实例状态腐烂——VL runner 本体问题，需进节点查 runner 日志；GLM 数据面 2.3s 健康

影响：chat/plan 带图消息在真实 exo 端点上暂时得不到视觉模型响应（路由与组装正确，端点不答）

### L-M193-1 · M193

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> hunk 接受状态为会话级内存标记（组件 useState + 内容指纹），刷新页面不保留——内容指纹决定不做持久化

影响：（待评估）

### L-M193-2 · M193

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> 拒绝粒度=unified diff hunk（git 原生分组），hunk 内单行不可独立拒绝

影响：（待评估）

### L-M193-3 · M193

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> staged 新文件/deleted 文件的 hunk 拒绝 422 引导整文件回滚（/dev/null 侧不支持单 hunk 反向应用）

影响：（待评估）

### L-M194-1 · M194

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> goal 展开为启动时一次性行为（与 M175 发送时展开同哲学，续跑不重展开）

影响：（待评估）

### L-M194-2 · M194

| 分类 | 优先级 | 难度 | 状态 | 目标 |
| --- | --- | --- | --- | --- |
| 未分类 | P2 | 中 | open | — |

> 评审模型选项硬编码（coder/architect/默认），未接动态 alias 列表

影响：（待评估）

## 3. 优先级×难度矩阵

| 优先级 \ 难度 | 低 | 中 | 高 |
| --- | --- | --- | --- |
| P0 | — | L-M183-1, L-M183-3, L-M183-6, L-M184-2, L-M188-4 | — |
| P1 | L-M192-1 | L-M171-1, L-M173-1, L-M174-1, L-M175-1, L-M176-1, L-M176-3, L-M178-2, L-M178-3, L-M179-2, L-M179-4, L-M180-1, L-M181-5, L-M183-2, L-M187-2, L-M187-3, L-M188-1 | L-M177-4 |
| P2 | L-M172-1, L-M172-2, L-M173-2, L-M173-3, L-M174-2, L-M174-3, L-M174-4, L-M175-2, L-M175-3, L-M176-2, L-M177-1, L-M177-2, L-M177-3, L-M178-1, L-M178-4, L-M179-1, L-M180-2, L-M180-3, L-M181-1, L-M181-2, L-M181-3, L-M181-6, L-M185-1, L-M185-2, L-M185-3, L-M185-4 | L-M171-2, L-M171-3, L-M172-3, L-M176-4, L-M179-3, L-M180-4, L-M181-4, L-M182-1, L-M182-2, L-M182-3, L-M182-4, L-M182-5, L-M182-6, L-M183-4, L-M183-5, L-M184-1, L-M184-3, L-M184-4, L-M186-1, L-M186-2, L-M186-3, L-M186-4, L-M187-1, L-M187-4, L-M188-2, L-M188-3, L-M189-1, L-M189-2, L-M193-1, L-M193-2, L-M193-3, L-M194-1, L-M194-2 | — |

## 4. 分阶段路线图

### 已消化

- L-M171-1 M189.1 消化：VectorStore 增 get_where/delete_ids 原语，ingest_file upsert 后按 source 过滤删除旧 content_hash 残留 chunk（fail-open）
- L-M173-1 M189.2 消化：_git_fingerprint（HEAD+porcelain 哈希）替代顶层 mtime 判 stale，深层内容/untracked/commit 全感知，非 git 回退 mtime
- L-M174-1 M190.1：session trash 机制 + POST /edit/undo + 前端截断 banner；撤销=丢弃重跑产物+按原 id 重挂（黑盒驱动契约修正），真歧义（新 user 消息/锚点丢失）409。verify_m190.sh 场景 a/b/c 通过
- L-M175-1 M192：图像附件全链接入 chat/plan——后端 ImageAttachmentIn 契约/落盘/_run_chat 多模态 parts/vision 路由/attachments 取回端点 + 前端 Composer 上传粘贴预览/历史缩略图；verify_m192.sh 单测 34 例 + 黑盒 20 断言全绿。遗留：exo VL 数据面推理超时，登记 L-M192-1 待集群恢复复验
- L-M176-1 M188.1 消化：CreateGoalRequest.verify_cmd 显式入参（argv 语义安全闸 422）+ _verify_deterministic 确定性优先（沙盒/host 双路径，exit 0=达成，source=verify_cmd），det 不可用 fail-safe 回落 LLM judge
- L-M176-3 M188.2 消化：rebuild_running 从事件流重建循环态（半途轮整轮重跑）+ lifespan goal 恢复优先于 checkpoint/error（不按 status==running 过滤，dispatch 尾段覆写状态不可靠）+ 续跑防重入 409；paused goal 不续跑登记为新限制
- L-M176-4 M194.1 消化 @ 展开部分：goal objective 走与 send 同款 expand_file_refs（refs 落用户消息 payload，响应保持原文）；max_iterations 部分此前已有 FLIPPED_GOAL_MAX_ITER env（硬上限 20 既定设计）
- L-M177-4 M193：后端 POST /project/revert-hunk 单 hunk patch 反向应用 + 前端 diffHunks 内容指纹分组 + Review 面板 hunk 块接受/拒绝交互。语义决策：接受=无 git 副作用的审查进度标记（前端内存），拒绝=真实工作区反向应用——遵守 L-M177-1 不碰 staging 约束。tests/test_m193_hunk.py 15 例 + verify_m193.sh 黑盒 16 断言全绿
- L-M178-2 M187.1/M187.2/M187.3 全消化：cron.py 纯逻辑 5 字段解析（Vixie dom/dow OR，字段跳跃，4 年上限，本地时区语义）+ kind=cron 创建校验 422；PATCH /tasks/{id} 部分更新（白名单+合并校验+调度字段变更重算 next_run_at）；lifespan 恢复会话注册 RUNNING_TASKS 闭合防重入跨重启缺口。verify_m187.sh 黑盒 a-f 验证
- L-M178-3 M187.3：_resume_orchestrator 句柄注册 RUNNING_TASKS+done_callback pop（恢复中会话被防重入看见，重复派发缺口闭合）；stale running 无 checkpoint 会话启动时标 error（chat/plan 不再永远假 running）。黑盒 e 项验证
- L-M179-2 M186.1：评审结果持久化——review_store.py（save/list/load，cap 50 删最旧，原子写，id 穿越防护）+ review 端点 fail-open 落盘回传 review_id + GET /project/reviews（轻量列表）/reviews/{id}（完整详情）；前端历史下拉载入回放（historical 标记）。verify_m186.sh 黑盒 b1-b3 验证
- L-M179-3 M194.4 消化：ContextPanel 评审按钮旁加模型下拉（默认 coder / architect），选择透传 reviewProject(model)，结果区显示本次模型
- L-M179-4 M186.2：findings 行号点击跳转——openFile(path, line?) + openedFile.line + 文件视图 line-target 高亮 scrollIntoView 居中；ReviewFindingRow line!=null 时整行 button.review-jump。vitest 覆盖有/无 line 双路径
- L-M180-1 M183 消化：worker 规则注入系统落地（agent 通路手动 CRUD + auto 通路自动生成 + 版本回滚 + 执行效果统计）
- L-M180-4 M194.6 消化：Launcher 镜像「地图」入口加「规则」入口（IconScrollText），点击切 ContextPanel rules tab
- L-M181-5 M182 消化：Bot Channel 多平台接入落地（Telegram webhook + 企业微信回调 + 统一消息接口 + 状态监控）
- L-M183-1 M185.1：chat/plan 通路注入 scope=all worker 规则（WORKER_RULES_CHAT_HEADER + build_worker_rules_text scopes 参数化），FLIPPED_WORKER_RULES_CHAT=0 可关，fail-open；payload.worker_rules_injected 标记。verify_m185.sh 黑盒验证
- L-M183-2 M190.2：_collect_failure_texts 多源汇聚（failure_kb ∪ 事件流 error）+ generate_auto_rules_llm 兜底（FLIPPED_RULES_LLM 开关，fail-open），响应增 llm_used。verify_m190.sh 场景 d/e/f 通过
- L-M183-3 M185.2：snapshot 派生 success_rate=success/(success+failure)（零 outcome→None）+ semantics 语义注记；前端 successRate 公式修正 + 语义注记渲染。契约快照已更新
- L-M183-4 M194.2 消化：build_worker_rules_text max_chars=None 时读 FLIPPED_WORKER_RULES_MAX_CHARS（默认 300 零行为变化），显式传参优先
- L-M183-5 M194.3 消化：history cap 运行期读 FLIPPED_WORKER_RULES_HISTORY_CAP（默认 20，clamp [1,500]，非法回落 20）
- L-M183-6 M185.3：GET /worker/rules 支持 enabled 过滤 + sort=priority（priority desc→id asc，与注入层同序）；缺省契约不变（全量插入序）
- L-M184-2 M185.4：check 增强 registry 真实性校验——id 格式 ^L-M<n>-<i>$、id 里程碑段==milestone 字段、枚举字段合法（status/priority/difficulty）、resolved/wontfix 必须有 resolution_note、id 唯一性
- L-M185-2 M194.7 消化：WorkerRulesPanel 带 sort/enabled 参数服务端拉取（M185.3 端点），失败回落本地排序；加 enabled 过滤开关
- L-M185-4 M194.2 消化：chat 通路改读 FLIPPED_CHAT_RULES_MAX_CHARS（缺省回落 worker 值），双通路独立调参就绪
- L-M186-3 M194.5 消化：commit message 展示改 textarea 可编辑，复制按钮取编辑后文本
- L-M186-4 M193 已交付逐 hunk 接受/拒绝（同 L-M177-4，重复条目一并关闭）
- L-M187-2 M191.3 消化：cron _MONTHS/_DOWS/_MACROS 映射 + _parse 宏展开（@yearly/@annually/@monthly/@weekly/@daily/@midnight/@hourly，其余 @ 串 CronError）+ _parse_field names 参数（MON-FRI/MON,WED/MON/2 全兼容，未知名 CronError 含字段位置）。tests/test_m191_cron_names.py + verify_m191.sh 黑盒验证
- L-M187-3 M191.4 消化：_STALE_SEEN 两击确认集 + _stale_sweep_once（首击记标记跳过派发竞态窗，次击 try_resume_goal→checkpoint resume→update_status(error)+bus 留痕；paused 不碰）+ _stale_watchdog（FLIPPED_WATCHDOG_SCAN_S 默认 60s）lifespan 并排启动。tests/test_m191_watchdog.py 覆盖两击确认/活句柄不碰
- L-M188-1 M191.2 消化：has_pending_approval 逆序扫 approval_request/result + rebuild_running pending 守卫 return None + _resume_with_decision 尾段钩子（rebuild 命中 → emit status「goal 审批续跑」+ create_task _goal_loop(start, judge_first=True) 注册 RUNNING_TASKS）；summarize_goal_events paused 态。tests/test_m191_goal_pause_resume.py 覆盖
- L-M188-4 M191.1 消化：judge emit 增结构化 error=verdict is None（gap 文案不变前端兼容），rebuild_running 重放结构化优先、哨兵兜底旧格式——judge 熔断计数跨重启保留且不再被真实 judge gap 撞串污染。tests/test_m191_judge_error_field.py 覆盖 error 字段往返/哨兵兜底/撞串不误计

### 当前迭代 P0

（无）

### 近期 P1

- L-M192-1 exo 集群 Qwen3-VL-4B 实例已放置（控制面 /state 可见 MlxRingInstance），但图像推… → exo 集群 VL 实例恢复后复跑 scripts/verify_m192.sh + 真实红蓝图问答

### 候选池 P2/wontfix

- L-M171-2 _git_files 以 repo toplevel 列举再按子目录过滤，超大 repo 有一次性列举开销（本地操作可接… → 后续里程碑
- L-M171-3 markdown fenced code block 内行首 # 会被当标题切段（不豁免，留作后续增强） → 后续里程碑
- L-M172-1 截断按字符数非 token（CJK/ASCII 等宽对待，max_chars=2400 是保守预算，token 只少不超… → 后续里程碑（token 级预算候选）
- L-M172-2 黑盒不覆盖接线层真 LLM 路径（system 注入/rag_chunks 证据在单测 mock 层，避免烧模型 fla… → 后续里程碑
- L-M172-3 注入检索为同步本地 Chroma 查询（毫秒级），未做异步化；若未来库极大可再优化 → 后续里程碑（库规模增大后再评估异步化）
- L-M173-2 注入固定 max_chars=1600（保守预算，token 只少不超），无请求级调参 → 后续里程碑
- L-M173-3 目录用途推断为启发式（目录名映射表），未知目录只列子项名不瞎编 → 后续里程碑
- L-M174-2 agent 模式只回滚到该轮快照=该轮及之后文件改动全撤销；chat/plan 无文件操作纯对话截断 → 后续里程碑
- L-M174-3 chat/plan _run_chat 本身无 LLM 对话历史（单消息无状态），重跑不带前序对话上下文——与现状行为一… → 后续里程碑（对话历史组装候选）
- L-M174-4 黑盒不覆盖 agent 模式 git restore（证据在单测 mock 层，不碰真实 git 仓库） → 后续里程碑（可用临时 git 仓库补黑盒）
- L-M175-2 展开是发送时一次性行为（历史 @token 不重放；edit 重跑按新文本重新展开，行为自然正确） → 后续里程碑
- L-M175-3 补全候选上限 8 条、单文件 32KB/总量 64KB/5 文件上限；skipped 状态仅提示不注入 → 后续里程碑（限额调参候选）
- L-M176-2 goal 运行中普通消息/edit/undo 全 409（wrapper 持 RUNNING_TASKS 全周期，与现状… → 后续里程碑
- L-M177-1 revert 只动 worktree，绝不清 staging area、绝不整仓 reset/checkout → 后续里程碑
- L-M177-2 untracked 回滚=unlink 仅限 ls-files 判定的常规文件；symlink 删链不删目标（天然安全） → 后续里程碑
- L-M177-3 行内确认=ZCode rewind 安全摘要的最小等价（动作文案写清后果），不做二次 modal → 后续里程碑
- L-M178-1 mark_run(done) 语义=「派发成功」非「任务执行完成」（执行结果在会话事件流，任务卡可跳转查看） → 后续里程碑（执行结果回填任务卡候选）
- L-M178-4 黑盒验证 chat 模式通路；agent/auto 模式的 git snapshot 分支由单测覆盖 → 后续里程碑
- L-M179-1 untracked 文件按契约只送路径+行数（不送内容），LLM 对新文件只能做有限评审——预算与注入防护的既定取舍 → 后续里程碑（预算内送新文件头部候选）
- L-M180-2 files 记录全部命中文件（含被截断丢弃的节），截断注记追加在预算外（可能略超 max_chars） → 后续里程碑
- L-M180-3 内容空白的规则文件视为不命中（满足「空规则零注入」红线） → 后续里程碑
- L-M181-1 远程面只读会话 + 发消息 + 审批三能力；不暴露文件树/终端/项目写/其他会话（token 绑定单会话） → 后续里程碑
- L-M181-2 token 单活制：同 session 重复签发旧 token 即失效；TTL 默认 1800s（FLIPPED_REM… → 后续里程碑
- L-M181-3 远程发消息走 canonical handler 缺省行为（不支持请求级 mode/model 覆盖），语义=conso… → 后续里程碑
- L-M181-4 host=127.0.0.1 时仅 host_note 文案提示，不自动改绑定（需 --host 0.0.0.0 起后端… → 后续里程碑（一键局域网模式候选）
- L-M181-6 移动页为零构建自包含 HTML（非 React），与 console 前端无共享组件 → 后续里程碑
- L-M182-1 个人微信无官方 bot API，落地企业微信应用回调；个人微信接入不在路线图
- L-M182-2 入站回复经轮询 history 实现（FLIPPED_BOT_REPLY_TIMEOUT_S 默认 90s），超时发固定…
- L-M182-3 一 chat 绑定一会话（mode=chat）；bot 会话不暴露文件树/终端/项目写等 console 能力
- L-M182-4 WeCom 依赖 pycryptodome，缺失时 available()=False 优雅降级（channels co…
- L-M182-5 outbound 走平台主动 send API（Telegram sendMessage/WeCom 应用消息），非 w…
- L-M182-6 身份映射 platform+chat_id→session_id 单映射，同 chat 多用户共享会话（群聊场景无逐用户…
- L-M184-1 classify 为关键词启发式（六类映射），命中率依赖限制文本措辞，人工校正为准（不踩人工已分类条目）
- L-M184-3 registry 人工字段（priority/difficulty/target/impact）需人工维护，脚本不自动评…
- L-M184-4 报告按日生成同日覆盖（limitations_analysis_<YYYYMMDD>.md），历史报告无索引机制
- L-M185-1 worker_rules_injected 标记只在事件层（events payload），history turn 不…
- L-M185-3 check 增强校验覆盖 id/枚举/注记/唯一性，不验 target 字段指向的里程碑是否真实存在
- L-M186-1 评审历史存应用侧 data/reviews/，换机/清数据即失（非项目 git 资产）
- L-M186-2 findings 跳转依赖 openFile 读文件成功；二进制/超 512KB/读失败静默降级无跳转
- L-M187-1 cron 按服务器本地时区解释，跨时区部署需注意（once/interval 仍为 UTC 语义）
- L-M187-4 编辑不触及 last_run_at/run_count 历史（历史只增不改）
- L-M188-2 verify_cmd host 路径（chat/plan）在宿主直接执行 subprocess，安全依赖 _verify…
- L-M188-3 断点续跑以轮为原子单位：轮内 orchestrator checkpoint 不复用，半途轮整轮重跑
- L-M189-1 git 指纹边界：未 ignore 的巨大 untracked 目录会拖慢 git status（用户项目卫生问题，代码…
- L-M189-2 chunk 清理为 fail-open：清理异常静默跳过，陈旧数据下次 ingest 再清（不影响检索正确性，因检索按新…
- L-M193-1 hunk 接受状态为会话级内存标记（组件 useState + 内容指纹），刷新页面不保留——内容指纹决定不做持久化
- L-M193-2 拒绝粒度=unified diff hunk（git 原生分组），hunk 内单行不可独立拒绝
- L-M193-3 staged 新文件/deleted 文件的 hunk 拒绝 422 引导整文件回滚（/dev/null 侧不支持单 h…
- L-M194-1 goal 展开为启动时一次性行为（与 M175 发送时展开同哲学，续跑不重展开）
- L-M194-2 评审模型选项硬编码（coder/architect/默认），未接动态 alias 列表

## 5. 跟踪机制说明

- 注册表文件：`data/limitations_registry.json`（version=1，tmp+os.replace 原子写）
- 新增/同步：`python scripts/limitations_report.py harvest`（STATE.json → registry 幂等合并，保留人工字段，源移除置 wontfix）
- 一致性检查：`python scripts/limitations_report.py check`（STATE.json 有而 registry 无 → exit 1 打印缺失清单）
- 状态流转：`python scripts/limitations_report.py set-status <id> <open|in_progress|resolved|wontfix> [--note 处置注记]`
- CI 钩子建议：在 `scripts/quality_gate.sh` 或 CI 流水线中加入 `python scripts/limitations_report.py check`，防止新里程碑的 known_limitations 漏登记
