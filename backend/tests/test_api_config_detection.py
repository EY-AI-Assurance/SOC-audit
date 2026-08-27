import httpx

from app.models.schemas import DiscoverModelsRequest
from app.routers import api_configs
from app.services.api_config_store import ApiConfigStore, identify_provider
from app.services.dify_client import log_connection_diagnostic


def test_provider_is_inferred_from_base_url():
    assert identify_provider(
        "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "openai_compatible",
    ) == "bailian"
    assert identify_provider(
        "https://openrouter.ai/api/v1",
        "openai_compatible",
    ) == "openrouter"
    assert identify_provider("https://internal.example.com/v1", "dify") == "dify"


def test_discovery_requires_no_provider(monkeypatch):
    monkeypatch.setattr(
        api_configs,
        "detect_connection",
        lambda config: ("openai_compatible", ["qwen-plus"]),
    )

    result = api_configs.models(DiscoverModelsRequest(
        base_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        api_key="sk-test",
    ))

    assert result == {
        "models": ["qwen-plus"],
        "protocol": "openai_compatible",
        "provider": "bailian",
    }


def test_untested_auto_config_is_saved_offline_and_resolved_when_tested(tmp_path, monkeypatch):
    store = ApiConfigStore(tmp_path / "api-configs")
    config = store.create({
        "name": "API configuration",
        "provider": "auto",
        "base_url": "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "api_key": "sk-test",
        "model": "",
        "dify_user": "soc-audit-local",
        "verify_tls": True,
    })
    monkeypatch.setattr(api_configs, "api_config_store", store)
    monkeypatch.setattr(
        api_configs,
        "detect_connection",
        lambda values: ("openai_compatible", ["text-embedding-v3", "qwen-plus"]),
    )
    monkeypatch.setattr(api_configs, "test_connection", lambda values: None)

    tested = api_configs.test_config(config["id"])

    assert tested["provider"] == "bailian"
    assert tested["protocol"] == "openai_compatible"
    assert tested["model"] == "qwen-plus"
    assert tested["status"] == "verified"


def test_connection_diagnostic_logs_root_cause_without_api_key(caplog):
    secret = "sk-must-never-appear"
    try:
        try:
            raise OSError(f"certificate verify failed for {secret}")
        except OSError as root:
            raise httpx.ConnectError("TLS connection failed") from root
    except httpx.ConnectError as exc:
        diagnostic_id = log_connection_diagnostic(
            "discover_models",
            exc,
            {
                "base_url": "https://user:password@example.com/v1?token=secret",
                "api_key": secret,
                "verify_tls": True,
            },
        )

    assert diagnostic_id in caplog.text
    assert "httpx.ConnectError: TLS connection failed" in caplog.text
    assert "builtins.OSError: certificate verify failed for [REDACTED]" in caplog.text
    assert secret not in caplog.text
    assert "user:password" not in caplog.text
    assert "token=secret" not in caplog.text
