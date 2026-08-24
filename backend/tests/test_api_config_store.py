from pathlib import Path

import pytest

from app.services.api_config_store import ApiConfigStore


@pytest.fixture()
def store(tmp_path: Path) -> ApiConfigStore:
    return ApiConfigStore(tmp_path / "api-configs")


def make_config(store: ApiConfigStore) -> dict:
    return store.create({
        "name": "Audit OpenAI",
        "provider": "openai",
        "base_url": "https://api.example.com/v1/",
        "api_key": "sk-plain-secret-value",
        "model": "audit-model",
        "dify_user": "soc-audit-local",
        "verify_tls": True,
    })


def test_secret_is_encrypted_and_never_returned(store: ApiConfigStore):
    config = make_config(store)
    on_disk = store.data_path.read_text(encoding="utf-8")

    assert "sk-plain-secret-value" not in on_disk
    assert "api_key" not in config
    assert config["masked_api_key"].startswith("sk-p")
    assert store.active_public() is None
    assert (store.key_path.stat().st_mode & 0o777) == 0o600


def test_only_current_verified_revision_can_be_active(store: ApiConfigStore):
    config = make_config(store)

    with pytest.raises(ValueError, match="Test this API"):
        store.activate(config["id"])

    store.record_test(config["id"], True)
    active = store.activate(config["id"])
    assert active["is_active"] is True
    assert store.active_snapshot()["api_key"] == "sk-plain-secret-value"

    updated = store.update(config["id"], {"model": "new-model", "api_key": ""})
    assert updated["status"] == "untested"
    assert store.active_public() is None
    assert store.get_secret(config["id"])["api_key"] == "sk-plain-secret-value"


def test_failed_test_is_visible_but_cannot_activate(store: ApiConfigStore):
    config = make_config(store)
    failed = store.record_test(config["id"], False, "HTTP 401")

    assert failed["status"] == "failed"
    assert failed["last_test_error"] == "HTTP 401"
    with pytest.raises(ValueError):
        store.activate(config["id"])


def test_deleting_active_config_clears_selection(store: ApiConfigStore):
    config = make_config(store)
    store.record_test(config["id"], True)
    store.activate(config["id"])

    store.delete(config["id"])

    assert store.active_public() is None
    assert store.list() == []
