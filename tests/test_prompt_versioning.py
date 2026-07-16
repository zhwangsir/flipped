"""M118 · Prompt 资产版本管理测试。

Prompt Versioning = 把 prompt 当代码管理：
- 版本化：每次修改生成新版本，可追溯
- A/B 测试：两个版本对比效果
- 回滚：出问题快速回退到上一版本
- 标签：stable / experimental / deprecated
"""
from __future__ import annotations

from driving.prompt_versioning import (
    PromptVersion,
    PromptRegistry,
    VersionTag,
    ABTestResult,
)


class TestPromptVersion:
    def test_version_has_fields(self):
        v = PromptVersion(
            id="v1",
            name="main_prompt",
            content="You are a helpful assistant.",
            version="1.0.0",
        )
        assert v.version == "1.0.0"
        assert v.tag == VersionTag.stable


class TestPromptRegistry:
    def test_register_and_get(self):
        reg = PromptRegistry()
        reg.register("greeting", "Hello!", version="1.0.0")
        v = reg.get("greeting")
        assert v is not None
        assert v.content == "Hello!"
        assert v.version == "1.0.0"

    def test_new_version_increments(self):
        reg = PromptRegistry()
        reg.register("greeting", "Hello!", version="1.0.0")
        reg.register("greeting", "Hi there!", version="1.1.0")
        v = reg.get("greeting")
        assert v.version == "1.1.0"
        assert len(reg.get_history("greeting")) == 2

    def test_rollback(self):
        reg = PromptRegistry()
        reg.register("greeting", "v1", version="1.0.0")
        reg.register("greeting", "v2", version="2.0.0")
        reg.rollback("greeting")
        v = reg.get("greeting")
        assert v.content == "v1"
        assert v.version == "1.0.0"

    def test_get_specific_version(self):
        reg = PromptRegistry()
        reg.register("test", "content v1", version="1.0.0")
        reg.register("test", "content v2", version="2.0.0")
        v = reg.get("test", version="1.0.0")
        assert v is not None
        assert v.content == "content v1"

    def test_tag_management(self):
        reg = PromptRegistry()
        reg.register("exp", "experimental", version="0.1.0")
        reg.set_tag("exp", VersionTag.experimental)
        v = reg.get("exp")
        assert v.tag == VersionTag.experimental


class TestABTest:
    def test_ab_test_result(self):
        reg = PromptRegistry()
        reg.register("prompt_a", "version A", version="1.0.0")
        reg.register("prompt_a", "version B", version="2.0.0")
        result = reg.run_ab_test(
            "prompt_a",
            "1.0.0",
            "2.0.0",
            metrics_a={"success_rate": 0.7, "avg_quality": 75},
            metrics_b={"success_rate": 0.85, "avg_quality": 82},
        )
        assert result.winner == "2.0.0"
        assert result.success_rate_delta > 0
