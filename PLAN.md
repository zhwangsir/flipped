# M182/M183/M184 · 三里程碑并行施工（Bot Channel / Worker 规则注入 / 限制消化）

> 来源：用户 2026-08-04 指令三连——(1) Bot Channel 多平台接入（Telegram+微信，统一消息接口/
> 身份映射/加密验证/状态监控）；(2) worker 规则注入系统（agent 通路手动 + auto 通路自动，
> 规则规范/版本回滚/效果监控）；(3) 全里程碑 known_limitations 系统性分析消化（42 条，
> 跟踪机制+分阶段方案+报告）。
> M182 同时消化 M181 限制「Bot Channel 未做」；M183 同时消化 M180 限制「agent/auto 的
> worker 规则注入列后续候选」——两条将在 M184 报告中标记 resolved。
> 施工：B182（bot 后端纯逻辑）∥ B183（worker 规则后端+orchestrator 接线）∥ C（两里程碑前端）
> ∥ M184（限制分析+跟踪脚本）。**B 队一律不碰 main.py**（防同文件并发冲突），端点由主代理
> Phase 3 统一接线 + 快照重生 + 全量回归 + verify 脚本 + 门禁 + 留痕。

## 勘察结论（主代理已核查）
- assistant.py `send_assistant_message(session_id, req: SendMessageRequest)`（:397，req.text
  必填）、`_do_decision`（:519）、`get_assistant_history` 均现成——bot 入站消息转发与 M181
  remote 同模式：函数级 import canonical handler，不复刻链路（M178 教训）。
- session.py `SessionStore.create(title, model="coder", mode="agent")`（:84）——bot 会话
  mode="chat"，title=f"bot:{platform}:{user_name or user_id}"。
- orchestrator.py `local_worker`（:826）已有 `_rules_short = project_rules[-300:]`（:852，
  M11.1 教训：prompt 预算 300 字符）——M183 在此前插入 worker 规则合并，总预算仍 300。
  verify 节点（:1568-1646，`verified` 判定在 :1526/:1642）——M183 在判定后挂 stats.record_outcome。
- ContextPanel tabs：diff/term/browser/files/map/rules（:517-533），tab 联合类型 ContextTab
  在 store（setContextTab）；新增 'bot'/'worker' 两 tab，Icons 走 lucide（IconBot/IconWand 新增）。
- requirements.txt 无 pycryptodome/telegram 库——决策：**Telegram 走 raw httpx**（已有依赖，
  Bot API sendMessage + webhook secret_token 头验证，零新增重依赖）；**企业微信回调 AES 用
  pycryptodome**（B182 安装并登记 requirements.txt）。个人微信无官方 bot API，落地企业微信
  （WeCom）应用回调，报告注明该决策。
- 安全惯例：token/secret 全走 env，不进代码/日志；httpx client trust_env=False（内网代理教训）。

## 契约

### M182 · Bot Channel（B182 实现；主代理接线；C 消费）

