# flipped · 六维度测试策略优化（TEST_STRATEGY_OPTIMIZATION.md）

> 目标：在现有 TEST_PLAN.md 四层分层（L1 单元 → L2 集成 → L3 系统 → L4 回归）基础上，
> 补齐性能、安全、兼容性、UX 四个缺失维度，形成全栈质量保障体系。
>
> 原则：每个维度都有可执行的脚本、明确的指标阈值、自动化的执行入口，
> 并接入 quality_gate.sh 统一门禁，避免"纸面策略"。

---

## 0. 当前测试现状快照（2026-07-27 · M160 后更新）

| 维度 | 现状 | 覆盖率 | 工具 | 差距 |
|------|------|--------|------|------|
| 功能测试 | ✅ 已有 | Python 86.13% / 前端 90.25% lines | pytest + vitest | browser.py/terminal.py 均已达 100%（38/38 + 88/88 lines）；assistant/observe/safety 已 100%/99% |
| 回归测试 | ✅ 已有 | 1945 py + 591 fe | quality_gate.sh + loop_test.sh + `.github/workflows/ci.yml` | CI 已落地，待接入实际仓库触发 |
| 性能测试 | ✅ 基线已建 | pytest-benchmark 8 项核心函数基线 + 前端交互流畅度基准 | tests/benchmarks/test_perf_benchmark.py + console/e2e/performance/interaction-perf.spec.ts | 待补并发测试(locust)、资源监控、前端 Lighthouse 脚本 |
| 安全测试 | ✅ 四项扫描已通 | bandit 0 HIGH / pip-audit 10 漏洞(均 wontfix) / npm audit 0 漏洞 / detect-secrets 0 | scripts/security_scan.sh | D-0003~D-0006 全部 fixed；pip-audit 剩余 10 为 chromadb/diskcache/pypdf2/starlette 无修复版本 |
| 兼容性测试 | ✅ 已落地 | 653 行测试 / chromium 62 passed | Playwright v1.61.1 + ci.yml 跨浏览器 job + console/e2e/compatibility/{interaction,layout,responsive,routing}.spec.ts | 已覆盖交互/布局/响应式断点(375/768/1280px)/路由；firefox+webkit 矩阵待 CI 实跑 |
| UX 测试 | ✅ a11y 已修复 | a11y 20 passed / design_score 达标 | @axe-core/playwright + design_lint.py + visual_regression.py + console/e2e/performance/interaction-perf.spec.ts | D-0007~D-0012 a11y 已修复；交互流畅度基准已建（FID/INP/动画帧率） |

---

## 1. 功能测试优化

### 1.1 目标
- Python 覆盖率从 82.86% → 85%（目标）
- 前端覆盖率从 29.36% → 50%（目标）
- 补齐 0% 覆盖模块：browser.py、terminal.py

### 1.2 工具
| 工具 | 用途 | 执行命令 |
|------|------|----------|
| pytest | Python 单元/集成测试 | `PYTHONPATH=src python -m pytest tests/ -q` |
| pytest-cov | 覆盖率采集 | `--cov=src --cov-report=term --cov-report=json` |
| vitest | 前端单元测试 | `cd console && npx vitest run` |
| @testing-library/react | 组件测试 | 已集成在 vitest 中 |

### 1.3 执行步骤
1. **补测 0% 模块**：为 `src/executor/browser.py` 和 `src/executor/terminal.py` 写 stub 单测
2. **前端补测**：FailurePanel、ContextPanel、Settings 等未覆盖组件
3. **边界用例**：补充空输入、超长文本、并发请求等边界场景
4. **每轮循环**：quality_gate.sh 全量跑 + 覆盖率趋势追踪

### 1.4 预期指标
| 指标 | 当前 | 目标 | 门禁 floor |
|------|------|------|------------|
| Python passed | 1945 | ≥1945 | ≥1900 |
| Python coverage | 86.13% | 88% | 80% |
| 前端 passed | 591 | ≥591 | ≥580 |
| 前端 lines cov | 90.25% | 92% | 28% |

### 1.5 责任分配
- 后端功能测试：开发 Agent（每个 milestone 必须附 TDD 测试）
- 前端功能测试：前端 Agent（每个组件必须附 .test.tsx）
- 覆盖率趋势监控：quality_gate.sh 自动采集

---

## 2. 性能测试

### 2.1 目标
- 建立后端 API 响应时间基准（P50/P95/P99）
- 建立前端首屏加载时间基准（LCP/FCP/TTFB）
- 检测并发处理能力（WebSocket 连接数 + API QPS）
- 监控资源占用（内存/CPU/文件描述符）

### 2.2 工具
| 工具 | 用途 | 安装 |
|------|------|------|
| pytest-benchmark | Python 函数级基准 | `pip install pytest-benchmark` |
| locust | API 并发负载测试 | `pip install locust` |
| lighthouse | 前端性能审计 | `npm i -D lighthouse` |
| psutil | 资源占用监控 | 已安装 |

