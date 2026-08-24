"""LLM clients for immutable API configuration snapshots."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from openai import OpenAI

logger = logging.getLogger(__name__)


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "The API request timed out"
    if isinstance(exc, httpx.ConnectError):
        return "Could not connect to the API. Check the URL, network, and VPN."
    return str(exc)[:500]


class LLMClient:
    def __init__(self, config: dict) -> None:
        self.config = dict(config)
        self._client: OpenAI | None = None

    def call(self, prompt: str, system_prompt: str = "") -> str:
        if self.config["protocol"] == "dify":
            return self._call_dify(prompt)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = self._openai_client().chat.completions.create(
                model=self.config["model"],
                messages=messages,
            )
        except Exception as exc:
            raise RuntimeError(self._redact(_safe_error(exc))) from exc
        raw = response.choices[0].message.content or ""
        logger.info("LLM returned %d characters", len(raw))
        return raw

    def _openai_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.config["api_key"],
                base_url=self.config["base_url"],
                http_client=httpx.Client(
                    verify=self.config.get("verify_tls", True),
                    timeout=120.0,
                ),
            )
        return self._client

    def _call_dify(self, prompt: str) -> str:
        url = self.config["base_url"].rstrip("/") + "/chat-messages"
        headers = {
            "Authorization": f"Bearer {self.config['api_key']}",
            "Content-Type": "application/json",
        }
        payload = {
            "inputs": {},
            "query": prompt,
            "response_mode": "blocking",
            "conversation_id": "",
            "user": self.config.get("dify_user") or "soc-audit-local",
        }
        try:
            with httpx.Client(
                timeout=180.0,
                verify=self.config.get("verify_tls", True),
            ) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Dify returned HTTP {exc.response.status_code}") from exc
        except Exception as exc:
            raise RuntimeError(self._redact(_safe_error(exc))) from exc

        raw = response.json().get("answer", "")
        logger.info("Dify returned %d characters", len(raw))
        return raw

    def _redact(self, value: str) -> str:
        secret = self.config.get("api_key", "")
        return value.replace(secret, "[REDACTED]") if secret else value

    def call_json(self, prompt: str, system_prompt: str = "") -> Any:
        raw = self.call(prompt, system_prompt).strip()
        if not raw:
            raise ValueError("LLM returned an empty response")
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.splitlines()[1:]).rstrip("`").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("LLM response was not valid JSON (%d characters)", len(raw))
            raise ValueError("LLM response was not valid JSON") from exc


def discover_models(config: dict) -> list[str]:
    if config.get("protocol") == "dify":
        return []
    url = config["base_url"].rstrip("/") + "/models"
    try:
        with httpx.Client(timeout=30.0, verify=config.get("verify_tls", True)) as client:
            response = client.get(url, headers={"Authorization": f"Bearer {config['api_key']}"})
            response.raise_for_status()
            data = response.json().get("data", [])
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Model discovery returned HTTP {exc.response.status_code}") from exc
    except Exception as exc:
        message = _safe_error(exc)
        secret = config.get("api_key", "")
        raise RuntimeError(message.replace(secret, "[REDACTED]") if secret else message) from exc
    return sorted({item["id"] for item in data if isinstance(item, dict) and item.get("id")})


def detect_connection(config: dict) -> tuple[str, list[str]]:
    """Detect Dify vs. OpenAI-compatible from only a Base URL and API key."""
    model_error: Exception | None = None
    try:
        return "openai_compatible", discover_models({**config, "protocol": "openai_compatible"})
    except RuntimeError as exc:
        model_error = exc

    info_url = config["base_url"].rstrip("/") + "/info"
    try:
        with httpx.Client(timeout=30.0, verify=config.get("verify_tls", True)) as client:
            response = client.get(
                info_url,
                headers={"Authorization": f"Bearer {config['api_key']}"},
            )
    except Exception as exc:
        message = _safe_error(exc)
        secret = config.get("api_key", "")
        safe_message = message.replace(secret, "[REDACTED]") if secret else message
        raise RuntimeError(safe_message) from exc

    # Dify exposes /info. Authentication failures still identify the protocol;
    # the subsequent connection test will return the useful credential error.
    if response.status_code in {200, 401, 403}:
        return "dify", []

    # Some OpenAI-compatible services do not implement GET /models. Dify has
    # now been ruled out, so retain the compatible protocol and let the user
    # provide a model ID only if automatic discovery was unavailable.
    logger.info("Model discovery unavailable; assuming OpenAI-compatible: %s", model_error)
    return "openai_compatible", []


def test_connection(config: dict) -> None:
    raw = LLMClient(config).call("Reply with exactly: OK")
    if not raw.strip():
        raise ValueError("The API returned an empty response")
