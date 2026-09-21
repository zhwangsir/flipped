"""Tests for model endpoint routing and health checks (M5.3)."""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from driving.model_router import (  # noqa: E402
    DEFAULT_EXO_URL,
    DEFAULT_PROXY_URL,
    DEFAULT_WORKER_PROXY_URL,
    is_endpoint_healthy,
    is_model_available,
    resolve_model_config,
    resolve_worker_model_config,
)


def _resp(status=200, data=None):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value={"data": data or []})
    return r


@patch("driving.model_router.httpx.get")
def test_is_endpoint_healthy_true(mock_get):
    mock_get.return_value = _resp(200)
    assert is_endpoint_healthy("http://proxy.test/v1") is True
    mock_get.assert_called_once()


@patch("driving.model_router.httpx.get")
def test_is_endpoint_healthy_false_on_error(mock_get):
    mock_get.side_effect = TimeoutError("down")
    assert is_endpoint_healthy("http://proxy.test/v1") is False


@patch("driving.model_router.httpx.get")
def test_is_model_available_true(mock_get):
    mock_get.return_value = _resp(200, [{"id": "architect"}, {"id": "coder"}])
    assert is_model_available("http://proxy.test/v1", "architect") is True


@patch("driving.model_router.httpx.get")
def test_is_model_available_false_when_missing(mock_get):
    mock_get.return_value = _resp(200, [{"id": "coder"}])
    assert is_model_available("http://proxy.test/v1", "architect") is False


@patch("driving.model_router.httpx.get")
def test_resolve_model_config_prefers_proxy(mock_get, monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "http://proxy.test/v1")
    monkeypatch.setenv("FLIPPED_MODEL_BASE_URL", "http://direct.test/v1")
    monkeypatch.setenv("FLIPPED_ARCHITECT_MODEL", "mlx-community/GLM-5.2-fp8")

    def side_effect(url, **kwargs):
        if url.startswith("http://proxy.test"):
            return _resp(200, [{"id": "architect"}])
        return _resp(200, [{"id": "mlx-community/GLM-5.2-fp8"}])

    mock_get.side_effect = side_effect
    base, model = resolve_model_config("architect")
    assert base == "http://proxy.test/v1"
    assert model == "architect"


@patch("driving.model_router.httpx.get")
def test_resolve_model_config_fallback_direct_when_proxy_down(mock_get, monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "http://proxy.test/v1")
    monkeypatch.setenv("FLIPPED_MODEL_BASE_URL", "http://direct.test/v1")
    monkeypatch.setenv("FLIPPED_ARCHITECT_MODEL", "mlx-community/GLM-5.2-fp8")

    def side_effect(url, **kwargs):
        if url.startswith("http://proxy.test"):
            raise TimeoutError("down")
        return _resp(200, [{"id": "mlx-community/GLM-5.2-fp8"}])

    mock_get.side_effect = side_effect
    base, model = resolve_model_config("architect")
    assert base == "http://direct.test/v1"
    assert model == "mlx-community/GLM-5.2-fp8"


@patch("driving.model_router.httpx.get")
def test_resolve_model_config_fallback_direct_when_alias_missing(mock_get, monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "http://proxy.test/v1")
    monkeypatch.setenv("FLIPPED_MODEL_BASE_URL", "http://direct.test/v1")
    monkeypatch.setenv("FLIPPED_ARCHITECT_MODEL", "mlx-community/GLM-5.2-fp8")

    def side_effect(url, **kwargs):
        if url.startswith("http://proxy.test"):
            return _resp(200, [{"id": "coder"}])  # no architect
        return _resp(200, [{"id": "mlx-community/GLM-5.2-fp8"}])

    mock_get.side_effect = side_effect
    base, model = resolve_model_config("architect")
    assert base == "http://direct.test/v1"
    assert model == "mlx-community/GLM-5.2-fp8"


