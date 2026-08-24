from app.models.schemas import DiscoverModelsRequest
from app.routers import api_configs
from app.services.api_config_store import identify_provider


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
