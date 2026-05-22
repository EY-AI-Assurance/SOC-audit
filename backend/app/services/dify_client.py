"""
LLM client — currently wired to iFlytek MaaS (OpenAI-compatible).
To switch providers, replace the body of `call()` only; the rest is unchanged.
"""
import json
import logging
import re
from typing import Any

import httpx
from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self) -> None:
        self._client = OpenAI(
            api_key=settings.bailian_api_key,
            base_url=settings.bailian_base_url,
            http_client=httpx.Client(verify=False, timeout=120.0),
        )
        self._model = settings.bailian_model

    def call(self, prompt: str, system_prompt: str = "") -> str:
        """Send a prompt and return the raw response text."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
        )
        raw = response.choices[0].message.content or ""
        print(f"[LLM] raw response (first 500 chars): {raw[:500]}", flush=True)
        return raw

    def call_json(self, prompt: str, system_prompt: str = "") -> Any:
        """Call the LLM and parse the response as JSON.
        Strips Qwen3 thinking tags and markdown code fences before parsing."""
        raw = self.call(prompt, system_prompt).strip()

        # Strip Qwen3 thinking blocks: <think>...</think>
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        # Strip markdown code fences
        if raw.startswith("```"):
            raw = "\n".join(raw.splitlines()[1:]).rstrip("`").strip()

        print(f"[LLM] cleaned JSON (first 500 chars): {raw[:500]}", flush=True)

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            print(f"[LLM] JSON parse FAILED. Full response:\n{raw}", flush=True)
            raise


dify_client = LLMClient()