@patch("driving.model_router.httpx.get")
def test_resolve_model_config_fallback_direct_when_both_down(mock_get, monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "http://proxy.test/v1")
    monkeypatch.setenv("FLIPPED_MODEL_BASE_URL", "http://direct.test/v1")
    monkeypatch.setenv("FLIPPED_ARCHITECT_MODEL", "mlx-community/GLM-5.2-fp8")
    mock_get.side_effect = TimeoutError("down")
    base, model = resolve_model_config("architect")
    assert base == "http://direct.test/v1"
    assert model == "mlx-community/GLM-5.2-fp8"


@patch("driving.model_router.httpx.get")
def test_resolve_worker_model_config_prefers_proxy(mock_get, monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "http://proxy.test/v1")
    monkeypatch.setenv("OPENHANDS_PROXY_BASE_URL", "http://worker-proxy.test/v1")
    monkeypatch.setenv("FLIPPED_MODEL_BASE_URL", "http://direct.test/v1")
    monkeypatch.setenv("OPENHANDS_MODEL", "coder")
    monkeypatch.setenv("FLIPPED_CODER_MODEL", "mlx-community/GLM-5.2-fp8")

    def side_effect(url, **kwargs):
        if url.startswith("http://proxy.test"):
            return _resp(200, [{"id": "coder"}])
        return _resp(200, [{"id": "mlx-community/GLM-5.2-fp8"}])

    mock_get.side_effect = side_effect
    base, model = resolve_worker_model_config()
    assert base == "http://worker-proxy.test/v1"
    assert model == "coder"


@patch("driving.model_router.httpx.get")
def test_resolve_worker_model_config_fallback_direct(mock_get, monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "http://proxy.test/v1")
    monkeypatch.setenv("FLIPPED_MODEL_BASE_URL", "http://direct.test/v1")
    monkeypatch.setenv("OPENHANDS_MODEL", "coder")
    monkeypatch.setenv("FLIPPED_CODER_MODEL", "mlx-community/GLM-5.2-fp8")

    def side_effect(url, **kwargs):
        if url.startswith("http://proxy.test"):
            raise TimeoutError("down")
        return _resp(200, [{"id": "mlx-community/GLM-5.2-fp8"}])

    mock_get.side_effect = side_effect
    base, model = resolve_worker_model_config()
    assert base == "http://direct.test/v1"
    assert model == "mlx-community/GLM-5.2-fp8"


