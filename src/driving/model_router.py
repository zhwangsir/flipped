"""Model endpoint routing and health checks for M5.3.

Provides runtime selection between the LiteLLM proxy and a direct exo endpoint,
plus helper functions used by both the orchestrator LLM factory and the
OpenHands Worker.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_PROXY_URL = "http://localhost:4000/v1"
DEFAULT_EXO_URL = "http://100.64.201.37:52415/v1"
DEFAULT_WORKER_PROXY_URL = "http://host.docker.internal:4000/v1"


def _api_key() -> str | None:
    # M89 关键修复:优先 LITELLM_MASTER_KEY。
    # LiteLLM proxy(:4000)需要 master_key 鉴权;exo 直连不鉴权(接受任意 key)。
    # 之前 EXO_API_KEY="dummy" 优先,导致 is_model_available 检查 proxy 时 400 鉴权失败,
    # Worker 误判 proxy 不可用 → 走直连 exo → reasoning 未关 → 卡死。
    return os.environ.get("LITELLM_MASTER_KEY") or os.environ.get("EXO_API_KEY")


def _model_id_for_alias(alias: str) -> str:
    env_map = {
        # F8 实测:集群当前 LAUNCH 的是 fp8(DQ4plus-q8 无实例 404)——默认对齐现实
        "architect": os.environ.get("FLIPPED_ARCHITECT_MODEL", "mlx-community/GLM-5.2-fp8"),
        "coder": os.environ.get("FLIPPED_CODER_MODEL", "mlx-community/Kimi-K2.7-Code-4bit"),
    }
    return env_map.get(alias, alias)


def _headers() -> dict[str, str] | None:
    key = _api_key()
    return {"Authorization": f"Bearer {key}"} if key else None


def is_endpoint_healthy(base_url: str, timeout: float = 5.0) -> bool:
    """Check whether an OpenAI-compatible endpoint is reachable."""
    url = f"{base_url.rstrip('/')}/models"
    try:
        r = httpx.get(url, headers=_headers(), timeout=timeout, follow_redirects=True, trust_env=False)
        return r.status_code == 200
    except Exception:
        return False


def is_model_available(base_url: str, model_id: str, timeout: float = 5.0) -> bool:
    """Check whether a specific model id is listed by the endpoint."""
    url = f"{base_url.rstrip('/')}/models"
    try:
        r = httpx.get(url, headers=_headers(), timeout=timeout, follow_redirects=True, trust_env=False)
        if r.status_code != 200:
            return False
        data = r.json().get("data", [])
        ids = [m.get("id") for m in data if isinstance(m, dict)]
        return model_id in ids
    except Exception:
        return False


def resolve_model_config(alias: str) -> tuple[str, str]:
    """Pick the best endpoint and model id for an orchestrator LLM alias.

    Preference order:
      1. LiteLLM proxy if healthy and the alias is listed there.
      2. Direct exo URL if healthy.
      3. Direct exo URL (best-effort fallback) otherwise.
    """
    proxy_url = os.environ.get("LITELLM_BASE_URL", DEFAULT_PROXY_URL)
    direct_url = os.environ.get("FLIPPED_MODEL_BASE_URL", DEFAULT_EXO_URL)
    full_model = _model_id_for_alias(alias)

    if is_endpoint_healthy(proxy_url) and is_model_available(proxy_url, alias):
        return proxy_url, alias

    if is_endpoint_healthy(direct_url):
        return direct_url, full_model

    # Best-effort fallback to direct exo so the LLM call can fail later with a
    # clear network error rather than silently picking a broken proxy.
    return direct_url, full_model


def resolve_worker_model_config(alias: str = "coder") -> tuple[str, str]:
    """Pick the best endpoint and model name for the OpenHands Worker.

    The proxy is checked from the host perspective (localhost:4000) but the
    runtime URL returned for the worker points to the docker-host gateway so
    the OpenHands container can reach the LiteLLM proxy on the host.

    M101 防御性修复：FLIPPED_USE_LOCAL_WORKER=1 时直接走 exo 直连，跳过 LiteLLM
    proxy 检测。否则当 LiteLLM proxy 健康时会返回 host.docker.internal:4000
    （Docker-only 主机名），宿主机 local_worker 无法 DNS 解析 → ConnectError。
    """
    direct_url = os.environ.get("FLIPPED_MODEL_BASE_URL") or os.environ.get("OPENHANDS_BASE_URL") or DEFAULT_EXO_URL
    direct_model = _model_id_for_alias(alias)

    # local_worker 模式：直接走 exo 直连，避免 host.docker.internal 陷阱
    if os.environ.get("FLIPPED_USE_LOCAL_WORKER") == "1":
        return direct_url, direct_model

    proxy_health_url = os.environ.get("LITELLM_BASE_URL", DEFAULT_PROXY_URL)
    proxy_runtime_url = os.environ.get("OPENHANDS_PROXY_BASE_URL", DEFAULT_WORKER_PROXY_URL)
    proxy_model = os.environ.get("OPENHANDS_MODEL", "coder") if alias == "coder" else alias

    if is_endpoint_healthy(proxy_health_url) and is_model_available(proxy_health_url, proxy_model):
        return proxy_runtime_url, proxy_model

    if is_endpoint_healthy(direct_url):
        return direct_url, direct_model

    return direct_url, direct_model
