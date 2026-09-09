from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from .models import ProviderConfig
from .config import MAX_LLM_OUTPUT_TOKENS
from .secrets import decrypt_secret


SYSTEM_PROMPT = """你是 Insight Studio 的数据分析助手，帮助非专业用户理解数据、澄清问题、解释统计结果，并把结论写成可审阅的报告语言。
必须遵守：不虚构数字；区分事实、推断和建议；需要计算时要求系统工具执行；先给结论，再给依据和下一步；报告发布前需人工确认。
对话回复应凝练，通常不超过 1500 个中文字；详细表格和长篇内容应放入可编辑报告，不要在对话中重复整份报告。
"""


DEEPSEEK_PRICING_CNY_PER_MILLION = {
    "deepseek-v4-flash": {"cache_hit_input": 0.02, "cache_miss_input": 1.0, "output": 2.0},
    "deepseek-v4-pro": {"cache_hit_input": 0.025, "cache_miss_input": 3.0, "output": 6.0},
}


@dataclass(frozen=True)
class CompletionResult:
    content: str
    request_id: str
    model: str
    usage: dict[str, int]
    estimated_cost_cny: float
    latency_ms: int
    pricing: dict[str, Any]
    usage_available: bool = True

    def as_meta(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id, "model": self.model, **self.usage,
            "estimated_cost_cny": self.estimated_cost_cny, "latency_ms": self.latency_ms,
            "pricing": self.pricing, "usage_available": self.usage_available,
        }


def _headers(config: ProviderConfig) -> dict[str, str]:
    return {"Authorization": f"Bearer {decrypt_secret(config.encrypted_api_key)}", "Content-Type": "application/json"}


async def complete(config: ProviderConfig, messages: list[dict[str, str]], context: str, request_options: dict[str, Any] | None = None) -> CompletionResult:
    if config.provider == "openai":
        return await _openai_response(config, messages, context, request_options or {})
    if config.provider == "deepseek":
        return await _deepseek_chat(config, messages, context, request_options or {})
    raise ValueError(f"Unsupported provider: {config.provider}")


async def _openai_response(config: ProviderConfig, messages: list[dict[str, str]], context: str, request_options: dict[str, Any]) -> CompletionResult:
    payload: dict[str, Any] = {
        "model": config.model,
        "instructions": f"{SYSTEM_PROMPT}\n\n当前数据上下文：\n{context}",
        "input": [{"role": item["role"], "content": item["content"]} for item in messages if item["role"] in {"user", "assistant"}],
        "store": False,
        "max_output_tokens": int(request_options.get("max_tokens", MAX_LLM_OUTPUT_TOKENS)),
    }
    effort = (config.options or {}).get("reasoning_effort")
    if effort:
        payload["reasoning"] = {"effort": effort}
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{config.base_url.rstrip('/')}/responses", headers=_headers(config), json=payload)
        response.raise_for_status()
        body = response.json()
    texts = [body["output_text"]] if body.get("output_text") else []
    if not texts:
        for item in body.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    texts.append(content["text"])
    raw_usage = body.get("usage") or {}
    usage = {
        "prompt_tokens": int(raw_usage.get("input_tokens", 0)), "cache_hit_tokens": int(raw_usage.get("input_tokens_details", {}).get("cached_tokens", 0)),
        "cache_miss_tokens": max(0, int(raw_usage.get("input_tokens", 0)) - int(raw_usage.get("input_tokens_details", {}).get("cached_tokens", 0))),
        "completion_tokens": int(raw_usage.get("output_tokens", 0)),
        "total_tokens": int(raw_usage.get("total_tokens", raw_usage.get("input_tokens", 0) + raw_usage.get("output_tokens", 0))),
    }
    return CompletionResult(
        content="\n".join(texts) or "模型返回了响应，但没有可显示的文本。",
        request_id=str(body.get("id", "")), model=str(body.get("model", config.model)), usage=usage,
        estimated_cost_cny=0.0, latency_ms=max(1, round((time.perf_counter() - started) * 1000)),
        pricing={"currency": "CNY", "status": "not_configured"}, usage_available=bool(body.get("usage")),
    )


async def _deepseek_chat(config: ProviderConfig, messages: list[dict[str, str]], context: str, request_options: dict[str, Any]) -> CompletionResult:
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\n当前数据上下文：\n{context}"}, *messages],
        "stream": False,
        "max_tokens": int(request_options.get("max_tokens", MAX_LLM_OUTPUT_TOKENS)),
        "thinking": request_options.get("thinking", (config.options or {}).get("thinking", {"type": "disabled"})),
    }
    if request_options.get("response_format"):
        payload["response_format"] = request_options["response_format"]
    if "temperature" in (config.options or {}):
        payload["temperature"] = config.options["temperature"]
    if "thinking" in (config.options or {}):
        payload["thinking"] = config.options["thinking"]
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{config.base_url.rstrip('/')}/chat/completions", headers=_headers(config), json=payload)
        response.raise_for_status()
        body = response.json()
    raw_usage = body.get("usage") or {}
    prompt_tokens = int(raw_usage.get("prompt_tokens", 0))
    cache_hit_tokens = int(raw_usage.get("prompt_cache_hit_tokens", 0))
    cache_miss_tokens = int(raw_usage.get("prompt_cache_miss_tokens", max(0, prompt_tokens - cache_hit_tokens)))
    completion_tokens = int(raw_usage.get("completion_tokens", 0))
    rates = DEEPSEEK_PRICING_CNY_PER_MILLION.get(config.model, {})
    cost = (
        cache_hit_tokens * float(rates.get("cache_hit_input", 0))
        + cache_miss_tokens * float(rates.get("cache_miss_input", 0))
        + completion_tokens * float(rates.get("output", 0))
    ) / 1_000_000
    usage = {
        "prompt_tokens": prompt_tokens, "cache_hit_tokens": cache_hit_tokens,
        "cache_miss_tokens": cache_miss_tokens, "completion_tokens": completion_tokens,
        "total_tokens": int(raw_usage.get("total_tokens", prompt_tokens + completion_tokens)),
    }
    return CompletionResult(
        content=body["choices"][0]["message"]["content"], request_id=str(body.get("id", "")),
        model=str(body.get("model", config.model)), usage=usage, estimated_cost_cny=round(cost, 8),
        latency_ms=max(1, round((time.perf_counter() - started) * 1000)),
        pricing={"currency": "CNY", "unit": "per_million_tokens", "rates": rates, "verified_on": "2026-08-14"},
        usage_available=bool(body.get("usage")),
    )


async def test_provider(config: ProviderConfig) -> tuple[bool, str, int | None]:
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"{config.base_url.rstrip('/')}/models", headers=_headers(config))
            response.raise_for_status()
        elapsed = int((time.perf_counter() - started) * 1000)
        return True, f"连接成功，模型服务可访问（{response.status_code}）", elapsed
    except Exception as exc:
        return False, f"连接失败：{type(exc).__name__}: {str(exc)[:180]}", None
