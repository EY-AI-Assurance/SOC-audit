"""
Dify API client — stub.

The public interface (call / call_json) is stable.
Fill in _completion / _chat / _workflow once the EY Dify endpoint is confirmed.
"""
import json
from typing import Any

import requests

from app.config import settings


class DifyClient:
    def __init__(self) -> None:
        self.api_url = settings.dify_api_url
        self.api_key = settings.dify_api_key
        self.mode    = settings.dify_call_mode
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def call(self, prompt: str, system_prompt: str = "") -> str:
        """Send a prompt and return the raw response text."""
        if self.mode == "completion":
            return self._completion(prompt, system_prompt)
        if self.mode == "chat":
            return self._chat(prompt, system_prompt)
        if self.mode == "workflow":
            return self._workflow(prompt)
        raise ValueError(f"Unknown dify_call_mode: {self.mode!r}")

    def call_json(self, prompt: str, system_prompt: str = "") -> Any:
        """Call Dify and parse the response as JSON. Strips markdown code fences."""
        raw = self.call(prompt, system_prompt).strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.splitlines()[1:]).rstrip("`").strip()
        return json.loads(raw)

    # ── TODO: implement after EY IT confirms the endpoint ────────────────────

    def _completion(self, prompt: str, system_prompt: str) -> str:
        raise NotImplementedError("Dify completion endpoint not yet configured")

    def _chat(self, prompt: str, system_prompt: str) -> str:
        raise NotImplementedError("Dify chat endpoint not yet configured")

    def _workflow(self, prompt: str) -> str:
        raise NotImplementedError("Dify workflow endpoint not yet configured")


dify_client = DifyClient()
