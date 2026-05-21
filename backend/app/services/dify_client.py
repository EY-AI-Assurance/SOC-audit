"""
LLM client — currently wired to Alibaba Bailian (OpenAI-compatible).
To switch providers, replace the body of `call()` only; the rest is unchanged.
"""
import json
from typing import Any

from openai import OpenAI

from app.config import settings


class LLMClient:
    def __init__(self) -> None:
        self._client = OpenAI(
            api_key=settings.bailian_api_key,
            base_url=settings.bailian_base_url,
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
        return response.choices[0].message.content or ""

    def call_json(self, prompt: str, system_prompt: str = "") -> Any:
        """Call the LLM and parse the response as JSON. Strips markdown code fences."""
        raw = self.call(prompt, system_prompt).strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.splitlines()[1:]).rstrip("`").strip()
        return json.loads(raw)


dify_client = LLMClient()
