"""Service tests."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.gunkly.const import DOMAIN

from .conftest import API, set_scopes

ENTITY = "todo.home_chores"


def _posts(mock: AiohttpClientMocker) -> list[tuple]:
    return [c for c in mock.mock_calls if c[0] == "POST"]


async def test_complete_by_id_and_name(hass: HomeAssistant, setup, mock_api) -> None:
    """The chore may be an id or an exact (case-insensitive) name."""
    await setup()
    mock_api.post(f"{API}/households/hh1/chores/c1/complete", status=201, json={})
    mock_api.post(f"{API}/households/hh1/chores/c3/complete", status=201, json={})
    await hass.services.async_call(
        DOMAIN,
        "complete_chore",
        {"entity_id": ENTITY, "chore": "c1", "note": "done"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN, "complete_chore", {"entity_id": ENTITY, "chore": "clean OVEN"}, blocking=True
    )
    posts = _posts(mock_api)
    assert str(posts[0][1]).endswith("/chores/c1/complete")
    assert posts[0][2] == {"note": "done"}
    assert str(posts[1][1]).endswith("/chores/c3/complete")


async def test_complete_needs_scope(hass: HomeAssistant, setup, mock_api) -> None:
    """Completing without chores:complete is refused locally."""
    set_scopes(mock_api, ["chores:read"])
    await setup()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "complete_chore", {"entity_id": ENTITY, "chore": "c1"}, blocking=True
        )
    assert not _posts(mock_api)


async def test_snooze_and_skip(hass: HomeAssistant, setup, mock_api) -> None:
    """Snooze sends the date; skip posts to the skip endpoint."""
    await setup()
    mock_api.post(f"{API}/households/hh1/chores/c2/snooze", json={})
    mock_api.post(f"{API}/households/hh1/chores/c2/skip", json={})
    await hass.services.async_call(
        DOMAIN,
        "snooze_chore",
        {"entity_id": ENTITY, "chore": "Water plants", "until": "2026-11-30"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN, "skip_chore", {"entity_id": ENTITY, "chore": "c2"}, blocking=True
    )
    posts = _posts(mock_api)
    assert posts[0][2] == {"until": "2026-11-30"}
    assert str(posts[1][1]).endswith("/chores/c2/skip")


async def test_unknown_chore_error(hass: HomeAssistant, setup, mock_api) -> None:
    """A 404 from the server is raised as HomeAssistantError."""
    await setup()
    mock_api.post(
        f"{API}/households/hh1/chores/nope/skip", status=404, json={"error": {"code": "not_found"}}
    )
    with pytest.raises(HomeAssistantError, match="not_found"):
        await hass.services.async_call(
            DOMAIN, "skip_chore", {"entity_id": ENTITY, "chore": "nope"}, blocking=True
        )
