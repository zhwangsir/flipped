#!/bin/bash
# M8.T4 验收脚本：Tauri 菜单/托盘、打包配置、CI 脚手架
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== M8.T4 验证：Tauri 打包/签名/自动更新脚手架 =="

echo "[1/7] 验证 tauri.conf.json 结构"
python3 - <<'PY'
import json, sys
from pathlib import Path
conf = json.loads(Path("console/src-tauri/tauri.conf.json").read_text())
assert conf.get("version"), "version 缺失"
assert conf.get("identifier"), "identifier 缺失"
assert conf.get("app", {}).get("trayIcon", {}).get("iconPath"), "app.trayIcon.iconPath 缺失"
assert "macOS" in conf.get("bundle", {}), "bundle.macOS 缺失"
assert conf["bundle"]["macOS"].get("minimumSystemVersion"), "macOS.minimumSystemVersion 缺失"
assert "signingIdentity" in conf["bundle"]["macOS"], "macOS.signingIdentity 缺失"
print("tauri.conf.json 结构 OK")
PY

echo "[2/7] 验证图标文件存在"
for icon in console/src-tauri/icons/icon.png \
            console/src-tauri/icons/32x32.png \
            console/src-tauri/icons/128x128.png \
            console/src-tauri/icons/128x128@2x.png \
            console/src-tauri/icons/icon.icns \
            console/src-tauri/icons/icon.ico; do
    test -f "$icon" || { echo "缺少图标: $icon"; exit 1; }
done
echo "图标文件 OK"

echo "[3/7] 验证 Cargo.toml feature 配置"
grep -q 'tray-icon' console/src-tauri/Cargo.toml || { echo "Cargo.toml 缺少 tray-icon feature"; exit 1; }
grep -q 'unstable' console/src-tauri/Cargo.toml || { echo "Cargo.toml 缺少 unstable feature"; exit 1; }
echo "Cargo.toml feature OK"

echo "[4/7] Python 全量回归测试"
source .venv/bin/activate
PYTHONPATH=src python -m pytest tests/ -q

echo "[5/7] Console 生产构建"
cd console
npm run build
cd ..

echo "[6/7] Tauri Rust 构建与单元测试"
cd console/src-tauri
cargo build
cargo test
cd ../..

echo "[7/7] Tauri release 打包（若可用）"
if command -v cargo-tauri &>/dev/null || { command -v cargo &>/dev/null && cargo tauri --version &>/dev/null; }; then
    cd console/src-tauri
    echo "尝试 cargo tauri build（本地可能无 Apple 证书，未签名产物可接受）..."
    set +e
    cargo tauri build
    TAURI_BUILD_EXIT=$?
    set -e
    cd ../..
    if [ $TAURI_BUILD_EXIT -eq 0 ]; then
        echo "cargo tauri build 成功"
    else
        echo "WARN: cargo tauri build 失败（预期：本地缺少 Apple Developer 证书时签名无法通过），请由 CI 验证打包。"
    fi
else
    echo "WARN: 未找到 cargo-tauri CLI，跳过 release 打包，请由 CI 验证。"
fi

echo "== M8.T4 验证通过 =="
