"""DeepSeek calls for JAD AI: a streamed chat answer and a small JSON request."""

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def model_name() -> str:
    return (settings.jad_ai_model or settings.deepseek_model).strip()


def is_configured() -> bool:
    return bool(settings.jad_ai_enabled and settings.deepseek_api_key)


@dataclass
class StreamResult:
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    cached_prompt_tokens: int | None = None
    completion_tokens: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _url() -> str:
    return f"{settings.deepseek_api_base_url.rstrip('/')}/chat/completions"


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.deepseek_api_key}", "Content-Type": "application/json"}


async def stream_chat(messages: list[dict[str, str]], result: StreamResult) -> AsyncIterator[str]:
    """Yield answer text as it arrives; usage and finish reason land in `result`."""
    payload = {
        "model": model_name(),
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": 0.4,
        "max_tokens": settings.jad_ai_max_answer_tokens,
    }
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", _url(), headers=_headers(), json=payload) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", errors="ignore")[:300]
                raise RuntimeError(f"DeepSeek returned {response.status_code}: {body}")
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                usage = event.get("usage")
                if usage:
                    result.prompt_tokens = usage.get("prompt_tokens")
                    result.completion_tokens = usage.get("completion_tokens")
                    result.cached_prompt_tokens = usage.get("prompt_cache_hit_tokens") or (
                        (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
                    )
                for choice in event.get("choices") or []:
                    if choice.get("finish_reason"):
                        result.finish_reason = choice["finish_reason"]
                    text = (choice.get("delta") or {}).get("content")
                    if text:
                        yield text


async def json_chat(system: str, user: str, *, max_tokens: int = 400) -> dict[str, Any]:
    payload = {
        "model": model_name(),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
        "temperature": 0.5,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(_url(), headers=_headers(), json=payload)
        response.raise_for_status()
    content = (response.json()["choices"][0]["message"]["content"] or "").strip()
    if content.startswith("```"):
        content = content.strip("`").removeprefix("json").strip()
    return json.loads(content)
