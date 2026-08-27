"""LLM clients for immutable API configuration snapshots."""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import sys
import traceback
import uuid
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from openai import OpenAI

logger = logging.getLogger(__name__)

PREFERRED_MODELS = {
    "openrouter": ["openrouter/free"],
    "bailian": ["qwen-plus", "qwen-turbo"],
    "deepseek": ["deepseek-chat", "deepseek-v4-flash"],
    "openai": ["gpt-4o-mini", "gpt-4.1-mini"],
}
NON_CHAT_MODEL_WORDS = {
    "embedding", "rerank", "moderation", "whisper", "transcribe", "tts",
    "speech", "image", "dall-e", "realtime",
}


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "The API request timed out"
    if isinstance(exc, httpx.ConnectError):
        return "Could not connect to the API. Check the URL, network, and VPN."
    return str(exc)[:500]


def _redact(value: str, secret: str = "") -> str:
    return value.replace(secret, "[REDACTED]") if secret else value


def _safe_base_url(value: str) -> str:
    """Remove URL credentials, query strings, and fragments before logging."""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    except (TypeError, ValueError):
        return "[invalid URL]"


def log_connection_diagnostic(operation: str, exc: Exception, config: dict | None = None) -> str:
    """Log actionable connection details without exposing API credentials."""
    config = config or {}
    secret = str(config.get("api_key", ""))
    diagnostic_id = uuid.uuid4().hex[:10]

    exception_chain = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(exception_chain) < 8:
        seen.add(id(current))
        message = _redact(str(current), secret)[:1000]
        exception_chain.append(
            f"  {len(exception_chain) + 1}. {type(current).__module__}.{type(current).__name__}: {message}"
        )
        current = current.__cause__ or current.__context__

    frames = traceback.extract_tb(exc.__traceback__)
    traceback_lines = [
        f"  {frame.filename}:{frame.lineno} in {frame.name}"
        for frame in frames[-12:]
    ] or ["  [no traceback frames]"]
    proxy_state = ", ".join(
        f"{name}={'SET' if os.environ.get(name) else 'not set'}"
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
    )

    logger.error(
        "API_CONNECTION_DIAGNOSTIC id=%s\n"
        "  operation=%s\n"
        "  base_url=%s\n"
        "  verify_tls=%s\n"
        "  runtime=%s | Python %s | httpx %s\n"
        "  proxy_environment=%s\n"
        "exception_chain:\n%s\n"
        "traceback_frames:\n%s",
        diagnostic_id,
        operation,
        _safe_base_url(str(config.get("base_url", ""))),
        config.get("verify_tls", True),
        platform.platform(),
        sys.version.split()[0],
        httpx.__version__,
        proxy_state,
        "\n".join(exception_chain),
        "\n".join(traceback_lines),
    )
    return diagnostic_id


def choose_automatic_model(provider: str, models: list[str]) -> str:
    for preferred in PREFERRED_MODELS.get(provider, []):
        if preferred in models:
            return preferred
    if provider == "openrouter":
        free_model = next((model for model in models if model.endswith(":free")), "")
        if free_model:
            return free_model
    return next(
        (
            model for model in models
            if not any(word in model.lower() for word in NON_CHAT_MODEL_WORDS)
        ),
        models[0] if models else "",
    )


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
