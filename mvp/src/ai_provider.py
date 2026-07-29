"""
AI Provider 抽象层 — 直接 HTTP API 调用
用户自带 API Key，后端透传

支持 Anthropic Messages API 和 OpenAI Chat Completions API
"""

import json
import time
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

import httpx


# ── Provider 枚举 ───────────────────────────────────────

class ProviderType:
    ANTHROPIC = "anthropic"
    OPENAI = "openai"

    @staticmethod
    def detect(api_key: str) -> str:
        """根据 key 前缀自动判断 provider"""
        if api_key.startswith("sk-ant-"):
            return ProviderType.ANTHROPIC
        elif api_key.startswith("sk-"):
            return "deepseek"  # DeepSeek / OpenAI-compatible
        return ProviderType.ANTHROPIC  # 默认


# ── 调用结果 ────────────────────────────────────────────

class AIResult:
    def __init__(self, text: str, input_tokens: int, output_tokens: int, latency_ms: float):
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.latency_ms = latency_ms

    def to_dict(self):
        return {
            "text": self.text,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
        }


class StreamResult:
    """流式结果：异步迭代器 + token 信息在结束时获得"""
    def __init__(self, stream: AsyncIterator[str]):
        self._stream = stream
        self.input_tokens = 0
        self.output_tokens = 0
        self.latency_ms = 0.0
        self._full_text = ""

    def __aiter__(self):
        return self._stream.__aiter__()

    async def __anext__(self):
        return await self._stream.__anext__()

    async def collect(self) -> AIResult:
        """消费整个流，返回完整结果"""
        chunks = []
        async for chunk in self._stream:
            if chunk is not None and chunk != "":  # 过滤 None/空串 防止 join 崩溃
                chunks.append(chunk)
        self._full_text = "".join(chunks)
        return AIResult(self._full_text, self.input_tokens, self.output_tokens, self.latency_ms)


# ── 抽象基类 ────────────────────────────────────────────

class AIProvider(ABC):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(120.0), trust_env=False)

    @abstractmethod
    async def chat(
        self, model: str, system: str, messages: list[dict],
        max_tokens: int = 4096, temperature: float = 0.7,
    ) -> AIResult:
        """非流式调用，返回完整结果"""
        ...

    @abstractmethod
    async def chat_stream(
        self, model: str, system: str, messages: list[dict],
        max_tokens: int = 4096, temperature: float = 0.7,
    ) -> StreamResult:
        """流式调用，返回异步迭代器"""
        ...

    async def close(self):
        await self.client.aclose()


# ── Anthropic 实现 ──────────────────────────────────────

