"""SiliconFlow LLM 路由与调用服务"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional, Tuple

import httpx

from ..config import get_settings


@dataclass
class LLMCallResult:
    content: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str
    raw: Dict[str, Any]


class LLMRouter:
    def __init__(self) -> None:
        s = self.settings = get_settings()
        # provider 无关：LLM_* 优先，留空则回退 SILICONFLOW_*（充值后改回一个变量即可切换）
        self.base_url = (s.llm_base_url or s.siliconflow_base_url).rstrip("/")
        self.api_key = s.llm_api_key or s.siliconflow_api_key
        self.primary_model = s.llm_model_content or s.llm_model_deepseek_v32
        self.complex_model = s.llm_model_deepseek_r1
        self.max_tokens = int(getattr(s, "llm_max_tokens", 8192) or 8192)
        # Ollama 的 thinking 模型（如 qwen3.5）必须关掉思维链，否则 token 全烧在 reasoning、content 为空
        self.disable_thinking = bool(getattr(s, "llm_disable_thinking", False))
        # 只有真的打 SiliconFlow 才算钱；本地 Ollama 免费
        self._bill = "siliconflow" in self.base_url
        print(f"[llm-router][init] base_url={self.base_url}, content_model={self.primary_model}, "
              f"tool_model={getattr(s, 'llm_model_tool', '-')}, disable_thinking={self.disable_thinking}")

    def _extra(self) -> Dict[str, Any]:
        """provider 专属的附加字段。"""
        return {"think": False} if self.disable_thinking else {}

    def _cost(self, input_tokens: int, output_tokens: int) -> float:
        if not self._bill:
            return 0.0
        return (input_tokens / 1_000_000) * 0.27 + (output_tokens / 1_000_000) * 0.42

    def pick_model(self, location: str, days: int, preferences: str = "", step: str = "generation") -> str:
        # 默认恒用更快的 V3.2；仅当显式开启 LLM_ALLOW_R1 时，才对多国/长行程的
        # generation 步骤启用推理模型 R1（慢）。reflection 段已下线。
        if not getattr(self.settings, "llm_allow_r1", False):
            return self.primary_model
        text = f"{location} {preferences}".lower()
        multi_country_markers = ["-", "、", ",", " and ", "france", "italy", "switzerland", "germany", "spain", "netherlands", "belgium", "austria", "europe multi-country"]
        multi_country = days > 7 or any(marker in text for marker in multi_country_markers)
        return self.complex_model if multi_country and step == "generation" else self.primary_model

    async def generate_json(
        self,
        *,
        location: str,
        days: int,
        preferences: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        step: str = "generation",
        model: str | None = None,
    ) -> LLMCallResult:
        if not self.api_key:
            raise ValueError("SILICONFLOW_API_KEY not configured")

        model = model or self.pick_model(location, days, preferences, step=step)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "max_tokens": self.max_tokens,
            **self._extra(),
        }
        print(f"[llm-router][pick] step={step}, location={location}, days={days}, model={model}")

        # generation 需产出大段结构化 JSON，读超时给足；SSE 心跳保活 + nginx 600s 覆盖此窗口。
        timeout = httpx.Timeout(connect=10.0, read=300.0, write=20.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        content = ((choice.get("message") or {}).get("content") or "").strip()
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        cost_usd = self._cost(input_tokens, output_tokens)
        print(
            f"[llm-cost] step={step}, model={model}, input_tokens={input_tokens}, output_tokens={output_tokens}, cost_usd={cost_usd:.6f}"
        )
        return LLMCallResult(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            model=model,
            raw=data,
        )

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        temperature: float = 0.3,
        max_tokens: int = 1500,
        timeout_s: float = 120.0,
        model: str | None = None,
        tool_choice: str = "auto",
    ) -> Dict[str, Any]:
        """OpenAI 兼容的 function-calling 一轮对话（供 supervisor 工具循环）。

        用**专用 tool 模型**（默认 Qwen2.5-72B-Instruct），与内容模型 V3.2 分工——
        对齐 StockPilot（`SILICONFLOW_TOOL_MODEL` vs `SILICONFLOW_MODEL`）。
        返回原始 message dict：`{"content": str|None, "tool_calls": [...]|None}`。
        """
        if not self.api_key:
            raise ValueError("SILICONFLOW_API_KEY not configured")

        model = model or getattr(self.settings, "llm_model_tool", None) or self.primary_model
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **self._extra(),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        timeout = httpx.Timeout(connect=10.0, read=timeout_s, write=20.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        usage = data.get("usage") or {}
        print(
            f"[llm-cost] step=supervisor(tools), model={model}, "
            f"input_tokens={usage.get('prompt_tokens', 0)}, output_tokens={usage.get('completion_tokens', 0)}"
        )
        return msg

    async def generate_json_stream(
        self,
        *,
        location: str,
        days: int,
        preferences: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        step: str = "generation",
        model: str | None = None,
    ) -> AsyncIterator[Tuple[str, Any]]:
        """流式版 generate_json。

        产出序列：0 或多个 ``("delta", <文本增量>)``，最后一个 ``("result", LLMCallResult)``。
        累计完整 content 后与非流式一致地返回（调用方仍在末尾解析 JSON）。
        provider/网络异常向上抛出，由调用方回退到非流式。
        """
        if not self.api_key:
            raise ValueError("SILICONFLOW_API_KEY not configured")

        model = model or self.pick_model(location, days, preferences, step=step)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": self.max_tokens,
            **self._extra(),
        }
        print(f"[llm-router][pick] step={step}(stream), location={location}, days={days}, model={model}")

        # read 超时按 chunk 间隔计：token 持续到达即不触发；给足以覆盖首字延迟。
        timeout = httpx.Timeout(connect=10.0, read=300.0, write=20.0, pool=10.0)
        content_parts: list[str] = []
        usage: Dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", f"{self.base_url}/chat/completions", headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        if data == "[DONE]":
                            break
                        continue
                    try:
                        chunk = json.loads(data)
                    except Exception:
                        continue
                    choice = (chunk.get("choices") or [{}])[0]
                    delta = ((choice.get("delta") or {}).get("content")) or ""
                    if delta:
                        content_parts.append(delta)
                        yield ("delta", delta)
                    if chunk.get("usage"):
                        usage = chunk["usage"]

        content = "".join(content_parts).strip()
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        cost_usd = self._cost(input_tokens, output_tokens)
        print(
            f"[llm-cost] step={step}(stream), model={model}, input_tokens={input_tokens}, output_tokens={output_tokens}, cost_usd={cost_usd:.6f}"
        )
        yield (
            "result",
            LLMCallResult(
                content=content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                model=model,
                raw={"usage": usage, "streamed": True},
            ),
        )


_router: Optional[LLMRouter] = None


class _LegacyLLMAdapter:
    """兼容旧代码的最小适配器。"""

    def __init__(self, router: LLMRouter) -> None:
        self.router = router
        self.provider = "siliconflow"
        self.model = router.primary_model

    def run(self, prompt: str) -> str:
        # 保留旧接口，便于历史 agent 模块导入；不建议新逻辑继续依赖它。
        _ = prompt
        raise RuntimeError("旧版 get_llm/run 接口已弃用，请改用 get_llm_router().generate_json()")


def get_llm_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
        print("✅ LLM Router 初始化成功")
    return _router


def get_llm() -> _LegacyLLMAdapter:
    """兼容旧调用，避免历史 agent 模块导入失败。"""
    return _LegacyLLMAdapter(get_llm_router())
