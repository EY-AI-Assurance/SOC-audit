"""LLM client for OpenAI-compatible providers and Dify Chatflow."""
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
        self._client: OpenAI | None = None
        self._model = settings.bailian_model

    def call(self, prompt: str, system_prompt: str = "") -> str:
        """Send a prompt and return the raw response text."""
        if settings.llm_provider == "dify":
            return self._call_dify(prompt)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = self._openai_client().chat.completions.create(
            model=self._model,
            messages=messages,
        )
        raw = response.choices[0].message.content or ""
        print(f"[LLM] raw response (first 500 chars): {raw[:500]}", flush=True)
        return raw

    def _openai_client(self) -> OpenAI:
        if self._client is not None:
            return self._client

        if not settings.bailian_api_key:
            raise ValueError("BAILIAN_API_KEY is empty. Set it in backend/.env before using LLM_PROVIDER=openai_compatible.")

        self._client = OpenAI(
            api_key=settings.bailian_api_key,
            base_url=settings.bailian_base_url,
            http_client=httpx.Client(verify=False, timeout=120.0),
        )
        return self._client

    def _call_dify(self, prompt: str) -> str:
        if not settings.dify_base_url:
            raise ValueError("DIFY_BASE_URL is empty. Set it in backend/.env before using LLM_PROVIDER=dify.")
        if not settings.dify_api_key:
            raise ValueError("DIFY_API_KEY is empty. Set it in backend/.env before using LLM_PROVIDER=dify.")

        url = settings.dify_base_url.rstrip("/") + "/chat-messages"

        headers = {
            "Authorization": f"Bearer {settings.dify_api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "inputs": {},
            "query": prompt,
            "response_mode": "blocking",
            "conversation_id": "",
            "user": settings.dify_user,
        }

        try:
            with httpx.Client(timeout=180.0) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.ConnectError as exc:
            raise ConnectionError(
                f"Cannot connect to Dify API at {url}. "
                "Check whether you are connected to the company network/VPN and whether DIFY_BASE_URL is correct."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Dify API returned HTTP {exc.response.status_code}: {exc.response.text[:500]}"
            ) from exc

        data = response.json()
        raw = data.get("answer", "")
        print(f"[DIFY] raw response (first 500 chars): {raw[:500]}", flush=True)
        return raw

    def call_json(self, prompt: str, system_prompt: str = "") -> Any:
        """Call the LLM and parse the response as JSON.
        Strips Qwen3 thinking tags and markdown code fences before parsing."""
        raw = self.call(prompt, system_prompt).strip()
        if not raw:
            raise ValueError("LLM returned an empty response. The prompt may be too long or the API request failed without content.")

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
