# M186 · Review 面板增强（评审持久化 + findings 跳转 + 仅变更过滤 + AI commit message）

> 来源：limitations_analysis_20260805.md 近期 P1 —— L-M179-2（评审结果不落盘）、L-M179-4（行号不可跳转）、
> L-M177-4（文件树仅变更过滤 / AI commit message / 逐 hunk 接受拒绝，三项中的前两项）。
> 性质：已登记限制的工程化消化。L-M177-4c（逐 hunk 接受/拒绝）难度高，本轮不做——
> L-M177-4 保持 open，文本改窄为逐 hunk 一项。
> 施工：双代理并行——A=后端（review_store.py + main.py + review.py，pytest TDD）；
> B=前端（store.tsx + ContextPanel.tsx + api.ts，vitest TDD）。无同文件冲突。
> 主代理：契约（本文件）→ verify_m186.sh 黑盒 → 全量回归 → 快照 → 门禁 → 留痕。

## 勘察结论（已核查）

- `POST /project/review`（main.py:518-555）：diff → build_review_prompt → LLM → findings，
  只读不落盘 → L-M179-2。`FLIPPED_AI_REVIEW=0` → 404（既有开关，新端点同遵守）。
- `GET /project/diff`（main.py:405-422）：`{files:[{path,added,removed,lines,untracked?,binary?}]}`。
- 前端 `GitDiffView`（ContextPanel.tsx:240-403）：diff 列表 + AI 评审按钮 + findings 按 path
  分组展示；`ReviewFindingRow`（:221-237）行号 `:N` 纯文本不可点 → L-M179-4。
- store.tsx：`openFile(path)`（:445）→ `openedFile={path,content}` → 文件 tab 只读编辑器
  （ContextPanel.tsx:567-583，每行 `.eln-wrap` 含行号 `ln`）——跳行 = openFile 加 line 参数
  + scrollIntoView/高亮，基建已具备。
- 文件树：`projectFiles` 树 + `FileTreeNode`（ContextPanel.tsx:617）无过滤 → L-M177-4a。
- LLM 通路复用：`resolve_worker_model_config(alias)` + `_llm_chat(base_url, model, system, user)`
  （main.py:533/549 既有调用形状）。
- 落盘位置决策：reviews 是工作产物不是项目资产，放**应用侧** `data/reviews/{project_slug}/`
  （`FLIPPED_REVIEWS_DIR` 覆盖），不写用户项目 git 树（.flipped/ 是规则目录，不塞历史）。
- 前端文件树「仅变更」过滤纯前端即可（gitDiff 已在 store），无需新端点。

## 契约（A/B 两队共同遵守，字段名一字不差）

### M186.1 · 评审结果持久化（消化 L-M179-2）

```python
# 新文件 src/api/review_store.py —— 纯逻辑，零 FastAPI，函数级不 import main
REVIEW_HISTORY_CAP = 50  # 每项目历史上限，超出删最旧
def save_review(reviews_dir: Path, *, project: str, model: str,
                files_reviewed: int, findings: list[dict]) -> dict
    # 写 {dir}/{project}/{ts:%Y%m%dT%H%M%S}_{uuid8}.json；返回完整记录 dict
    # 记录 = {id, ts(iso), project, model, files_reviewed, findings_count, findings}
    # 写后超 cap 删最旧；原子写（tmp+rename，同 worker_rules 惯例）
def list_reviews(reviews_dir: Path, project: str) -> list[dict]
    # ts desc；每项 {id,ts,project,model,files_reviewed,findings_count}（无 findings 全文）
    # 目录不存在 → []；坏文件跳过不炸
def load_review(reviews_dir: Path, project: str, review_id: str) -> dict | None
    # id 非法（含 / 或 ..）→ None；不存在 → None

# main.py
# POST /project/review 成功后 fail-open 落盘（落盘失败不影响响应）；
#   ReviewResponse += review_id: str | None = None
# GET  /project/reviews → ReviewsHistoryResponse{reviews: list[ReviewHistoryEntry]}
#   ReviewHistoryEntry = {id,ts,project,model,files_reviewed,findings_count}
# GET  /project/reviews/{review_id} → ReviewRecord（完整含 findings）；未知 id 404
# 三个端点均遵守 FLIPPED_AI_REVIEW=0 → 404；无活动项目 → 400（review）/ {reviews: []}（列表）
```

```ts
// 前端 store.tsx
reviewHistory: ReviewHistoryEntry[];            // 历史列表（轻量无 findings）
loadReviewHistory: () => Promise<void>;          // 拉列表（失败静默置 []）
openReview: (id: string) => Promise<void>;       // 拉详情 → 填 aiReview.result 形状回放
// aiReview.result 形状不变（AiReviewResult），历史回放视为只读结果；loadGitDiff 仍清 result
```