### 2.3 执行步骤
1. **后端函数基准**（`tests/benchmarks/test_perf_benchmark.py`）：
   - orchestrator 调度延迟（mock LLM，测纯调度逻辑）
   - factory_loop 任务派发延迟
   - safety.is_safe_command 吞吐
   - model_router 路由决策延迟
2. **API 并发测试**（`tests/load/test_api_load.py`）：
   - 10/50/100 并发创建 session
   - WebSocket 并发消息推送
   - 长连接保活 + 断线重连
3. **前端性能审计**（`scripts/perf_audit.sh`）：
   - Lighthouse 跑 LCP/FCP/TTFB/CLS
   - Bundle size 分析（vite build --report）
4. **资源监控**（集成到 E2E 测试）：
   - 测试前后内存差值
   - 进程 CPU 峰值
   - 文件描述符泄漏检测

### 2.4 预期指标
| 指标 | 目标 | 门禁 |
|------|------|------|
| orchestrator 调度延迟 P95 | < 50ms | > 200ms 报警 |
| API 创建 session P95 | < 100ms | > 500ms 报警 |
| WebSocket 消息延迟 P95 | < 50ms | > 200ms 报警 |
| 前端 LCP | < 2.5s | > 4s 报警 |
| 前端 FCP | < 1.8s | > 3s 报警 |
| 前端 CLS | < 0.1 | > 0.25 报警 |
| 100 并发 API 错误率 | 0% | > 1% 报警 |
| 内存增长（10 轮 E2E） | < 100MB | > 500MB 报警 |

### 2.5 责任分配
- 后端基准：开发 Agent（每次 API 变更附 benchmark）
- 前端审计：前端 Agent（每次 UI 变更附 Lighthouse 报告）
- 趋势监控：CI 自动跑 + 结果记 `PERF_LOG.md`

---

## 3. 安全测试

### 3.1 目标
- SAST 静态安全扫描（Python + TypeScript）
- 依赖漏洞扫描（pip + npm）
- 命令注入防护验证（已有 safety.py，补测试）
- API 安全测试（认证/授权/输入校验）
- 敏感信息泄漏检测（密钥/令牌不进代码）

### 3.2 工具
| 工具 | 用途 | 安装 |
|------|------|------|
| bandit | Python SAST 扫描 | `pip install bandit` |
| pip-audit | Python 依赖漏洞扫描 | `pip install pip-audit` |
| npm audit | 前端依赖漏洞扫描 | 内置 |
| eslint-plugin-security | TypeScript 安全 lint | `npm i -D eslint-plugin-security` |
| secret-scan | 密钥泄漏检测 | `pip install detect-secrets` |
| pytest | 安全功能测试 | 已有 |

### 3.3 执行步骤
1. **Python SAST**（`scripts/security_scan.sh`）：
   ```bash
   bandit -r src/ -f json -o reports/bandit.json --severity-level HIGH
   ```
2. **依赖漏洞扫描**：
   ```bash
   pip-audit --desc --format json -o reports/pip-audit.json
   cd console && npm audit --json > reports/npm-audit.json
   ```
3. **密钥泄漏检测**：
   ```bash
   detect-secrets scan src/ console/src/ > reports/secrets.json
   ```
4. **安全功能测试**（`tests/security/`）：
   - `test_command_injection.py`：验证 is_safe_command 拦截各种注入模式
   - `test_api_auth.py`：验证 API 认证/授权边界
   - `test_xss_prevention.py`：验证前端输入转义
5. **ESLint 安全规则**（`console/.eslintrc.security.json`）：
   - 启用 eslint-plugin-security 推荐规则

### 3.4 预期指标
| 指标 | 目标 | 门禁 |
|------|------|------|
| bandit HIGH 级发现 | 0 | > 0 阻断 |
| bandit MEDIUM 级发现 | ≤ 2 | > 5 阻断 |
| pip-audit 漏洞 | 0 | > 0 阻断 |
| npm audit 漏洞 | 0 | > 0 阻断 |
| detect-secrets 命中 | 0 | > 0 阻断 |
| 安全功能测试通过率 | 100% | < 100% 阻断 |

### 3.5 责任分配
- SAST/依赖扫描：CI 自动跑（每次 push）
- 安全功能测试：开发 Agent（安全模块变更附测试）
- 密钥泄漏检测：pre-commit hook 自动跑

---

## 4. 兼容性测试

### 4.1 目标
- 跨浏览器兼容性（Chrome/Firefox/Safari/Edge）
- 响应式布局验证（移动端/平板/桌面）
- 操作系统兼容性（macOS/Linux/Windows）
- Tauri 桌面应用兼容性

