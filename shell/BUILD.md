# Phase 3 · 外壳构建 Runbook（Code-OSS fork → flipped IDE）

> 把 VSCodium(Code-OSS 干净构建脚手架) 换皮成品牌 IDE，内建 Cline + IDE 控制面扩展，三平台打包。
> 决策依据 D14（用 VSCodium 脚手架、Open VSX、不打包微软闭源 builtin、保留 Cline NOTICE）。
> ⚠️ 标 **[需你]** 的步骤需要你的账号/证书，无法自主完成。

## 0. 前置
- Node 20.x、Git + Git LFS、Python3。
- macOS 打包/签名：**[需你]** Apple Developer ID Application 证书 + notarytool 凭据。
- Windows：**[需你]** Authenticode 代码签名证书。

## 1. 取脚手架 + 换皮（可自主）
```bash
git clone https://github.com/VSCodium/vscodium.git build/vscodium
cd build/vscodium
# 拉取上游 vscode 源(其脚手架脚本会做)；然后把 flipped 品牌合并进 product.json：
python3 ../../shell/apply_branding.py ./product.json ../../shell/product.overrides.json
# 替换图标/启动画面资源(src/stable/resources/...)；品牌 patch 越薄越好(降低月度 rebase 冲突)
```
- 市场端点已在 overrides 设为 **Open VSX**（微软市场红线，D14）。
- **不打包**微软闭源 builtin（C/C++、Pylance、Remote、C#）——fork 中已被技术性禁用。

## 2. 内建 Cline + IDE 控制面（可自主）
- 把 Cline(Apache-2.0) 的 VSIX 与本仓库 `ide-extension/`(编译后) 放进 builtin extensions 目录 / `product.json` 的 `builtInExtensions`。
- 随分发包附 Apache-2.0 全文 + Cline 的 LICENSE/NOTICE，并在"关于/第三方声明"展示署名（D14）。
- 模型端点外置：默认 OpenAI 兼容 `http://localhost:4000/v1`，用户可在设置里改（D11）。

## 3. 三平台构建（可自主，需网络/时间）
```bash
# 见 VSCodium dev/build.sh；按平台产物：
# macOS: .app/.dmg | Windows: .msi(WiX) | Linux: .deb/.rpm/AppImage
```

## 4. 签名 / 公证 / 分发 — **[需你]**
- **macOS**：`codesign`(Developer ID, hardened runtime) + `notarytool` 公证 + `staple`；验证 Gatekeeper 不报 Unnotarized。对嵌入的二进制(含 Python sidecar 解释器/native wheel)**逐个**签名(D11)。
- **Windows**：Authenticode 签名(否则 SmartScreen 告警)。
- 发布 SHA256 校验和；Open VSX 供应链审计(锁随包扩展来源/版本)。

## CI 云构建（D17，Windows 首选路径）

本机为 macOS，**无法构建 Windows 原生包**(node-pty/spdlog 等需 Windows MSVC)。故 Windows release 走 **GitHub Actions `windows-2022` 云构建**：CI 里 clone VSCodium 脚手架 + 叠加 flipped 品牌/扩展，不把上万个 VSCodium 文件塞进本仓库(拓扑 T2)。

- workflow：`.github/workflows/release-windows.yml`(手动 `workflow_dispatch`，不随 push 自动跑)。
- 编排脚本：`shell/build-windows.sh`(品牌合并→可选内建扩展→get_repo→build→package→prepare_assets→SHA256)。
- 分阶段(`include_builtins` 开关)：
  - **v0.0**：纯品牌 VSCodium x64 未签名 `.exe`(先验证整条云构建管线跑通)。
  - **v0.1**：`include_builtins=true` → 内建 Cline + `ide-extension`(本地 vsix，Apache-2.0 NOTICE 随包)。
  - **v0.2**：再随包带多 Agent 驾驭层 Python sidecar(python-build-standalone；注入 gulp 产物/installer，**非** electron-builder——VSCodium 不用它)。
- 触发：`gh workflow run release-windows.yml -f include_builtins=false`(首跑)。产物在 Actions artifact `flipped-windows-x64`。
- 未签名分发指引见 `shell/win/RELEASE_NOTES.md`；签名钩子(Inno `#ifdef Sign` + Azure Trusted Signing)已在文档预留，待证书。
- 多端：Windows 跑通后，同管线加 `macos`/`linux` job 成矩阵。

> ⚠️ VSCodium 的 Windows 构建对版本钉定/原生模块/SDK 敏感，**首跑大概率需迭代几轮**(已据调研预置 REH=no、MSI=no、windows-2022、bash、品牌深合并等规避)。逐轮看 CI 日志修正。

## 现状（本仓库已就绪部分）
- ✅ 品牌覆盖配置 `product.overrides.json` + 合并脚本 `apply_branding.py`（`scripts/verify_phase3_scaffold.sh` 验证）。
- ✅ Windows 云构建管线：`release-windows.yml` + `build-windows.sh` + `win/RELEASE_NOTES.md`（D17）。
- ✅ 待内建的扩展：`ide-extension/`(编译通过)。
- ⏳ 余：CI 首跑迭代到绿(v0.0→v0.1→v0.2) + 签名公证(**需你 Apple/Windows 证书**)。
