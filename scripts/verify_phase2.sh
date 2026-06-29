#!/usr/bin/env bash
# Phase 2 环境模板验收（D12）：随项目内置多语言环境声明合法且完整。
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }
T=infra/env-templates

echo "== devcontainer.json 合法 + 多语言 Features =="
$PY -c "
import json
d=json.load(open('$T/devcontainer.json'))
f=d.get('features',{})
need=['python','node','rust','java','mise']
miss=[n for n in need if not any(n in k for k in f)]
assert not miss, f'缺 Features: {miss}'
assert 'mise install' in d.get('postCreateCommand',''), '缺 mise install postCreate'
print('   features:', len(f), '| 覆盖:', need)
" && pass "devcontainer 多语言 Features 完整" || bad "devcontainer 模板不完整"

echo "== .mise.toml 合法 + 钉定 4 语言 =="
$PY -c "
import tomllib
d=tomllib.load(open('$T/.mise.toml','rb'))
t=d.get('tools',{})
for k in ('python','node','rust','java'):
    assert k in t, f'缺 {k}'
print('   tools:', t)
" && pass ".mise.toml 钉定完整" || bad ".mise.toml 不完整"

echo ""
if [ $fail -eq 0 ]; then echo "Phase 2 环境模板验收：通过 ✅"; else echo "Phase 2 验收：有未通过 ❌"; fi
exit $fail