```tsx
// GitDiffView 头部加「历史」按钮 → 展开历史列表（时间/model/条数），点击 openReview(id)。
// 历史回放时显示「历史评审 · {ts}」标记（与本次评审区分）。
```

### M186.2 · findings 行号跳转（消化 L-M179-4）

```ts
// store.tsx
openFile: (path: string, line?: number) => Promise<void>;
// openedFile: { path: string; content: string; line?: number } | null
// line 可选，缺省 = 现状（不滚动）；失败静默（现状不变）
```

```tsx
// ContextPanel.tsx 文件视图：openedFile.line 存在时
//   → 对应行 .eln-wrap 加高亮 class（如 'line-target'）+ scrollIntoView({block:'center'})
// ReviewFindingRow：finding.line != null 时整行 button 化（review-jump），
//   onClick → openFile(finding.path, finding.line)；line==null 保持纯文本现状。
```

### M186.3 · 文件树「仅变更」过滤（消化 L-M177-4a）

```tsx
// ContextPanel.tsx 文件 tab 头部：「仅变更」toggle（默认关）。
// 开 → 纯函数 filterTreeByPaths(tree, changedPaths:Set<string>)：
//   保留命中文件节点 + 其祖先目录（目录无命中后代则剔除）；空结果 → 提示「无变更文件」。
// gitDiff 已在 store，changedPaths = new Set(gitDiff.map(f=>f.path))。
// toggle 旁计数徽标 = gitDiff.length。
```

### M186.4 · AI commit message（消化 L-M177-4b）

```python
# review.py 追加（纯函数，零 LLM）：
COMMIT_PROMPT_BUDGET = 6_000
COMMIT_SYSTEM_PROMPT = "你是提交信息撰写员，只输出 conventional commit 文本。"
def build_commit_prompt(files: list[dict]) -> str
    # 指令（type(scope): subject ≤72 字符 + 可选 body；只输出文本）+ 逐文件段（同 _file_section）
    # 超预算按文件逆序丢 + 截断注记（同 build_review_prompt 形状）
def parse_commit_reply(text: str) -> str
    # 剥 fence → 首个非空行起至多 20 行拼接；空 → ReviewParseError（复用现异常类）

# main.py
# POST /project/commit_message {model?} → CommitMessageResponse
#   {message: str, model: str, files_count: int, note: str | None}
#   工作区干净 → message="" note="工作区干净"；LLM 失败 502；FLIPPED_AI_REVIEW=0 → 404
```

```tsx
// GitDiffView 头部加「生成 commit」按钮（与 AI 评审并排）→
//   结果展示在 summary 区（可复制按钮 navigator.clipboard.writeText）。
```

## 验收标准（verify_m186.sh 全部实跑）

1. `pytest tests/test_m186_review_persist.py -q` 全绿（A 队 TDD：save/list/load/cap 删旧/
   坏文件跳过/id 穿越防护/build_commit_prompt 预算/parse_commit_reply 边界）。
2. 前端 vitest 全绿（B 队 TDD：openFile 带 line 跳转渲染/ReviewFindingRow 点击/
   filterTreeByPaths/历史列表载入回放/commit 按钮与复制）。
3. 真实后端黑盒（真 uvicorn + 假 OpenAI server）：
   a. POST /project/review → 200 且 data/reviews/{proj}/ 落盘一条；GET /project/reviews 列表含该条
   b. GET /project/reviews/{id} → 完整 findings；未知 id → 404
   c. POST /project/commit_message → 假 LLM 回显文本原样返回；干净工作区 → note
   d. FLIPPED_AI_REVIEW=0 实例三个端点全 404
4. 全量回归：pytest 全绿 + vitest 全绿 + vite build + OpenAPI 快照比对（更新走
   FLIPPED_UPDATE_API_SNAPSHOT=1）+ quality_gate.sh。
5. registry：L-M179-2 / L-M179-4 set-status resolved（含注记）；L-M177-4 文本改窄
   （仅余逐 hunk）保持 open；report 重生；check exit 0。

## 已知限制（施工后登记进 STATE.json）

- 评审历史存应用侧 data/reviews/，换机/清数据即失（非项目 git 资产）。
- findings 跳转依赖 openFile 读文件成功；二进制/超 512KB/读失败静默降级无跳转。
- commit message 质量取决于 worker 模型，无人工编辑框（复制后自行修改）。
- 逐 hunk 接受/拒绝仍遗留（L-M177-4 改窄保留）。
