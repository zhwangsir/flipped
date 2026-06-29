# 调研：exo 的 OpenAI 兼容工具调用（function calling）

> 日期 2026-06-29 ｜ 源码 + release notes 实证 ｜ 置信：核心结论 high，两个具体 quant 命中 medium（需实测）

## 结论（TL;DR）

exo **当前版本原生支持 OpenAI 兼容工具调用**，返回**结构化 `tool_calls`** 字段 + `finish_reason="tool_calls"`，**不**塞进 `content`（v1.0.64+，2026 初起）。采用**按模型自动分派解析器**架构，**没有** mlx-openai-server 那种 `--tool-call-parser` CLI 开关——解析器按 `model_id` 子串 + tokenizer 属性自动选择，无法手动指定。

- **Kimi-K2**：exo 写死的专用解析器 `_parse_kimi_tool_calls`（`<|tool_calls_section_begin|>` 等 markers）；PR #1413(v1.0.68) 修过 Kimi 自带 tool-id 冲突。
- **GLM**：exo 专用 XML 风格解析（`<arg_key>/<arg_value>`），带独立单测 `test_glm_tool_parsing.py`。
- 另有 gpt-oss(Harmony)、DeepSeek(DSML) 专用路径；其余模型靠 tokenizer 三属性（`tool_call_start/end/tool_parser`）。
- `_coerce_tool_calls_to_schema()` 会按请求 tools 的 JSON schema 对参数做类型矫正（string→int 等），减少格式漂移。

## 对本项目的影响

- **M0.4 命根子大概率能过**：两个目标模型在 exo 里都有专用解析器 → 工具调用应返回结构化 tool_calls。
- **唯一风险 = 版本/命名匹配**：`Kimi-K2.7-Code-4bit` / `GLM-5.2-DQ4plus-q8` 是较新名。exo 按子串匹配（"kimi-k2"/"glm" 大概率命中），但新版本号/文法漂移、特殊 quant 的 chat_template 可能让解析失配 → 落回无解析路径。**以集群恢复后的实测为准**（monitor_cluster.py 会跑）。exo 未暴露版本端点；但目录含 K2.7/GLM-5.2 且用 JACCL+Thunderbolt，应为较新构建。
- **LiteLLM 兜底**：仅当 exo 侧解析失败才需要（LiteLLM 可把文本工具调用退化解析），但其自身有 streaming/tool_calls 已知 bug；**首选确保 exo 解析命中**，LiteLLM 的主价值是统一鉴权/路由/降级。

## 客户端现实（影响 M2 基座 D4）

- 社区实测（exo #1840）：**Cline 对本地模型最稳**；Kilo Code 可用但有 `MODEL_NO_TOOLS_USED` 通病、需手动开"工具能力/Computer Use"开关并对齐 Model ID/context window；Claude Code 对 exo 兼容差（会崩）。
- 编辑器一律选 **OpenAI Compatible** provider，Model ID **从 exo `/v1/models` 原样复制**（大小写/前缀错会匹配不到解析分支）。

## 最小验证标准（集群恢复后执行）

1. 非流式带 `tools` 请求 → `choices[0].message.tool_calls` 非空、`content` 空、`finish_reason="tool_calls"`（K2 与 GLM 各一次）。← `scripts/toolcall_test.py` 已覆盖
2. `"stream": true` → SSE 出现 `delta.tool_calls` 且末 `finish_reason="tool_calls"`（流式独立代码路径，单独验）。
3. 编辑器内"创建/编辑文件"任务真的执行了文件操作。
4. 失败则先升级 exo 复测，再考虑 LiteLLM 兜底；看 exo 日志 `tool call parsing failed` 定位。

## 关键来源

- adapter（结构化输出证据）：`src/exo/api/adapters/chat_completions.py`
- 分派解析器：`src/exo/worker/runner/llm_inference/model_output_parsers.py`、`tool_parsers.py`
- 解析器选择：`src/exo/worker/engines/mlx/builder.py`
- Kimi 专用：`src/exo/worker/engines/mlx/utils_mlx.py` ｜ GLM 单测：`.../test_glm_tool_parsing.py`
- Releases / PR #1413 / Issues #1074 #1100 #1840 ｜ mlx-lm 上游缺陷 #1262 #1096
- 全量 URL 见会话记录 task af38672c39675ffc7。
