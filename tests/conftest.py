"""Fixtures for the Gunkly tests."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.gunkly.const import CONF_TOKEN, CONF_URL, DOMAIN

URL = "https://gunkly.test"
API = f"{URL}/api/v1"
TOKEN = "gk_" + "a" * 43

ALL_SCOPES = ["chores:read", "chores:complete", "chores:write"]


def token_payload(scopes: list[str] | None = None) -> dict[str, Any]:
    """Return a GET /token response."""
    return {
        "id": "tok1",
        "name": "Home Assistant",
        "scopes": ALL_SCOPES if scopes is None else scopes,
        "households": [
            {"id": "hh1", "name": "Home", "role": "member"},
            {"id": "hh2", "name": "Cabin", "role": "guest"},
        ],
        "user": {"id": "u1", "displayName": "Sam"},
        "expiresAt": None,
    }


def chore(cid: str, name: str, status: str, due: str | None, **extra: Any) -> dict[str, Any]:
    """Return a chore as the API serialises it."""
    return {
        "id": cid,
        "areaId": None,
        "name": name,
        "notes": extra.pop("notes", ""),
        "link": "",
        "kind": "recurring",
        "schedule": {"type": "interval", "interval": {"every": 1, "unit": "week"}, "firstDue": due},
        "dueDate": due,
        "nextDue": None,
        "status": status,
        "assignees": [],
        **extra,
    }


CHORES = [
    chore("c1", "Take out bins", "overdue", "2026-11-20", turnName="Alex"),
    chore(
        "c2", "Water plants", "today", "2026-11-22", notes="Fern needs extra", reminderTime="07:30"
    ),
    chore("c3", "Clean oven", "thisWeek", "2026-11-25", areaId="a1"),
    chore("c4", "Deep clean", "later", "2026-12-20"),
    chore("c5", "Paused thing", "paused", "2026-11-21"),
]


# Reminder times are local to the household's zone, which differs from the test default.
HOUSEHOLD = {
    "id": "hh1",
    "name": "Home",
    "timezone": "Asia/Tokyo",
    "role": "member",
    "areasEnabled": True,
}
AREAS = [{"id": "a1", "name": "Kitchen"}, {"id": "a2", "name": "Garden"}]


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow loading custom_components."""


@pytest.fixture
def mock_api(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Mock a healthy Gunkly server with all scopes."""
    aioclient_mock.get(f"{API}/token", json=token_payload())
    aioclient_mock.get(f"{API}/households/hh1/chores", json=CHORES)
    aioclient_mock.get(f"{API}/households/hh2/chores", json=[])
    aioclient_mock.get(f"{API}/households/hh1", json=HOUSEHOLD)
    aioclient_mock.get(f"{API}/households/hh1/areas", json=AREAS)
    return aioclient_mock


@pytest.fixture
def entry() -> MockConfigEntry:
    """A config entry for the mocked server."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Gunkly (Sam)",
        unique_id="tok1@gunkly.test:443",
        data={CONF_URL: URL, CONF_TOKEN: TOKEN},
    )


@pytest.fixture
async def setup(hass: HomeAssistant, entry: MockConfigEntry, mock_api: AiohttpClientMocker):
    """Return a coroutine function that sets the entry up."""

    async def _setup(options: dict[str, Any] | None = None) -> MockConfigEntry:
        entry.add_to_hass(hass)
        if options:
            hass.config_entries.async_update_entry(entry, options=options)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _setup


def set_scopes(mock: AiohttpClientMocker, scopes: list[str]) -> None:
    """Re-register the mocked server with a token that has only these scopes."""
    mock.clear_requests()
    mock.get(f"{API}/token", json=token_payload(scopes))
    mock.get(f"{API}/households/hh1/chores", json=CHORES)
    mock.get(f"{API}/households/hh2/chores", json=[])
    mock.get(f"{API}/households/hh1", json=HOUSEHOLD)
    mock.get(f"{API}/households/hh1/areas", json=AREAS)


def set_chores(
    mock: AiohttpClientMocker,
    chores: list[dict[str, Any]],
    archived: list[dict[str, Any]] | None = None,
) -> None:
    """Replace the chores the mocked server lists for the first household."""
    mock.clear_requests()
    if archived is not None:  # registered first: the more specific URL must match first
        mock.get(f"{API}/households/hh1/chores?archived=1", json=archived)
    mock.get(f"{API}/token", json=token_payload())
    mock.get(f"{API}/households/hh1/chores", json=chores)
    mock.get(f"{API}/households/hh2/chores", json=[])
    mock.get(f"{API}/households/hh1", json=HOUSEHOLD)
    mock.get(f"{API}/households/hh1/areas", json=AREAS)