@patch("driving.model_router.httpx.get")
def test_resolve_worker_model_config_defaults_when_env_empty(mock_get, monkeypatch):
    """当前单模型模式：env 全空时 coder 默认 = GLM-5.2-fp8。

    历史：M156 双模型期此默认曾是 Kimi-K2.7-Code-4bit；Kimi 从 exo 下线后
    回归 M149 单模型语义（与 architect/supervisor/overseer/monitor 同源）。
    若未来恢复双模型：export FLIPPED_CODER_MODEL=mlx-community/Kimi-K2.7-Code-4bit。
    """
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("FLIPPED_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("OPENHANDS_BASE_URL", raising=False)
    monkeypatch.delenv("OPENHANDS_MODEL", raising=False)
    monkeypatch.delenv("FLIPPED_CODER_MODEL", raising=False)
    mock_get.side_effect = TimeoutError("down")
    base, model = resolve_worker_model_config()
    assert base == DEFAULT_EXO_URL
    assert model == "mlx-community/GLM-5.2-fp8"


@patch("driving.model_router.httpx.get")
def test_single_model_routing_complete(mock_get, monkeypatch):
    """单模型路由完整性：全部 alias（含 coder）→ GLM-5.2-fp8。

    锁定单模型分工：architect/coder/supervisor/overseer/monitor 同源（编排/执行同源）。
    env 全空时验证默认映射。
    """
    monkeypatch.delenv("FLIPPED_ARCHITECT_MODEL", raising=False)
    monkeypatch.delenv("FLIPPED_CODER_MODEL", raising=False)
    monkeypatch.delenv("FLIPPED_SUPERVISOR_MODEL", raising=False)
    monkeypatch.delenv("FLIPPED_OVERSEER_MODEL", raising=False)
    monkeypatch.delenv("FLIPPED_MONITOR_MODEL", raising=False)
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("FLIPPED_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("OPENHANDS_BASE_URL", raising=False)
    monkeypatch.delenv("OPENHANDS_MODEL", raising=False)
    mock_get.side_effect = TimeoutError("down")  # 强制走直连回退，暴露 _model_id_for_alias 默认

    for alias in ("architect", "coder", "supervisor", "overseer", "monitor"):
        _, model = resolve_worker_model_config(alias)
        assert model == "mlx-community/GLM-5.2-fp8", f"{alias} 应默认 GLM-5.2-fp8，实际 {model}"


@patch("driving.model_router.httpx.get")
def test_coder_env_override_switches_model(mock_get, monkeypatch):
    """env 覆盖钉：FLIPPED_CODER_MODEL 可一行切换 coder 模型。

    单模型模式下此机制保留为反向开关：若未来 exo 恢复 Kimi，
    export FLIPPED_CODER_MODEL=mlx-community/Kimi-K2.7-Code-4bit 即可切回双模型，无需改代码。
    """
    monkeypatch.setenv("FLIPPED_CODER_MODEL", "mlx-community/Kimi-K2.7-Code-4bit")
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("FLIPPED_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("OPENHANDS_BASE_URL", raising=False)
    monkeypatch.delenv("OPENHANDS_MODEL", raising=False)
    mock_get.side_effect = TimeoutError("down")
    _, model = resolve_worker_model_config()
    assert model == "mlx-community/Kimi-K2.7-Code-4bit"


@patch("driving.model_router.httpx.get")
def test_resolve_worker_config_local_worker_bypasses_proxy(mock_get, monkeypatch):
    """M101 防御性修复：FLIPPED_USE_LOCAL_WORKER=1 时直接走 exo 直连，
    避免 host.docker.internal:4000 在宿主机无法 DNS 解析 → ConnectError。

    回归场景：LiteLLM proxy :4000 健康且 model 可用时，若不短路，
    会返回 host.docker.internal:4000 导致 local_worker ConnectError。
    """
    monkeypatch.setenv("FLIPPED_USE_LOCAL_WORKER", "1")
    monkeypatch.setenv("LITELLM_BASE_URL", "http://proxy.test/v1")
    monkeypatch.setenv("OPENHANDS_PROXY_BASE_URL", "http://host.docker.internal:4000/v1")
    monkeypatch.setenv("FLIPPED_MODEL_BASE_URL", "http://direct.test/v1")
    monkeypatch.setenv("OPENHANDS_MODEL", "coder")
    monkeypatch.setenv("FLIPPED_CODER_MODEL", "mlx-community/Kimi-K2.7-Code-4bit")

    base, model = resolve_worker_model_config("coder")
    assert base == "http://direct.test/v1"  # 直连，不是 host.docker.internal
    assert model == "mlx-community/Kimi-K2.7-Code-4bit"
    mock_get.assert_not_called()


@patch("driving.model_router.httpx.get")
def test_resolve_worker_config_by_alias(mock_get, monkeypatch):
    """M7.1 — resolve_worker_model_config 按 alias 返回不同执行模型。"""
    mock_get.side_effect = Exception("down")  # 所有端点不健康 → 走直连回退
    monkeypatch.setenv("FLIPPED_MODEL_BASE_URL", "http://direct.test/v1")
    monkeypatch.setenv("FLIPPED_ARCHITECT_MODEL", "mlx-community/GLM-5.2-fp8")
    monkeypatch.setenv("FLIPPED_CODER_MODEL", "mlx-community/Kimi-K2.7-Code-4bit")
    _, model_c = resolve_worker_model_config("coder")
    url_a, model_a = resolve_worker_model_config("architect")
    assert model_c == "mlx-community/Kimi-K2.7-Code-4bit"
    assert model_a == "mlx-community/GLM-5.2-fp8"
    assert url_a == "http://direct.test/v1"
