#!/usr/bin/env bash
# Phase 3 外壳脚手架验收（D14）：品牌覆盖配置合法 + 合并逻辑正确。
# 注：实际 VSCodium 构建/签名/公证需网络+用户证书，不在本脚本范围（见 shell/BUILD.md）。
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

echo "== product.overrides.json 合法 + 关键品牌字段 + Open VSX =="
$PY -c "
import json
d=json.load(open('shell/product.overrides.json'))
for k in ('nameLong','applicationName','darwinBundleIdentifier','urlProtocol'):
    assert d.get(k), f'缺品牌字段 {k}'
g=d.get('extensionsGallery',{})
assert 'open-vsx.org' in g.get('serviceUrl',''), '市场必须是 Open VSX(微软市场红线)'
print('   品牌:', d['nameLong'], '| bundleId:', d['darwinBundleIdentifier'], '| gallery: Open VSX')
" && pass "品牌覆盖配置合法且完整" || bad "品牌覆盖配置不完整"

echo "== apply_branding 合并逻辑(在样例 product.json 上实测) =="
$PY -c "
import json, sys
sys.path.insert(0,'shell')
from apply_branding import apply_overrides
# 模拟 VSCodium 的 product.json(微软市场 + 自带字段)
base={'nameShort':'VSCodium','applicationName':'codium','quality':'stable',
      'extensionsGallery':{'serviceUrl':'https://marketplace.visualstudio.com/x'},'keep':'me'}
ov=json.load(open('shell/product.overrides.json'))
m=apply_overrides(base, ov)
assert m['nameShort']=='flipped' and m['applicationName']=='flipped', '品牌应覆盖'
assert m['quality']=='stable' and m['keep']=='me', '非覆盖字段应保留'
assert 'open-vsx.org' in m['extensionsGallery']['serviceUrl'], 'gallery 应替换为 Open VSX'
assert base['nameShort']=='VSCodium', '原对象不可变'
print('   合并后 nameShort=%s, gallery=Open VSX, 保留 quality/keep' % m['nameShort'])
" && pass "品牌合并逻辑正确(覆盖+保留+不可变)" || bad "合并逻辑错误"

echo ""
if [ $fail -eq 0 ]; then echo "Phase 3 外壳脚手架验收：通过 ✅（构建/签名需用户证书，见 shell/BUILD.md）"; else echo "Phase 3 脚手架验收：有未通过 ❌"; fi
exit $fail
