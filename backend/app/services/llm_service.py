"""SiliconFlow LLM 路由与调用服务"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

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
        self.settings = get_settings()
        self.base_url = self.settings.siliconflow_base_url.rstrip("/")
        self.api_key = self.settings.siliconflow_api_key
        self.primary_model = self.settings.llm_model_deepseek_v32
        self.complex_model = self.settings.llm_model_deepseek_r1

    def pick_model(self, location: str, days: int, preferences: str = "", step: str = "generation") -> str:
        _ = preferences
        text = f"{location} {preferences}".lower()
        multi_country_markers = ["-", "、", ",", " and ", "france", "italy", "switzerland", "germany", "spain", "netherlands", "belgium", "austria", "europe multi-country"]
        multi_country = days > 7 or any(marker in text for marker in multi_country_markers)
        if step == "reflection" and multi_country:
            return self.complex_model
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
    ) -> LLMCallResult:
        if not self.api_key:
            raise ValueError("SILICONFLOW_API_KEY not configured")

        model = self.pick_model(location, days, preferences, step=step)
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
        }
        print(f"[llm-router][pick] step={step}, location={location}, days={days}, model={model}")

        timeout = httpx.Timeout(connect=10.0, read=120.0, write=20.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        content = ((choice.get("message") or {}).get("content") or "").strip()
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        cost_usd = (input_tokens / 1_000_000) * 0.27 + (output_tokens / 1_000_000) * 0.42
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
