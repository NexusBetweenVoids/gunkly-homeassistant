"""API client unit tests."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.gunkly.api import (
    GunklyApiError,
    GunklyAuthError,
    GunklyClient,
    GunklyConnectionError,
    GunklyRateLimitError,
    normalize_url,
)

from .conftest import API, URL


@pytest.fixture
async def client(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> GunklyClient:
    """Client against the mocked URL."""
    return GunklyClient(async_get_clientsession(hass), URL + "/", "gk_x")


def test_normalize_url() -> None:
    """Scheme defaults to https and trailing slashes go away."""
    assert normalize_url("Gunkly.test/") == "https://gunkly.test"
    assert normalize_url("http://10.0.0.2:4865/") == "http://10.0.0.2:4865"
    with pytest.raises(ValueError):
        normalize_url("ftp://x")


async def test_error_mapping(client: GunklyClient, aioclient_mock: AiohttpClientMocker) -> None:
    """HTTP and transport failures map to the client's exceptions."""
    aioclient_mock.get(f"{API}/households/a/chores", status=401)
    with pytest.raises(GunklyAuthError):
        await client.get_chores("a")
    aioclient_mock.clear_requests()

    aioclient_mock.get(f"{API}/households/a/chores", status=429, headers={"Retry-After": "7"})
    with pytest.raises(GunklyRateLimitError) as rate:
        await client.get_chores("a")
    assert rate.value.retry_after == 7
    aioclient_mock.clear_requests()

    aioclient_mock.get(
        f"{API}/households/a/chores", status=404, json={"error": {"code": "not_found"}}
    )
    with pytest.raises(GunklyApiError) as api:
        await client.get_chores("a")
    assert (api.value.status, api.value.code) == (404, "not_found")
    aioclient_mock.clear_requests()

    aioclient_mock.get(f"{API}/households/a/chores", exc=TimeoutError)
    with pytest.raises(GunklyConnectionError):
        await client.get_chores("a")
    aioclient_mock.clear_requests()

    aioclient_mock.get(f"{API}/households/a/chores", text="<html>")
    with pytest.raises(GunklyConnectionError):
        await client.get_chores("a")
