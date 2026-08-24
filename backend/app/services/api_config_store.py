"""Encrypted, file-backed API configuration library."""
from __future__ import annotations

import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

try:  # POSIX: macOS and Linux
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX
    msvcrt = None


PROVIDERS = {
    "auto": {
        "label": "Automatic detection",
        "protocol": "auto",
        "base_url": "",
        "requires_base_url": True,
        "supports_model_discovery": True,
    },
    "dify": {
        "label": "Dify",
        "protocol": "dify",
        "base_url": "https://api.dify.ai/v1",
        "requires_base_url": True,
        "supports_model_discovery": False,
    },
    "openai": {
        "label": "OpenAI",
        "protocol": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "requires_base_url": False,
        "supports_model_discovery": True,
    },
    "bailian": {
        "label": "Alibaba Bailian",
        "protocol": "openai_compatible",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "requires_base_url": False,
        "supports_model_discovery": True,
    },
    "deepseek": {
        "label": "DeepSeek",
        "protocol": "openai_compatible",
        "base_url": "https://api.deepseek.com",
        "requires_base_url": False,
        "supports_model_discovery": True,
    },
    "siliconflow": {
        "label": "SiliconFlow",
        "protocol": "openai_compatible",
        "base_url": "https://api.siliconflow.cn/v1",
        "requires_base_url": False,
        "supports_model_discovery": True,
    },
    "moonshot": {
        "label": "Moonshot",
        "protocol": "openai_compatible",
        "base_url": "https://api.moonshot.cn/v1",
        "requires_base_url": False,
        "supports_model_discovery": True,
    },
    "openrouter": {
        "label": "OpenRouter",
        "protocol": "openai_compatible",
        "base_url": "https://openrouter.ai/api/v1",
        "requires_base_url": False,
        "supports_model_discovery": True,
    },
    "custom_openai_compatible": {
        "label": "Custom OpenAI-compatible",
        "protocol": "openai_compatible",
        "base_url": "",
        "requires_base_url": True,
        "supports_model_discovery": True,
    },
}

CONNECTION_FIELDS = {"provider", "base_url", "api_key", "model", "dify_user", "verify_tls"}


def identify_provider(base_url: str, protocol: str) -> str:
    """Infer a display preset without requiring the user to choose one."""
    if protocol == "dify":
        return "dify"
    host = (urlparse(base_url).hostname or "").lower()
    if "openrouter.ai" in host:
        return "openrouter"
    if any(value in host for value in ["dashscope", "aliyuncs.com", ".maas."]):
        return "bailian"
    if "deepseek" in host:
        return "deepseek"
    if "siliconflow" in host:
        return "siliconflow"
    if "moonshot" in host:
        return "moonshot"
    if host == "api.openai.com" or host.endswith(".openai.com"):
        return "openai"
    return "custom_openai_compatible"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask_key(value: str) -> str:
    if len(value) <= 8:
        return "••••••••"
    return f"{value[:4]}••••••••{value[-4:]}"


def _normalize_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL must be a valid HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError("Base URL must not contain credentials")
    return value


def _lock_file(handle) -> None:
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return
    if msvcrt is not None:
        # msvcrt locks a byte range from the current file position. Keep one
        # stable byte in the lock file so separate Windows processes contend
        # for the same range.
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    raise RuntimeError("No supported file-locking implementation is available")


def _unlock_file(handle) -> None:
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    if msvcrt is not None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    raise RuntimeError("No supported file-locking implementation is available")


class ApiConfigStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or settings.api_configs_dir
        self.directory.mkdir(parents=True, exist_ok=True)
        self.data_path = self.directory / "api_configs.json"
        self.key_path = self.directory / "master.key"
        self.lock_path = self.directory / ".lock"
        self._thread_lock = threading.RLock()
        self._fernet = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        if self.key_path.exists():
            return self.key_path.read_bytes().strip()
        key = Fernet.generate_key()
        fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
        return key

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock:
            with self.lock_path.open("a+b") as handle:
                _lock_file(handle)
                try:
                    yield
                finally:
                    _unlock_file(handle)

    def _read_unlocked(self) -> dict:
        if not self.data_path.exists():
            return {"version": 1, "active_id": None, "legacy_migrated": False, "configs": []}
        return json.loads(self.data_path.read_text(encoding="utf-8"))

    def _write_unlocked(self, data: dict) -> None:
        temp = self.data_path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.data_path)
        os.chmod(self.data_path, 0o600)

    def _encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def _decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Stored API key cannot be decrypted") from exc

    def _validate_fields(self, values: dict) -> dict:
        provider = values.get("provider", "")
        if provider not in PROVIDERS:
            raise ValueError("Unsupported API provider")
        name = values.get("name", "").strip()
        if not name:
            raise ValueError("Name is required")
        key = values.get("api_key", "").strip()
        if not key:
            raise ValueError("API key is required")
        base_url = values.get("base_url", "").strip() or PROVIDERS[provider]["base_url"]
        base_url = _normalize_url(base_url)
        model = values.get("model", "").strip()
        if PROVIDERS[provider]["protocol"] == "openai_compatible" and not model:
            raise ValueError("Model is required for OpenAI-compatible providers")
        dify_user = values.get("dify_user", "soc-audit-local").strip() or "soc-audit-local"
        return {
            **values,
            "name": name,
            "provider": provider,
            "protocol": PROVIDERS[provider]["protocol"],
            "base_url": base_url,
            "api_key": key,
            "model": model,
            "dify_user": dify_user,
            "verify_tls": bool(values.get("verify_tls", True)),
        }

    def _public(self, config: dict, active_id: str | None) -> dict:
        key = self._decrypt(config["encrypted_api_key"])
        status = "verified" if config.get("validated_revision") == config["revision"] else (
            "failed" if config.get("last_test_error") else "untested"
        )
        return {
            key_name: value for key_name, value in config.items()
            if key_name not in {"encrypted_api_key", "validated_revision"}
        } | {
            "masked_api_key": _mask_key(key),
            "status": status,
            "is_active": config["id"] == active_id,
        }

    def list(self) -> list[dict]:
        with self._locked():
            data = self._read_unlocked()
            return [self._public(item, data.get("active_id")) for item in data["configs"]]

    def get_public(self, config_id: str) -> dict:
        with self._locked():
            data = self._read_unlocked()
            config = self._find(data, config_id)
            return self._public(config, data.get("active_id"))

    def get_secret(self, config_id: str) -> dict:
        with self._locked():
            data = self._read_unlocked()
            config = dict(self._find(data, config_id))
            config["api_key"] = self._decrypt(config.pop("encrypted_api_key"))
            return config

    @staticmethod
    def _find(data: dict, config_id: str) -> dict:
        config = next((item for item in data["configs"] if item["id"] == config_id), None)
        if config is None:
            raise KeyError("API configuration not found")
        return config

    def create(self, values: dict) -> dict:
        values = self._validate_fields(values)
        timestamp = _now()
        config = {
            "id": str(uuid.uuid4()),
            "name": values["name"],
            "provider": values["provider"],
            "protocol": values["protocol"],
            "base_url": values["base_url"],
            "encrypted_api_key": self._encrypt(values["api_key"]),
            "model": values["model"],
            "dify_user": values["dify_user"],
            "verify_tls": values["verify_tls"],
            "revision": 1,
            "validated_revision": None,
            "last_tested_at": None,
            "last_test_error": "",
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        with self._locked():
            data = self._read_unlocked()
            data["configs"].append(config)
            self._write_unlocked(data)
            return self._public(config, data.get("active_id"))

    def update(self, config_id: str, patch: dict) -> dict:
        clean_patch = {key: value for key, value in patch.items() if value is not None}
        if clean_patch.get("api_key", "") == "":
            clean_patch.pop("api_key", None)
        with self._locked():
            data = self._read_unlocked()
            config = self._find(data, config_id)
            current = dict(config)
            current["api_key"] = self._decrypt(current["encrypted_api_key"])
            merged = self._validate_fields({**current, **clean_patch})
            changed_connection = any(
                key in clean_patch and merged[key] != current.get(key)
                for key in CONNECTION_FIELDS
            )
            for key in ["name", "provider", "protocol", "base_url", "model", "dify_user", "verify_tls"]:
                config[key] = merged[key]
            if "api_key" in clean_patch:
                config["encrypted_api_key"] = self._encrypt(merged["api_key"])
            if changed_connection:
                config["revision"] += 1
                config["validated_revision"] = None
                config["last_test_error"] = ""
                if data.get("active_id") == config_id:
                    data["active_id"] = None
            config["updated_at"] = _now()
            self._write_unlocked(data)
            return self._public(config, data.get("active_id"))

    def delete(self, config_id: str) -> None:
        with self._locked():
            data = self._read_unlocked()
            self._find(data, config_id)
            data["configs"] = [item for item in data["configs"] if item["id"] != config_id]
            if data.get("active_id") == config_id:
                data["active_id"] = None
            self._write_unlocked(data)

    def record_test(self, config_id: str, success: bool, error: str = "") -> dict:
        with self._locked():
            data = self._read_unlocked()
            config = self._find(data, config_id)
            config["last_tested_at"] = _now()
            config["last_test_error"] = "" if success else error[:500]
            config["validated_revision"] = config["revision"] if success else None
            self._write_unlocked(data)
            return self._public(config, data.get("active_id"))

    def activate(self, config_id: str) -> dict:
        with self._locked():
            data = self._read_unlocked()
            config = self._find(data, config_id)
            if config.get("validated_revision") != config["revision"]:
                raise ValueError("Test this API configuration successfully before activating it")
            data["active_id"] = config_id
            self._write_unlocked(data)
            return self._public(config, config_id)

    def active_public(self) -> dict | None:
        with self._locked():
            data = self._read_unlocked()
            if not data.get("active_id"):
                return None
            return self._public(self._find(data, data["active_id"]), data["active_id"])

    def active_snapshot(self) -> dict:
        with self._locked():
            data = self._read_unlocked()
            active_id = data.get("active_id")
            if not active_id:
                raise ValueError("No active API configuration. Add, test, and activate one on the APIs page.")
            config = dict(self._find(data, active_id))
            if config.get("validated_revision") != config["revision"]:
                raise ValueError("The active API configuration must be tested again")
            config["api_key"] = self._decrypt(config.pop("encrypted_api_key"))
            return config

    def migrate_legacy(self) -> str | None:
        """Import legacy .env values once. Returns the preferred config id to verify."""
        with self._locked():
            data = self._read_unlocked()
            if data.get("legacy_migrated"):
                return None

            imported: dict[str, str] = {}
            candidates = []
            if settings.dify_api_key and settings.dify_base_url:
                candidates.append({
                    "name": "Legacy Dify",
                    "provider": "dify",
                    "base_url": settings.dify_base_url,
                    "api_key": settings.dify_api_key,
                    "model": "",
                    "dify_user": settings.dify_user,
                    "verify_tls": True,
                })
            if settings.bailian_api_key and settings.bailian_base_url:
                provider = "bailian" if "aliyun" in settings.bailian_base_url or "dashscope" in settings.bailian_base_url else "custom_openai_compatible"
                candidates.append({
                    "name": "Legacy OpenAI-compatible",
                    "provider": provider,
                    "base_url": settings.bailian_base_url,
                    "api_key": settings.bailian_api_key,
                    "model": settings.bailian_model,
                    "dify_user": "soc-audit-local",
                    "verify_tls": False,
                })

            for candidate in candidates:
                validated = self._validate_fields(candidate)
                timestamp = _now()
                config = {
                    "id": str(uuid.uuid4()),
                    "name": validated["name"],
                    "provider": validated["provider"],
                    "protocol": validated["protocol"],
                    "base_url": validated["base_url"],
                    "encrypted_api_key": self._encrypt(validated["api_key"]),
                    "model": validated["model"],
                    "dify_user": validated["dify_user"],
                    "verify_tls": validated["verify_tls"],
                    "revision": 1,
                    "validated_revision": None,
                    "last_tested_at": None,
                    "last_test_error": "",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
                data["configs"].append(config)
                imported[validated["protocol"]] = config["id"]

            data["legacy_migrated"] = True
            self._write_unlocked(data)
            preferred = "dify" if settings.llm_provider == "dify" else "openai_compatible"
            return imported.get(preferred)


api_config_store = ApiConfigStore()
