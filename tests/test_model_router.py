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
    monkeypatch.setenv("FLIPPED_CODER_MODEL", "mlx-community/Kimi-K2.7-Code-4bit")

    def side_effect(url, **kwargs):
        if url.startswith("http://proxy.test"):
            return _resp(200, [{"id": "coder"}])
        return _resp(200, [{"id": "mlx-community/Kimi-K2.7-Code-4bit"}])

    mock_get.side_effect = side_effect
    base, model = resolve_worker_model_config()
    assert base == "http://worker-proxy.test/v1"
    assert model == "coder"


@patch("driving.model_router.httpx.get")
def test_resolve_worker_model_config_fallback_direct(mock_get, monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "http://proxy.test/v1")
    monkeypatch.setenv("FLIPPED_MODEL_BASE_URL", "http://direct.test/v1")
    monkeypatch.setenv("OPENHANDS_MODEL", "coder")
    monkeypatch.setenv("FLIPPED_CODER_MODEL", "mlx-community/Kimi-K2.7-Code-4bit")

    def side_effect(url, **kwargs):
        if url.startswith("http://proxy.test"):
            raise TimeoutError("down")
        return _resp(200, [{"id": "mlx-community/Kimi-K2.7-Code-4bit"}])

    mock_get.side_effect = side_effect
    base, model = resolve_worker_model_config()
    assert base == "http://direct.test/v1"
    assert model == "mlx-community/Kimi-K2.7-Code-4bit"


@patch("driving.model_router.httpx.get")
def test_resolve_worker_model_config_defaults_when_env_empty(mock_get, monkeypatch):
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("FLIPPED_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("OPENHANDS_BASE_URL", raising=False)
    monkeypatch.delenv("OPENHANDS_MODEL", raising=False)
    mock_get.side_effect = TimeoutError("down")
    base, model = resolve_worker_model_config()
    assert base == DEFAULT_EXO_URL
    assert model == "mlx-community/Kimi-K2.7-Code-4bit"