### 4.2 工具
| 工具 | 用途 | 状态 |
|------|------|------|
| Playwright | 跨浏览器 E2E | ✅ 已安装 v1.61.1 |
| @axe-core/playwright | 无障碍 + 兼容性扫描 | ✅ 已安装 |
| vitest viewport | 响应式断点单测 | 需配置 |

### 4.3 执行步骤
1. **跨浏览器 E2E**（`console/e2e/cross-browser.spec.ts`）：
   ```typescript
   for (const browser of ['chromium', 'firefox', 'webkit']) {
     test(`核心流程在 ${browser} 正常`, async ({ page }) => {
       // 创建 session → 发消息 → 收 WS 事件 → 验证渲染
     });
   }
   ```
2. **响应式断点测试**（`console/src/__tests__/responsive.test.tsx`）：
   - 375px（手机）/ 768px（平板）/ 1280px（桌面）/ 1920px（4K）
   - 验证侧边栏折叠、终端抽屉、面板布局
3. **OS 兼容性**（GitHub Actions matrix）：
   ```yaml
   strategy:
     matrix:
       os: [ubuntu-latest, macos-latest, windows-latest]
   ```
4. **Tauri 兼容性**：手动验收 macOS/Windows/Linux 桌面包

### 4.4 预期指标
| 指标 | 目标 | 门禁 |
|------|------|------|
| 跨浏览器 E2E 通过率 | 100% | < 100% 阻断 |
| 响应式断点渲染正确率 | 100% | < 100% 阻断 |
| OS matrix 测试通过率 | 100% | < 100% 阻断 |

### 4.5 责任分配
- 跨浏览器 E2E：CI matrix 自动跑
- 响应式测试：前端 Agent（每次布局变更附断点测试）
- OS 兼容性：GitHub Actions matrix

---

## 5. 回归测试强化

### 5.1 目标
- CI/CD 自动化触发（push/PR 时自动跑全量门禁）
- 测试结果趋势可视化
- 测试隔离（不互相污染）
- 快速反馈（quick 模式 < 5min，full 模式 < 30min）

### 5.2 工具
| 工具 | 用途 | 状态 |
|------|------|------|
| GitHub Actions | CI/CD 流水线 | ✅ 已创建 `.github/workflows/ci.yml`（质量门禁 + 安全扫描 + 性能基准 + 跨浏览器 E2E 四 job 并行） |
| quality_gate.sh | 质量门禁 | ✅ 已有 |
| loop_test.sh | 循环测试 | ✅ 已有 |
| pytest-xdist | 并行测试 | 需安装 |

### 5.3 执行步骤
1. **创建 GitHub Actions**（`.github/workflows/ci.yml`）：
   ```yaml
   on: [push, pull_request]
   jobs:
     quality-gate:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
         - uses: actions/setup-node@v4
         - run: bash scripts/quality_gate.sh
     security-scan:
       runs-on: ubuntu-latest
       steps:
         - run: bash scripts/security_scan.sh
   ```
2. **并行测试**：安装 pytest-xdist，`pytest -n auto` 加速
3. **测试隔离**：每个测试用 tmpdir fixture，不共享状态
4. **快速反馈**：PR 跑 `quality_gate.sh --quick`，merge 跑 full

### 5.4 预期指标
| 指标 | 目标 | 门禁 |
|------|------|------|
| CI quick 模式耗时 | < 5min | > 10min 报警 |
| CI full 模式耗时 | < 30min | > 60min 报警 |
| 回归检出率 | 100% | 漏检 = 门禁失败 |
| 测试隔离率 | 100% | 有依赖 = 缺陷 |

### 5.5 责任分配
- CI 流水线：DevOps Agent（创建 + 维护）
- 回归测试：CI 自动跑（每次 push/PR）
- 趋势分析：TEST_LOG.md + quality_metrics_history.jsonl

---

## 6. 用户体验测试

### 6.1 目标
- 无障碍合规（WCAG 2.1 AA）
- 交互流畅度（动画 60fps、响应 < 100ms）
- 视觉一致性（设计系统遵循率）
- 错误态友好性（错误提示可理解 + 可恢复）

### 6.2 工具
| 工具 | 用途 | 状态 |
|------|------|------|
| @axe-core/playwright | 无障碍自动扫描 | ✅ 已安装 |
| design_lint.py | 设计系统遵循检查 | ✅ 已有 |
| visual_regression.py | 视觉回归对比 | ✅ 已有（opt-in） |
| Chrome DevTools Protocol | 帧率/交互延迟 | 需集成 |

### 6.3 执行步骤
1. **无障碍扫描**（`console/e2e/a11y.spec.ts`）：
   ```typescript
   import AxeBuilder from '@axe-core/playwright';
   test('无障碍扫描', async ({ page }) => {
     await page.goto('/');
     const results = await new AxeBuilder({ page }).analyze();
     expect(results.violations).toEqual([]);
   });
   ```