class AnthropicProvider(AIProvider):
    BASE = "https://api.anthropic.com/v1/messages"

    def _build_body(self, model: str, system: str, messages: list[dict],
                    max_tokens: int, temperature: float) -> dict:
        # 转换 OpenAI 格式消息到 Anthropic 格式
        anthropic_messages = []
        for m in messages:
            role = m["role"]
            if role == "system":
                continue  # system 在顶层
            anthropic_messages.append({"role": role, "content": m["content"]})

        return {
            "model": model,
            "system": system,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

    async def chat(self, model: str, system: str, messages: list[dict],
                   max_tokens: int = 4096, temperature: float = 0.7) -> AIResult:
        body = self._build_body(model, system, messages, max_tokens, temperature)
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        t0 = time.time()
        resp = await self.client.post(self.BASE, json=body, headers=headers)
        latency = (time.time() - t0) * 1000

        if resp.status_code != 200:
            raise RuntimeError(f"Anthropic API error {resp.status_code}: {resp.text}")

        data = resp.json()
        text = data["content"][0]["text"]
        return AIResult(
            text=text,
            input_tokens=data["usage"]["input_tokens"],
            output_tokens=data["usage"]["output_tokens"],
            latency_ms=latency,
        )

    async def chat_stream(self, model: str, system: str, messages: list[dict],
                          max_tokens: int = 4096, temperature: float = 0.7) -> StreamResult:
        body = self._build_body(model, system, messages, max_tokens, temperature)
        body["stream"] = True
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        t0 = time.time()
        resp = await self.client.send(
            self.client.build_request("POST", self.BASE, json=body, headers=headers),
            stream=True,
        )

        if resp.status_code != 200:
            body_text = await resp.aread()
            raise RuntimeError(f"Anthropic API error {resp.status_code}: {body_text}")

        async def event_stream():
            nonlocal resp
            input_tokens = 0
            output_tokens = 0
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    if data.get("type") == "content_block_delta":
                        text = data.get("delta", {}).get("text", "")
                        if text:
                            yield text
                    elif data.get("type") == "message_start":
                        input_tokens = data.get("message", {}).get("usage", {}).get("input_tokens", 0)
                    elif data.get("type") == "message_delta":
                        output_tokens = data.get("usage", {}).get("output_tokens", 0)

        stream = StreamResult(event_stream())
        stream.latency_ms = (time.time() - t0) * 1000

        # 触发流以收集 token 数据，但在 collect() 时才执行
        return stream


# ── OpenAI 实现 ─────────────────────────────────────────

class DeepSeekProvider(AIProvider):
    """DeepSeek API — OpenAI 兼容协议"""
    BASE = "https://api.deepseek.com/v1/chat/completions"

    async def chat(self, model: str, system: str, messages: list[dict],
                   max_tokens: int = 4096, temperature: float = 0.7) -> AIResult:
        full_messages = [{"role": "system", "content": system}] + messages
        body = {"model": model, "messages": full_messages, "max_tokens": max_tokens,
                "temperature": temperature, "stream": False}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        t0 = time.time()
        resp = await self.client.post(self.BASE, json=body, headers=headers)
        latency = (time.time() - t0) * 1000
        if resp.status_code != 200:
            raise RuntimeError(f"DeepSeek API error {resp.status_code}: {resp.text}")
        data = resp.json()
        msg = data["choices"][0]["message"]
        text = msg.get("content") or msg.get("reasoning_content") or ""
        return AIResult(text=text,
            input_tokens=data["usage"]["prompt_tokens"],
            output_tokens=data["usage"]["completion_tokens"],
            latency_ms=latency)

    async def chat_stream(self, model: str, system: str, messages: list[dict],
                          max_tokens: int = 4096, temperature: float = 0.7) -> StreamResult:
        full_messages = [{"role": "system", "content": system}] + messages
        body = {"model": model, "messages": full_messages, "max_tokens": max_tokens,
                "temperature": temperature, "stream": True}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        t0 = time.time()
        resp = await self.client.send(
            self.client.build_request("POST", self.BASE, json=body, headers=headers), stream=True)
        if resp.status_code != 200:
            body_text = await resp.aread()
            raise RuntimeError(f"DeepSeek API error {resp.status_code}: {body_text}")
        async def event_stream():
            nonlocal resp
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    ds = line[6:]
                    if ds == "[DONE]":
                        break
                    data = json.loads(ds)
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    if "content" in delta and delta["content"]:
                        yield delta["content"]
                    elif "reasoning_content" in delta and delta["reasoning_content"]:
                        yield delta["reasoning_content"]
        return StreamResult(event_stream())


class OpenAIProvider(DeepSeekProvider):
    """OpenAI API — 继承 DeepSeek 实现（协议相同，仅 BASE 不同）"""
    BASE = "https://api.openai.com/v1/chat/completions"

    async def chat(self, model: str, system: str, messages: list[dict],
                   max_tokens: int = 4096, temperature: float = 0.7) -> AIResult:
        full_messages = [{"role": "system", "content": system}] + messages
        body = {
            "model": model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        t0 = time.time()
        resp = await self.client.post(self.BASE, json=body, headers=headers)
        latency = (time.time() - t0) * 1000

        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text}")

        data = resp.json()
        msg = data["choices"][0]["message"]
        text = msg.get("content") or msg.get("reasoning_content") or ""
        return AIResult(
            text=text,
            input_tokens=data["usage"]["prompt_tokens"],
            output_tokens=data["usage"]["completion_tokens"],
            latency_ms=latency,
        )

    async def chat_stream(self, model: str, system: str, messages: list[dict],
                          max_tokens: int = 4096, temperature: float = 0.7) -> StreamResult:
        full_messages = [{"role": "system", "content": system}] + messages
        body = {
            "model": model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        t0 = time.time()
        resp = await self.client.send(
            self.client.build_request("POST", self.BASE, json=body, headers=headers),
            stream=True,
        )

        if resp.status_code != 200:
            body_text = await resp.aread()
            raise RuntimeError(f"OpenAI API error {resp.status_code}: {body_text}")

        input_tokens = 0
        output_tokens = 0

        async def event_stream():
            nonlocal input_tokens, output_tokens
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    data = json.loads(data_str)
                    choice = data.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    if "content" in delta:
                        yield delta["content"]
                    if "usage" in data and data["usage"]:
                        input_tokens = data["usage"].get("prompt_tokens", 0)
                        output_tokens = data["usage"].get("completion_tokens", 0)

        stream = StreamResult(event_stream())
        stream.latency_ms = (time.time() - t0) * 1000
        return stream


# ── Provider 工厂 ───────────────────────────────────────

def create_provider(api_key: str, provider_type: str = None) -> AIProvider:
    if provider_type is None:
        provider_type = ProviderType.detect(api_key)
    if provider_type == ProviderType.OPENAI:
        return OpenAIProvider(api_key)
    if provider_type == "deepseek":
        return DeepSeekProvider(api_key)
    return AnthropicProvider(api_key)


# ── 默认模型映射 ────────────────────────────────────────

DEFAULT_MODELS = {
    ProviderType.ANTHROPIC: {"small": "claude-sonnet-5-20251001", "large": "claude-opus-4-8"},
    ProviderType.OPENAI: {"small": "gpt-4o-mini", "large": "gpt-4o"},
    "deepseek": {"small": "deepseek-v4-flash", "large": "deepseek-v4-flash"},
}
VALID_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner",
                "gpt-4o", "gpt-4o-mini", "claude-sonnet-5-20251001", "claude-opus-4-8"}

def resolve_model(api_key: str, model_name: str = None, size: str = "small") -> str:
    """解析模型名——用户指定 > 默认 > 回退"""
    if model_name and model_name.strip():
        return model_name.strip()
    pt = ProviderType.detect(api_key)
    return DEFAULT_MODELS.get(pt, DEFAULT_MODELS["deepseek"])[size]


def get_default_model(api_key: str, size: str = "small") -> str:
    """size: small(AI-1/总结) | large(AI-2)"""
    pt = ProviderType.detect(api_key)
    return DEFAULT_MODELS[pt][size]
