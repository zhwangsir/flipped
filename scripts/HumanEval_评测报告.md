# HumanEval

> 评测时间：2026-08-08  
> 评测方法：OpenAI HumanEval 官方基准（164 题 pass@1，temperature=0.0，单次生成）  


---

## 一、执行摘要

### 1.1 结果

| 指标 | 数值 |
|---|---:|
| 数据集 | OpenAI HumanEval（164 题） |
| 生成成功率 | **164 / 164 = 100%** |
| 测试通过 | **132** |
| 测试失败（真实模型能力问题） | 32 |
| **最终 pass@1** | **132 / 164 = 80.49%** |

### 1.2 数据修正过程

| 阶段 | 通过数 | pass@1 | 说明 |
|---|---:|---:|---|
| 初跑 | 124 | 75.61% | 9 个任务因上游超时未生成 |
| 修正提取 bug | 125 | 76.22% | HumanEval/154 修复后通过（+1） |
| 重跑超时任务 | **132** | **80.49%** | 9 个超时任务全部生成成功，7 通过（+7） |

**核心结论**：排除网络因素后，该 K3 API 接口在 HumanEval 官方基准上的**纯模型能力 pass@1 = 80.49%**（132/164）。所有失败均为模型真实能力不足，无任何网络/超时干扰。

---

## 二、与官方数据横向对比

### 2.1 HumanEval pass@1 横向对比表

| 模型 | HumanEval pass@1 | 数据来源 |
|---|---:|---|
| Claude 3.5 Sonnet | ~92.0% | 
| GPT-4o | ~90.2% | OpenAI 官方 |
| **Kimi K2（官方）** | **~85.9%** |
| DeepSeek-V3 | ~82.6% | DeepSeek 官方 |
| **本接口实测** | **80.49%** | 提供接口 ｜
| GPT-4（早期） | ~67.0% | OpenAI 官方 |

### 2.2 关键差距分析

| 对比项 | 差值 | 判定 |
|---|---:|---|
| 实测 vs Kimi K2 官方（85.9%） | **-5.41%** | 低于上一代 K2 |
| 实测 vs Kimi K3 官方宣称定位 | 低于 | K3 为 K2 升级版，官方定位更高 |
| 实测 vs DeepSeek-V3（82.6%） | -2.11% | 略低 |

**判定**：该接口实测 pass@1 = 80.49%，**低于 Kimi K2 官方水平（85.9%）**，与 K3 作为 K2 升级版的官方定位不符。结合此前综合评测中观察到的 63s 硬性超时、长上下文退化等现象，**该接口后端大概率不是满血版 Kimi K3**，可能是限流/降级版本或较小规模的蒸馏变体。

---

## 三、评测方法

### 3.1 HumanEval 官方标准

- 164 个 Python 编程任务，每题含函数签名 + 文档字符串 + 单元测试
- pass@1：每题生成 1 个补全，执行单元测试，通过即计 1 分
- temperature=0.0 贪心解码，保证可复现

### 3.2 排除网络因素的措施

| 措施 | 说明 |
|---|---|
| 多次重试 | 每个任务最多重试 6 次，交替开/关 thinking |
| 加大超时 | 客户端超时 180s → 300s，给足生成时间 |
| 重试间隔 | 每次重试间隔 3s，避免触发限流 |
| 结果验证 | 164/164 全部生成成功，无网络干扰 |

### 3.3 代码提取修复