```python
# B182: src/api/bot_channel.py（纯逻辑，零 FastAPI，函数级不 import main）
#   @dataclass UnifiedMessage: platform, chat_id, user_id, user_name, text, message_id: str
#   @dataclass ChannelStatus: platform, enabled, configured: bool; inbound_count, outbound_count,
#     error_count: int; last_inbound_at, last_outbound_at: float|None; last_error: str
#   class BotSessionRegistry(path)  # 身份映射：platform+chat_id → session_id
#     resolve(platform, chat_id) -> str|None；bind(platform, chat_id, session_id, user_name="")
#     JSON dict 持久化 tmp+os.replace；坏文件回退空不炸
#   class ChannelStats(path)      # 状态监控：record_inbound/outbound/error(platform, err="")
#     status(platform, configured) -> ChannelStatus；all_statuses(configured: dict) -> list
#   async def handle_inbound(msg, *, registry, stats, create_session, dispatch, await_reply,
#       send_reply) -> bool
#     # 全注入保纯：create_session(title)->session_id；dispatch(sid,text)->Awaitable（转发
#     # canonical send）；await_reply(sid)->Awaitable[str|None]（轮询 history 等新 assistant
#     # turn，超时 None）；send_reply(text)->Awaitable[tuple[bool,str]]（平台 sender）
#     # 流程：resolve/建会话 bind → record_inbound → dispatch → await_reply → 有回复
#     # send_reply(截 4000)；超时发固定兜底文案；任何异常 record_error 吞掉返回 False
#   async def wait_for_reply(get_history, session_id, baseline_turns, timeout_s, interval_s=1.0)
#     # get_history(sid)->Awaitable[list[dict(role,text)]]；新 assistant turn 出现→其 text
#   # 路径 env：FLIPPED_BOT_DB（默认 data/bot_sessions.json）/ FLIPPED_BOT_STATS_DB
#   # 超时 env：FLIPPED_BOT_REPLY_TIMEOUT_S 默认 90

# B182: src/api/bot_telegram.py
#   def verify_secret(header: str|None, expected: str) -> bool   # hmac.compare_digest
#   def parse_update(body: dict) -> UnifiedMessage|None  # message.text；非文本/无 message→None
#   class TelegramSender(token, *, client=None)  # client=注入 fake httpx.AsyncClient
#     async send_message(chat_id, text) -> tuple[bool, str]  # 截 4000；异常→(False,str) 不上抛
#     # POST https://api.telegram.org/bot{token}/sendMessage；httpx.AsyncClient(timeout=15,
#     # trust_env=False)；HTTP 非 2xx → (False, f"http {code}")
#   def configured() -> bool   # env FLIPPED_BOT_TELEGRAM_TOKEN

# B182: src/api/bot_wecom.py（企业微信应用回调；pycryptodome 缺失→available()=False 优雅降级）
#   class WeComCrypto(token, encoding_aes_key, corp_id)
#     verify_signature(msg_signature, timestamp, nonce, encrypt) -> bool
#       # SHA1("".join(sorted([token, timestamp, nonce, encrypt]))) hexdigest 比对
#     decrypt(encrypt_b64) -> str  # AES-256-CBC key=b64decode(aes_key+"=") iv=key[:16]
#       # 去 PKCS7 → random16+msg_len(4B 网络序)+msg+corpid；corpid 尾缀校验失败→ValueError
#     encrypt(msg) -> str  # 测试与被动回复用
#   def parse_callback_xml(xml_text) -> UnifiedMessage|None  # MsgType=text；chat_id=FromUserName
#   class WeComSender(corp_id, secret, agent_id, *, client=None)  # access_token 缓存提前 200s 刷新
#     async send_message(user_id, text) -> tuple[bool, str]
#   def configured() -> bool  # env 四件：WECOM_TOKEN/AES_KEY/CORP_ID/SECRET（+AGENT_ID 缺省 "0"）

# 主代理 Phase 3 接线（main.py，pydantic 响应模型定义在 main 段内按既有风格）：
#   POST /bot/telegram/webhook：token 未配置 404；secret 头不符 403；parse None→200
#     {"ok":true,"handled":false}；否则 create_task(handle_inbound)→200 {"ok":true,"handled":true}
#   GET  /bot/wecom/callback（URL 验证）：验签 403；PlainTextResponse(decrypt(echostr))
#   POST /bot/wecom/callback：验签 403；decrypt+parse None→"success"；else create_task→"success"
#   GET  /bot/channels → {channels: [ChannelStatusEntry...]}（enabled=env 开关且 configured）
#   POST /bot/channels/{platform}/test {text} → 未知平台 404/未配置 400/无绑定 400/
#     send 失败 502 {ok:false,error}；成功 {ok:true}
#   FLIPPED_BOT=0 → 全部 404
```

```ts
// C 队 M182 消费契约
// types.ts: BotChannelInfo {platform,enabled,configured,inbound_count,outbound_count,
//   error_count,last_inbound_at,last_outbound_at,last_error}
// api.ts: fetchBotChannels() → BotChannelInfo[]；testBotChannel(platform, text) → {ok,error?}
// icons.tsx: IconBot（lucide Bot 线性，对齐既有风格）
// components/BotChannelPanel.tsx（直调 api 不经 store，仿 RulesPanel 范式）：
//   通道卡片：平台名（Telegram/企业微信）+ IconBot + enabled/configured 徽标（绿/灰）+
//   三项计数（入/出/错）+ last_inbound_at 相对时间 + last_error 红字（空不渲染）+
//   「发测试消息」按钮→loading 禁用→结果行（ok 绿「已发送」/error 红）；
//   空态（无通道 configured）引导文案 + env 配置提示；加载失败红字+重试
// ContextPanel.tsx：tab 'bot' 按钮（IconBot）「机器人」+ 条件渲染 <BotChannelPanel/>
```

