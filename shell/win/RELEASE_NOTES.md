# flipped IDE for Windows — 首版(未签名)

> 本包**未做代码签名**(Authenticode 证书后补，D17)。能正常安装运行，但 Windows 会提示"未知发布者"。

## 安装

1. 下载 `FlippedSetup-x64-<ver>.exe`(系统级)或 `FlippedUserSetup-x64-<ver>.exe`(用户级，免管理员)。
2. 首次运行 SmartScreen 弹"**Windows 已保护你的电脑**"——这是未签名的正常表现，不是病毒：
   点 **More info / 更多信息** → **Run anyway / 仍要运行**。
3. 若文件被标记为"已阻止"：右键 `.exe` → **属性** → 勾选 **解除锁定(Unblock)** → 确定。

> Windows 11 的 **Smart App Control** 可能更激进地直接拦截无信誉的未签名程序；企业 GPO 也可能禁用"仍要运行"。这些情况下需签名版(待 Authenticode 证书)。

## 校验完整性(可选但推荐)

`SHA256SUMS` 随包发布。校验下载是否被篡改(只验完整性，**不等于**安全背书)：

```powershell
certutil -hashfile FlippedSetup-x64-<ver>.exe SHA256
# 或
Get-FileHash .\FlippedSetup-x64-<ver>.exe -Algorithm SHA256
```
比对输出与 `SHA256SUMS` 中对应行一致即可。

## 配置模型端点

flipped 内建的 agent(Cline)默认连 OpenAI 兼容端点 `http://localhost:4000/v1`。首次使用在设置里把 Base URL 改成你的端点(如本地 LiteLLM 代理或内网推理服务)，填好 model 名即可。**端点不硬编码**，可自由更换。

## 关于签名(后续)

CI 已预留 Authenticode 钩子(Inno Setup `#ifdef Sign` + Azure Trusted Signing action，D17)。备好证书后在 CI 配置 secret 即可启用，届时不再有 SmartScreen 警告。