- 初跑 4 个任务因模型输出未闭合 ` ```python ` 代码块导致提取失败
- 修复提取逻辑（支持未闭合代码块）后重跑
- HumanEval/154 修复后通过，其余 3 个为真实算法错误

---

## 四、32 个真实失败任务明细

以下 32 个任务生成成功但单元测试未通过，**全部为模型真实能力不足**：

### 4.1 边界条件 / 数学逻辑类

| 任务 | 函数 | 问题类型 |
|---|---|---|
| HumanEval/0 | has_close_elements | 边界条件 |
| HumanEval/20 | find_closest_elements | 边界条件 |
| HumanEval/21 | rescale_to_unit | 边界条件 |
| HumanEval/39 | prime_fib | 数学逻辑 |
| HumanEval/47 | median | 数学逻辑 |
| HumanEval/76 | is_simple_power | 数学逻辑 |
| HumanEval/77 | iscube | 数学逻辑 |
| HumanEval/157 | right_angle_triangle | 数学逻辑 |

### 4.2 字符串解析类

| 任务 | 函数 | 问题类型 |
|---|---|---|
| HumanEval/1 | separate_paren_groups | 字符串解析 |
| HumanEval/6 | parse_nested_parens | 字符串解析 |
| HumanEval/17 | parse_music | 字符串解析 |
| HumanEval/91 | is_bored | 字符串解析 |

### 4.3 编码 / 解码类

| 任务 | 函数 | 问题类型 |
|---|---|---|
| HumanEval/38 | decode_cyclic | 编码/解码 |
| HumanEval/50 | decode_shift | 编码/解码 |
| HumanEval/89 | encrypt | 编码/解码 |
| HumanEval/93 | encode | 编码/解码 |

### 4.4 复杂规则 / 算法类

| 任务 | 函数 | 问题类型 |
|---|---|---|
| HumanEval/32 | — | 复杂规则 |
| HumanEval/36 | fizz_buzz | 复杂规则 |
| HumanEval/81 | numerical_letter_grade | 复杂规则 |
| HumanEval/94 | skjkasdkd | 复杂规则 |
| HumanEval/102 | choose_num | 复杂规则 |
| HumanEval/116 | sort_array | 复杂规则 |
| HumanEval/124 | valid_date | 复杂规则 |
| HumanEval/130 | tri | 复杂规则 |
| HumanEval/132 | is_nested | 复杂规则 |
| HumanEval/145 | order_by_points | 复杂规则 |
| HumanEval/147 | get_closest_vowel | 复杂规则 |
| HumanEval/10 | make_palindrome | 算法错误 |
| HumanEval/58 | — | 算法错误 |
| HumanEval/92 | — | 算法错误 |
| HumanEval/129 | minPath | 算法错误 |

### 4.5 指令遵循失败（特殊案例）

| 任务 | 问题 |
|---|---|
| HumanEval/57 | 模型未输出代码，而是输出闲聊内容 "Hi there! How can I help you..."（重试 2 次均如此），指令遵循失败 |

---

## 五、结论

### 5.1 最终判定

| 维度 | 数值 | 评级 |
|---|---|---|
| HumanEval pass@1（纯模型能力） | **80.49%** | 中上 |
| 生成成功率 | 100% | — |
| 真实失败 | 32 / 164（19.5%） | — |

### 5.2 是否为满血 K3

**否。** 依据：
1. pass@1 = 80.49%，低于 Kimi K2 官方 85.9%，而 K3 为 K2 升级版，官方定位更高
2. 存在上游 63s 硬性超时（需多次重试才能生成）
3. HumanEval/57 出现指令遵循失败（输出闲聊而非代码）
4. 此前综合评测显示长上下文能力退化

### 5.3 建议

1. 用 Moonshot 官方 API（platform.moonshot.cn）对同一 164 题跑一遍 pass@1，直接对比官方满血 K3 与该接口的差异
2. 若官方 API pass@1 显著高于 80.49%，可确认该白名单接口为降级/限流版本
3. 该接口可作为日常代码生成使用（80% 通过率），但不宜用于对准确性要求高的场景

---

## 附录：数据文件索引

| 文件 | 说明 |
|---|---|
| `humaneval_results_final.json` | 初跑完整结果（164 题） |
| `humaneval_rerun_bug.json` | 4 个提取 bug 任务重跑结果 |
| `humaneval_rerun_timeout.json` | 9 个超时任务重跑结果（含重试记录） |
| `humaneval_results_merged.json` | **合并后最终结果（准确版）** |
| `humaneval_eval.py` | 初跑评测脚本 |
| `humaneval_rerun_bug.py` | 提取 bug 修复重跑脚本 |
| `humaneval_rerun_timeout.py` | 超时任务重跑脚本（带 6 次重试） |
