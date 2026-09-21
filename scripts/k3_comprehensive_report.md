# Kimi-K3 API 综合能力评测报告

- **评测日期**：2026-08-08 11:57
- **评测接口**：`http://43.119.32.180:8002/v1`
- **模型标识**：`moonshotai/Kimi-K3`
- **任务总数**：17 项，覆盖 6 个类别
- **评分维度**：正确性 (correctness) / 代码质量 (quality) / 完整性 (completeness) / 加权总分 (total)

## 1. 总体评分

| 指标 | 数值 |
|---|---:|
| 成功生成任务数 | 15 / 17 |
| 成功任务平均总分 | **79.8%** |
| 失败任务数 | 2 |

### 1.1 分类评分

| 类别 | 成功任务数 | 平均总分 |
|---|---:|---:|
| debugging | 1 | 42.5% |
| long_context | 2 | 82.5% |
| multi_language | 2 | 35.0% |
| python_advanced | 4 | 85.6% |
| python_basic | 4 | 98.1% |
| reasoning | 2 | 92.5% |

## 2. 单项任务评分

| 任务 | 类别 | 状态 | run1 | run2 | 延迟 | Token(P/C/R) | 正确性 | 质量 | 完整性 | 总分 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 递归斐波那契 | python_basic | ✅ 通过 | 100% | 100% | 27.1s | P:146 / C:662 / R:470 | 100% | 100% | 100% | 100% | 测试 6/6 passed |
| 二分查找 | python_basic | ✅ 通过 | 92% | 92% | 16.3s | P:147 / C:299 / R:60 | 100% | 75% | 100% | 92% | 质量检查缺: edge_empty |
| 邮箱验证 | python_basic | ✅ 通过 | FAIL | 100% | 63.8s | P:160 / C:1255 / R:876 | 100% | 100% | 100% | 100% | 测试 9/9 passed |
| 栈数据结构 | python_basic | ✅ 通过 | 100% | 100% | 32.0s | P:142 / C:838 / R:476 | 100% | 100% | 100% | 100% | 生成并校验通过 |
| 简易 JSON 解析器 | python_basic | ❌ 失败 | FAIL | — | 63.5s | — | — | — | — | — | HTTP 504 Gateway Time-out（上游 nginx 超时） |
| 快速排序 | python_advanced | ✅ 通过 | 42% | 42% | 18.1s | P:137 / C:450 / R:276 | 0% | 75% | 100% | 42% | RecursionError: maximum recursion depth exceeded |
| 手写 LRU 缓存 | python_advanced | ✅ 通过 | 100% | 100% | 42.2s | P:164 / C:1015 / R:563 | 100% | 100% | 100% | 100% | 生成并校验通过 |
| Trie 前缀树 | python_advanced | ✅ 通过 | 100% | 100% | 47.7s | P:132 / C:1229 / R:730 | 100% | 100% | 100% | 100% | 生成并校验通过 |
| 图 BFS 最短路径 | python_advanced | ✅ 通过 | 100% | 100% | 24.8s | P:153 / C:663 / R:390 | 100% | 100% | 100% | 100% | 测试 4/4 passed |
| TypeScript Promise.all | multi_language | ✅ 通过 | 44% | 44% | 38.6s | P:146 / C:1018 / R:620 | 0% | 80% | 100% | 44% | 质量检查缺: generic |
| Go Worker Pool | multi_language | ❌ 失败 | FAIL | — | 61.9s | — | — | — | — | — | HTTP 504 Gateway Time-out（上游 nginx 超时） |
| Rust Result 处理 | multi_language | ✅ 通过 | 26% | 26% | 50.6s | P:135 / C:1407 / R:1125 | 0% | 20% | 100% | 26% | 质量检查缺: function_def, result_type, question_mark, parse |
| 并发 Bug 诊断 | debugging | ✅ 通过 | 42% | 42% | 45.4s | P:160 / C:1238 / R:985 | 0% | 75% | 100% | 42% | 质量检查缺: race_mentioned |
| 逻辑推理题 | reasoning | ✅ 通过 | 85% | 85% | 17.2s | P:154 / C:415 / R:164 | 0% | 50% | 100% | 85% | 质量检查缺: reasoning |
| 数列求和 | reasoning | ✅ 通过 | 100% | 100% | 15.9s | P:154 / C:405 / R:200 | 100% | 100% | 100% | 100% | 测试 4/4 passed |
| 长文本关键信息提取 | long_context | ✅ 通过 | 100% | 100% | 5.2s | P:5624 / C:59 / R:44 | 0% | 100% | 100% | 100% | 生成并校验通过 |
| 多步骤指令遵循 | long_context | ✅ 通过 | 65% | 65% | 6.3s | P:145 / C:131 / R:105 | 0% | 100% | 100% | 65% | 生成并校验通过 |

## 3. 与 Kimi-K2.7-Code / GLM-5.2 横向对比（重叠 5 题）

| 任务 | K3-API (run2) | Kimi-K2.7-Code | GLM-5.2 |
|---|---|---|---|
| fib_recursive | 100% | 100% | 100% |
| binary_search | 92% | 92% | 92% |
| validate_email | 100% | 100% | 0% |
| stack_class | 100% | 100% | 100% |
| json_parser | 0% | 100% | 0% |
| **平均** | **78.5%** | **98.5%** | **58.5%** |

## 4. 关键耗时对比

| 任务 | K3-API 结果 | K3 耗时 | K2.7-Code 耗时 | 说明 |
|---|---|---|---|---|
| 邮箱验证 | 通过 | 63.8s | 32.0s | K3 刚压线完成；K2.7 快一倍 |
| 简易 JSON 解析器 | 504 超时 | 63.5s | 158.2s | K2.7 需 158s，上游 63s 截断导致 K3 无法完成 |

## 5. 失败与缺陷分析

### 5.1 上游超时导致的失败（网络/服务端）

- `json_parser`：连续两次均在上游 ~63s 返回 `504 Gateway Time-out`。
- `go_worker_pool`：同样稳定 504，耗时 61.9s。
- 判定：Caddy 本身无超时设置；504 来自 Moonshot 侧 nginx。由于 K2.7-Code 完成 `json_parser` 需要 158s，当前通道的 ~63s 硬限制对复杂代码生成不友好。

### 5.2 模型自身缺陷（与网络无关）

| 任务 | 问题 | 影响 |
|---|---|---|
| 快速排序 | 重复元素时 `equal` 分区不收敛，触发 `RecursionError` |  correctness=0% |
| Rust Result 处理 | 缺少函数定义、`Result` 类型、`?` 运算符、解析逻辑 | quality=20% |
| TypeScript Promise.all | 代码无法运行，缺少泛型支持 | quality=80% / correctness=0% |
| 并发 Bug 诊断 | 给出 `threading.Lock` 但未解释 race condition | quality=75% / 缺 race_mentioned |
| 多步骤指令遵循 | 内容正确但格式未严格按指令输出 | total=65% |

## 6. 结论

- **总体得分**：79.8%（15/17 任务成功生成）。
- **与 K2.7-Code 的差距**：在重叠 5 题上 K3-API 平均 78.5%，K2.7-Code 平均 98.5%。
- **主要瓶颈**：上游 ~63s 超时让复杂任务（如手写 JSON 解析器）无法完成；模型本身在边界条件、多语言、严格指令遵循上表现不佳。
- **是否满血 K3**：**否**。该接口在简单任务上表现正常，但速度和复杂任务完成度均不符合满血 K3 预期。

---

*报告由 `test_k3_comprehensive.py` 自动生成，原始数据见 `k3_comprehensive_eval.json`。*