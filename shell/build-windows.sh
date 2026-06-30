#!/usr/bin/env bash
# flipped · Windows 构建编排(D17)。在已 clone 的 VSCodium 脚手架上叠加 flipped 品牌 + 内建扩展，
# 然后走 VSCodium 的 get_repo → build → package → assets 出未签名 Inno Setup installer。
# 由 .github/workflows/release-windows.yml 在 windows-2022(shell:bash) 调用。
# 用法: build-windows.sh [build|checksums]
set -euo pipefail

FLIPPED_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # flipped repo 根
ROOT="$(cd "$FLIPPED_DIR/.." && pwd)"                            # 工作区(含 vscodium/)
VSCODIUM="$ROOT/vscodium"
ARCH="${VSCODE_ARCH:-x64}"

log() { echo "── [flipped-build] $*"; }

cmd="${1:-build}"

# ---- checksums 子命令: 对 assets 产物算 SHA256 ----
if [ "$cmd" = "checksums" ]; then
  cd "$VSCODIUM"
  if [ -d assets ]; then
    log "生成 assets/SHA256SUMS"
    ( cd assets && : > SHA256SUMS && for f in *; do
        [ "$f" = "SHA256SUMS" ] && continue
        [ -f "$f" ] && sha256sum "$f" >> SHA256SUMS
      done; cat SHA256SUMS )
  else
    log "WARN: 无 assets/ 目录(构建未产出?)"
  fi
  exit 0
fi

[ -d "$VSCODIUM" ] || { log "ERROR: 未找到 $VSCODIUM(workflow 应先 clone VSCodium)"; exit 1; }
cd "$VSCODIUM"

# ---- 1) 品牌覆盖: flipped product.overrides.json 深合并进 VSCodium 根 product.json ----
log "合并 flipped 品牌到 product.json(保留 VSCodium 的 Open-VSX gallery 等)"
jq -s '.[0] * .[1]' product.json "$FLIPPED_DIR/shell/product.overrides.json" > product.json.flipped
mv product.json.flipped product.json
log "品牌确认: nameLong=$(jq -r .nameLong product.json) / applicationName=$(jq -r .applicationName product.json)"

# ---- 2) (可选 v0.1) 内建 Cline + ide-extension 为 builtInExtensions ----
if [ "${INCLUDE_BUILTIN_EXTS:-0}" = "1" ]; then
  log "内建扩展: 取 Cline VSIX(Open VSX) + 本地打包 ide-extension VSIX"
  mkdir -p .build/cline .build/flipped
  CLINE_VER="$(curl -fsSL https://open-vsx.org/api/saoudrizwan/claude-dev/latest | jq -r '.version')"
  log "Cline 最新版本 = $CLINE_VER"
  curl -fsSL -o .build/cline/cline.vsix \
    "https://open-vsx.org/api/saoudrizwan/claude-dev/${CLINE_VER}/file/saoudrizwan.claude-dev-${CLINE_VER}.vsix"
  # Apache-2.0 合规: 解出 Cline 的 LICENSE/NOTICE 随分发保留
  ( cd .build/cline && unzip -o -q cline.vsix 'extension/LICENSE*' 'extension/NOTICE*' || true )

  log "打包 ide-extension 为 VSIX"
  ( cd "$FLIPPED_DIR/ide-extension" && npm ci && npm run compile \
      && npx --yes @vscode/vsce package --no-dependencies -o "$VSCODIUM/.build/flipped/flipped-ide-control-plane.vsix" )

  log "注入 builtInExtensions(本地 vsix 字段，不联网)"
  jq --arg cver "$CLINE_VER" '.builtInExtensions = [
      {name:"saoudrizwan.claude-dev", version:$cver, vsix:".build/cline/cline.vsix",
       metadata:{id:"00000000-0000-0000-0000-0000000c1100",
                 publisherId:{publisherName:"saoudrizwan",displayName:"Cline",flags:""},
                 publisherDisplayName:"Cline"}},
      {name:"flipped.flipped-ide-control-plane", version:"0.0.1", vsix:".build/flipped/flipped-ide-control-plane.vsix",
       metadata:{id:"00000000-0000-0000-0000-0000000f1100",
                 publisherId:{publisherName:"flipped",displayName:"flipped",flags:""},
                 publisherDisplayName:"flipped"}}
    ]' product.json > product.json.exts && mv product.json.exts product.json
else
  log "纯品牌构建(v0.0)：不内建扩展(include_builtins=false)"
fi

# ---- 3) 版本: 默认用 VSCodium upstream 钉定；仅显式传入才覆盖 ----
[ -n "${MS_TAG:-}" ] && { log "覆盖 MS_TAG=$MS_TAG"; export MS_TAG; }
[ -n "${RELEASE_VERSION:-}" ] && { log "覆盖 RELEASE_VERSION=$RELEASE_VERSION"; export RELEASE_VERSION; }

# ---- 4) 构建链(VSCodium 脚手架) ----
export CI_BUILD="${CI_BUILD:-no}"
export SHOULD_BUILD="${SHOULD_BUILD:-yes}"
export OS_NAME="${OS_NAME:-windows}"
export VSCODE_ARCH="$ARCH"
export npm_config_arch="$ARCH"
export npm_config_target_arch="$ARCH"

log "step get_repo.sh — 拉取 microsoft/vscode 源"
. ./get_repo.sh

log "step build.sh — prepare_vscode(换皮+patch) + npm ci + gulp 编译"
. ./build.sh

log "step package.sh — 打包 win32-${ARCH}"
./build/windows/package.sh

log "step prepare_assets.sh — Inno Setup 未签名 installer + zip"
if [ -f ./build/windows/prepare_assets.sh ]; then
  ./build/windows/prepare_assets.sh
else
  ./prepare_assets.sh
fi

log "构建完成，产物:"
ls -la assets 2>/dev/null || { log "WARN: 无 assets/，列出 build 输出"; ls -la "VSCode-win32-${ARCH}" 2>/dev/null || true; }
