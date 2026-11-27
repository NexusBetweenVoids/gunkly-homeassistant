"""Config flow tests."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.gunkly.const import (
    CONF_POLL_INTERVAL,
    CONF_SHOW_LATER,
    CONF_TOKEN,
    CONF_URL,
    DOMAIN,
)

from .conftest import API, TOKEN, URL, token_payload

USER_INPUT = {CONF_URL: "gunkly.test/", CONF_TOKEN: f"  {TOKEN} "}


async def _start(hass: HomeAssistant, user_input: dict | None = None):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input or USER_INPUT
    )


async def test_user_success(hass: HomeAssistant, mock_api: AiohttpClientMocker) -> None:
    """A valid token creates an entry with a normalised URL and stripped token."""
    result = await _start(hass)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Gunkly (Sam @ gunkly.test)"
    assert result["data"] == {CONF_URL: URL, CONF_TOKEN: TOKEN}
    assert result["result"].unique_id == "tok1@gunkly.test:443"
    assert mock_api.mock_calls[0][3]["Authorization"] == f"Bearer {TOKEN}"


async def test_duplicate_aborts(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    """The same token on the same host cannot be added twice."""
    entry.add_to_hass(hass)
    result = await _start(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_invalid_auth_then_recover(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 401 shows invalid_auth and the form can be retried."""
    aioclient_mock.get(f"{API}/token", status=401, json={"error": {"code": "unauthorized"}})
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API}/token", json=token_payload())
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_cannot_connect(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Server errors show cannot_connect."""
    aioclient_mock.get(f"{API}/token", status=502)
    result = await _start(hass)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_invalid_url(hass: HomeAssistant) -> None:
    """A non-http URL is rejected before any request."""
    result = await _start(hass, {CONF_URL: "ftp://x", CONF_TOKEN: TOKEN})
    assert result["errors"] == {"base": "invalid_url"}


async def test_missing_scope_and_no_households(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Tokens without read scope or households are refused."""
    aioclient_mock.get(f"{API}/token", json=token_payload(scopes=["chores:complete"]))
    result = await _start(hass)
    assert result["errors"] == {"base": "missing_scope"}

    aioclient_mock.clear_requests()
    payload = token_payload()
    payload["households"] = []
    aioclient_mock.get(f"{API}/token", json=payload)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "no_households"}


async def test_reauth(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    """Reauth stores the new token and its new unique id."""
    entry.add_to_hass(hass)
    new_token = "gk_" + "b" * 43
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    mock_api.clear_requests()
    payload = token_payload()
    payload["id"] = "tok2"
    mock_api.get(f"{API}/token", json=payload)
    mock_api.get(f"{API}/households/hh1/chores", json=[])
    mock_api.get(f"{API}/households/hh2/chores", json=[])
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: new_token}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] == new_token
    assert entry.unique_id == "tok2@gunkly.test:443"
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reauth_invalid(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    """A bad replacement token keeps the form open."""
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    mock_api.clear_requests()
    mock_api.get(f"{API}/token", status=401)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: "gk_bad"}
    )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_options(hass: HomeAssistant, setup) -> None:
    """Options flow stores the poll interval and show-later flag."""
    entry = await setup()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_POLL_INTERVAL: 120, CONF_SHOW_LATER: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_POLL_INTERVAL: 120, CONF_SHOW_LATER: True}


async def test_two_servers_are_told_apart(hass: HomeAssistant, setup, mock_api) -> None:
    """Entries of two servers get distinct device names (new entities, no `_2` ids)."""
    from homeassistant.helpers import device_registry as dr

    await setup()
    other = MockConfigEntry(
        domain=DOMAIN,
        title="Gunkly (Sam @ other.test)",
        unique_id="tok2@other.test:443",
        data={CONF_URL: "https://other.test", CONF_TOKEN: "gk_" + "b" * 43},
    )
    other.add_to_hass(hass)
    base = "https://other.test/api/v1"
    mock_api.get(f"{base}/token", json=token_payload(["chores:read"]))
    mock_api.get(f"{base}/households/hh1/chores", json=[])
    mock_api.get(f"{base}/households/hh2/chores", json=[])
    assert await hass.config_entries.async_setup(other.entry_id)
    await hass.async_block_till_done()
    names = {d.name for d in dr.async_get(hass).devices}
    assert {"Home", "Home (other.test)"} <= names
    assert hass.states.get("todo.home_chores") is not None  # existing ids unchanged
