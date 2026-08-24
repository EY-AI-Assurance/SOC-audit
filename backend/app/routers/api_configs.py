"""API configuration library endpoints."""
from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException, Response

from app.models.schemas import (
    ApiConfigCreate,
    ApiConfigSummary,
    ApiConfigUpdate,
    DiscoverModelsRequest,
)
from app.services.api_config_store import PROVIDERS, api_config_store, identify_provider
from app.services.dify_client import detect_connection, discover_models, test_connection

router = APIRouter(prefix="/api/api-configs", tags=["api-configs"])


def _http_error(exc: Exception, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(exc))


@router.get("/providers")
def list_providers():
    return {"providers": [{"id": provider_id, **values} for provider_id, values in PROVIDERS.items()]}


@router.get("")
def list_configs():
    return {
        "configs": [ApiConfigSummary(**item).model_dump() for item in api_config_store.list()],
        "active": api_config_store.active_public(),
    }


@router.post("", response_model=ApiConfigSummary, status_code=201)
def create_config(req: ApiConfigCreate):
    try:
        return api_config_store.create(req.model_dump())
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.patch("/{config_id}", response_model=ApiConfigSummary)
def update_config(config_id: str, req: ApiConfigUpdate):
    try:
        return api_config_store.update(config_id, req.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise _http_error(exc, 404) from exc
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.delete("/{config_id}", status_code=204)
def delete_config(config_id: str):
    try:
        api_config_store.delete(config_id)
    except KeyError as exc:
        raise _http_error(exc, 404) from exc
    return Response(status_code=204)


@router.post("/discover-models")
def models(req: DiscoverModelsRequest):
    try:
        if req.config_id:
            config = api_config_store.get_secret(req.config_id)
            protocol = config["protocol"]
            provider_id = config["provider"]
            model_list = discover_models(config)
        else:
            if not req.base_url or not req.api_key:
                raise ValueError("Base URL and API key are required")
            base_url = req.base_url.strip().rstrip("/")
            config = {
                "base_url": base_url,
                "api_key": req.api_key,
                "verify_tls": req.verify_tls,
            }
            protocol, model_list = detect_connection(config)
            provider_id = identify_provider(base_url, protocol)
        return {"models": model_list, "protocol": protocol, "provider": provider_id}
    except (KeyError, ValueError, RuntimeError) as exc:
        raise _http_error(exc, 502 if isinstance(exc, RuntimeError) else 400) from exc


@router.post("/{config_id}/test", response_model=ApiConfigSummary)
def test_config(config_id: str):
    try:
        config = api_config_store.get_secret(config_id)
        test_connection(config)
        return api_config_store.record_test(config_id, True)
    except KeyError as exc:
        raise _http_error(exc, 404) from exc
    except Exception as exc:
        error = str(exc)[:500]
        try:
            api_config_store.record_test(config_id, False, error)
        except KeyError:
            pass
        raise _http_error(RuntimeError(error), 502) from exc


@router.post("/{config_id}/activate", response_model=ApiConfigSummary)
def activate_config(config_id: str):
    try:
        return api_config_store.activate(config_id)
    except KeyError as exc:
        raise _http_error(exc, 404) from exc
    except ValueError as exc:
        raise _http_error(exc, 409) from exc


def migrate_and_verify_legacy() -> None:
    preferred_id = api_config_store.migrate_legacy()
    if not preferred_id:
        return

    def verify() -> None:
        try:
            test_connection(api_config_store.get_secret(preferred_id))
            api_config_store.record_test(preferred_id, True)
            api_config_store.activate(preferred_id)
        except Exception as exc:
            api_config_store.record_test(preferred_id, False, str(exc))

    threading.Thread(target=verify, name="legacy-api-verification", daemon=True).start()