2. **交互流畅度**（Chrome Performance API）：
   - 测量 First Input Delay (FID)
   - 测量 Interaction to Next Paint (INP)
   - 测量动画帧率（requestAnimationFrame）
3. **视觉回归**（已有 visual_regression.py）：
   - 启用 `FLIPPED_USE_VISUAL_REGRESSION=1`
   - 基线截图 + 差异对比
4. **设计系统 lint**（已有 design_lint.py + lint_design_quality）：
   - 颜色 hex 值检查
   - 字体/间距/动效规范检查
   - meta viewport / img alt / 语义 HTML 检查

### 6.4 预期指标
| 指标 | 目标 | 门禁 |
|------|------|------|
| axe-core violations | 0 | > 0 阻断（critical/serious） |
| FID | < 100ms | > 300ms 报警 |
| INP | < 200ms | > 500ms 报警 |
| 动画帧率 | ≥ 60fps | < 30fps 报警 |
| design_score | ≥ 70 | < 60 阻断 |
| 视觉回归差异 | < 5% | > 10% 阻断 |

### 6.5 责任分配
- 无障碍扫描：CI 自动跑（每次 PR）
- 交互流畅度：前端 Agent（每次动画变更附测量）
- 视觉回归：opt-in 跑（`FLIPPED_USE_VISUAL_REGRESSION=1`）
- 设计 lint：quality_gate.sh 已集成

---

## 7. 测试结果跟踪与反馈机制

### 7.1 文档体系
| 文档 | 用途 | 更新频率 |
|------|------|----------|
| TEST_PLAN.md | 测试计划（四层分层 + 门禁标准） | 每个里程碑 |
| TEST_STRATEGY_OPTIMIZATION.md | 六维度策略（本文档） | 每季度评审 |
| TEST_LOG.md | 每轮测试证据流水 | 每轮循环 |
| DEFECT_LOG.md | 缺陷跟踪 | 每个缺陷 |
| PERF_LOG.md | 性能基准趋势 | 每次 perf 测试 |
| SECURITY_REPORT.md | 安全扫描结果 | 每次 push |
| quality_metrics.json | 指标快照（机器可读） | 每次门禁 |
| quality_metrics_history.jsonl | 指标趋势（时序） | 每轮循环 |

### 7.2 反馈回路
```
测试执行 → 指标采集 → 趋势对比 → 偏差分析 → 缺陷记录 → 修复 → 复测
    ↑                                                              ↓
    └────────────────── 连续 2 轮全绿 → 收尾 ←──────────────────────┘
```

### 7.3 责任矩阵（RACI）
| 活动 | 负责(R) | 审批(A) | 咨询(C) | 知会(I) |
|------|---------|---------|---------|---------|
| 功能测试编写 | 开发 Agent | 用户 | — | — |
| 质量门禁执行 | CI 自动 | — | — | 开发 Agent |
| 安全扫描 | CI 自动 | — | — | 用户 |
| 性能基准 | 开发 Agent | — | — | 用户 |
| 缺陷修复 | 开发 Agent | 用户 | — | — |
| 门禁放行 | quality_gate.sh | — | — | 用户 |

---

## 8. 实施路线图

| 阶段 | 内容 | 优先级 | 预计工时 |
|------|------|--------|----------|
| Phase 1 | 安全扫描脚本 + bandit/pip-audit 集成 | P0 | 2h |
| Phase 2 | 性能基准脚本 + pytest-benchmark 集成 | P0 | 3h |
| Phase 3 | quality_gate.sh 升级（集成安全+性能） | P0 | 1h |
| Phase 4 | GitHub Actions CI 流水线 | P1 | 2h |
| Phase 5 | 跨浏览器 E2E（Playwright matrix） | P1 | 3h |
| Phase 6 | 无障碍扫描（axe-core 自动化） | P1 | 2h |
| Phase 7 | 前端覆盖率提升（补测 panel 组件） | P2 | 4h |
| Phase 8 | 后端 0% 模块补测 | P2 | 3h |

---

## 9. 质量门禁升级清单

quality_gate.sh 新增门禁项：

| 门禁 | 命令 | 阈值 | 阻断级别 |
|------|------|------|----------|
| G6 · 安全 SAST | `bandit -r src/ -ll` | 0 HIGH | 硬阻断 |
| G7 · 依赖漏洞 | `pip-audit + npm audit` | 0 vuln | 硬阻断 |
| G8 · 密钥泄漏 | `detect-secrets scan` | 0 hit | 硬阻断 |
| G9 · 性能基准 | `pytest tests/benchmarks/` | 无回归 | 软告警 |
| G10 · 无障碍 | `npx @axe-core/cli` | 0 critical | 软告警 |