### M183 · Worker 规则注入系统（B183 实现；主代理接线；C 消费）

```python
# B183: src/driving/worker_rules.py（纯逻辑零 FastAPI；orchestrator 与 main 均 import 它）
#   class WorkerRule(BaseModel): id, text, scope("worker"|"all"), source("manual"|"auto"),
#     enabled: bool=True, priority: int=50(manual)/10(auto) 0..100, created_at: float
#     # id 生成 "wr-"+secrets.token_hex(4) 碰撞重试；text strip 1..500；
#     # 注入防护 blocklist（case-insensitive）："ignore previous instructions"/"忽略之前的指令"/
#     # "忽略以上指令"/"disregard all" → ValidationError
#   class WorkerRuleStore(path)   # env FLIPPED_WORKER_RULES_PATH 默认 data/worker_rules.json
#     JSON {version:int, rules:[...], history:[{version,ts,action,detail,rules:[快照]}]}
#     坏文件→空 store(version 0)；tmp+os.replace 原子写；history cap 20；每次变更 bump version
#     list/add(text,*,scope,source,priority)/update(id,text?,priority?,scope?)/
#     delete(id)->bool/set_enabled(id,enabled)/versions()->list[元信息含 rule_count]/
#     rollback(version)->bool  # 恢复快照，自身亦 bump version action="rollback"
#   def build_worker_rules_text(rules, *, max_chars=300) -> tuple[str, list[str]]
#     # enabled 且 scope∈{worker,all}；priority desc → id asc；逐条 "- {text}"；
#     # 预算尾部整条丢弃+"…(略N条)"；返回 (text, applied_ids)
#   class WorkerRuleStats(path)   # env FLIPPED_WORKER_RULE_STATS_PATH 默认 data/worker_rule_stats.json
#     record_applied(ids)/record_outcome(ids, success: bool)/snapshot()->
#     #   {"stats": {id: {applied,success,failure}}, "total_runs": int}
#   AUTO_RULE_TEMPLATES: list[tuple[pattern_regex, rule_text]]  # ≥6 条常见失败模式→规则模板
#   def generate_auto_rules(failure_texts, existing, *, max_rules=3) -> list[str]
#     # pattern 命中→模板文本；对 existing 文本+本次候选去重；返回候选

# B183: orchestrator.py 接线（钉死两处，fail-open 绝不让编排失败）
#   ① local_worker（:852 `_rules_short` 计算后）：
#     state 增字段 worker_rules_applied: list[str]（OrchestratorState TypedDict 登记）
#     函数级 import WorkerRuleStore/Stats/build_worker_rules_text →
#     _wr_text,_ids = build_worker_rules_text(store.list(), max_chars=300)
#     非空：_rules_short = (_wr_text+"\n"+_rules_short).strip()[:300]；
#     stats.record_applied(_ids)；返回 dict 带 "worker_rules_applied": _ids
#   ② verify 节点 verified 终判处（:1642-1646 区域 + :1526 复合路径）：
#     函数级 import WorkerRuleStats → record_outcome(state.get("worker_rules_applied",[]), verified)
#     语义：applied 按注入次计数，outcome 按 verify 次计数（中间迭代记 failure，
#     规则效果=降低失败迭代数，报告注明）

# 主代理 Phase 3 接线（main.py）：
#   GET    /worker/rules → {version, rules[]}
#   POST   /worker/rules {text, scope?, priority?} → 201 rule；ValidationError→422
#   PUT    /worker/rules/{id} {text?, priority?, scope?} → rule；404
#   DELETE /worker/rules/{id} → {ok:true}；404
#   POST   /worker/rules/{id}/toggle {enabled} → rule；404
#   GET    /worker/rules/versions → {versions:[{version,ts,action,detail,rule_count}]}
#   POST   /worker/rules/rollback {version} → {ok,version}；未知 404
#   POST   /worker/rules/auto-generate {failure_texts?: [...]} → {added:[rule...], candidates:n}
#     # 缺省数据源：函数级 import driving.failure_kb 读最近失败（fail-open→空→added=[]）
#   GET    /worker/rules/stats → WorkerRuleStats.snapshot()
#   FLIPPED_WORKER_RULES=0 → 全部 404
```

