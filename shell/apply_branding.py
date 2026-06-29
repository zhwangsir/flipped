"""把 flipped 品牌覆盖深合并进 VSCodium/Code-OSS 的 product.json（D14）。

用法：python3 shell/apply_branding.py <code-oss-checkout>/product.json [shell/product.overrides.json]
- 覆盖项胜出；嵌套 dict 递归合并（如 extensionsGallery 整体替换为 Open VSX）。
deep_merge / apply_overrides 是纯函数（可单测）；main 读写文件。
"""
from __future__ import annotations

import json
import os
import sys


def deep_merge(base: dict, override: dict) -> dict:
    """递归合并，override 胜出；嵌套 dict 合并，其余直接替换。返回新 dict（不可变）。"""
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def apply_overrides(product: dict, overrides: dict) -> dict:
    return deep_merge(product, overrides)


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python3 shell/apply_branding.py <product.json 路径> [overrides 路径]")
        return 2
    product_path = sys.argv[1]
    here = os.path.dirname(os.path.abspath(__file__))
    overrides_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "product.overrides.json")
    with open(product_path) as f:
        product = json.load(f)
    with open(overrides_path) as f:
        overrides = json.load(f)
    merged = apply_overrides(product, overrides)
    with open(product_path, "w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    print(f"✓ 已把品牌覆盖({len(overrides)} 项)合并进 {product_path}")
    print(f"  nameLong={merged.get('nameLong')} | gallery={merged.get('extensionsGallery', {}).get('serviceUrl')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