```ts
// C 队 M183 消费契约
// types.ts: WorkerRule {id,text,scope,source,enabled,priority,created_at}
//   WorkerRulesInfo {version,rules: WorkerRule[]}
//   WorkerRuleVersion {version,ts,action,detail,rule_count}
//   WorkerRuleStatsData {stats: Record<string,{applied,success,failure}>, total_runs}
// api.ts: fetchWorkerRules/createWorkerRule(text,scope?,priority?)/updateWorkerRule/
//   deleteWorkerRule/toggleWorkerRule/fetchWorkerRuleVersions/rollbackWorkerRules(version)/
//   autoGenerateWorkerRules()/fetchWorkerRuleStats
// icons.tsx: IconWand（lucide Wand2 线性）
// components/WorkerRulesPanel.tsx（直调 api 不经 store）：
//   头部：版本徽标 v{n} +「自动生成」按钮（结果 note「新增 N 条」/「无新候选」）+「版本史」
//   展开区（versions 列表 + 回滚按钮二次确认）；
//   规则行：enabled toggle + text（行内编辑 保存/取消）+ source 徽标（auto 紫/manual 蓝）+
//   priority 徽标 + 删除二次确认；新建表单（text 必填/scope select/priority number）；
//   stats 区：每规则 applied 数 + 成功率条（success/(success+failure)，0 次显示「未应用」）；
//   全部失败红字不收起；loading 骨架
// ContextPanel.tsx：tab 'worker' 按钮（IconWand）「Worker」+ 条件渲染 <WorkerRulesPanel/>
```

### M184 · known_limitations 系统性消化（独立子代理，无 main.py/前端改动）
- scripts/limitations_report.py（stdlib only）子命令：
  - `harvest`：读 STATE.json milestones.*.known_limitations → data/limitations_registry.json；
    id 稳定 `L-{milestone}-{序号}`（按出现序）；已有条目按 (milestone,text) 匹配保留人工字段
    （category/impact/priority/difficulty/status/resolution_note/target）；新增默认
    category="未分类"/priority="P2"/difficulty="中"/status="open"
  - `classify`：内置规则表为「未分类」条目自动填 category/priority/difficulty 建议
    （关键词映射：安全/加密/token→安全；未做/候选/缺口→功能缺口；性能/开销/超时→性能；
    测试/黑盒/覆盖→测试覆盖；取舍/不动/兼容→架构取舍；数据/持久化/恢复→数据一致性）
  - `check`：STATE.json 每条限制都在 registry → 缺失 exit 1（CI 门禁钩子）
  - `set-status <id> <open|in_progress|resolved|wontfix> [--note ...]`：状态更新机制
  - `report`：生成 reports/limitations_analysis_<YYYYMMDD>.md——总览（总数/分类/优先级分布）+
    42 条全量明细表（id/里程碑/分类/影响/优先级/难度/状态/分阶段目标）+ 优先级×难度矩阵 +
    分阶段路线图（P0→当前迭代，P1→下两里程碑，P2→候选池）+ 已消化条目标记
    （M180 worker 注入→resolved by M183；M181 Bot Channel→resolved by M182）+ 跟踪机制说明
- tests/test_m184_limitations.py ≥12 例（harvest 幂等/稳定 id/人工字段保留/新增默认/
  classify 关键词命中/check 缺失退出码/set-status 往返/report 含全部 id 与路线图节）
- 报告定稿由主代理审阅（优先级/难度判断需全局上下文）

## 阶段与验收
- Phase 1（并行四队）：B182 / B183 / C / M184，各跑各的新增测试，不跑全量回归
- Phase 2（主代理）：main.py 接线（M182 五端点 + M183 九端点）+ API 快照重生核对 +
  api-types 重生 + 全量回归（pytest+vitest+tsc+build）
- Phase 3（主代理）：verify_m182.sh（假 LLM+假 Telegram/WeCom HTTP 黑盒）+ verify_m183.sh
  （真编排黑盒验证注入+stats）+ verify_m184.sh（脚本四子命令+check 门禁）+
  quality_gate 门禁 + STATE.json/TEST_LOG.md 留痕 + git commit
- DoD 红线：B 队不动 main.py；orchestrator 接线全 fail-open；bot token 只走 env；
  注入防护 blocklist 必测；全量回归零失败；findings.jsonl 空
