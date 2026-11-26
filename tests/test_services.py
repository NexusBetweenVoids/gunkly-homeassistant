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


@pytest.mark.parametrize("service", ["snooze_chore", "skip_chore"])
async def test_snooze_skip_need_scope(hass: HomeAssistant, setup, mock_api, service) -> None:
    """Snooze and skip need chores:complete like complete does."""
    set_scopes(mock_api, ["chores:read", "chores:write"])
    await setup()
    data = {"entity_id": ENTITY, "chore": "c1"}
    if service == "snooze_chore":
        data["until"] = "2026-12-01"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, service, data, blocking=True)
    assert not _posts(mock_api)


async def test_guest_household_refuses_actions(hass: HomeAssistant, setup, mock_api) -> None:
    """A guest role refuses actions locally even with all scopes."""
    await setup()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "skip_chore", {"entity_id": "todo.cabin_chores", "chore": "c1"}, blocking=True
        )
    assert not _posts(mock_api)


async def test_pause_resume(hass: HomeAssistant, setup, mock_api) -> None:
    """Pause sends an optional date, resume posts; paused chores resolve by name too."""
    await setup()
    mock_api.post(f"{API}/households/hh1/chores/c1/pause", json={})
    mock_api.post(f"{API}/households/hh1/chores/c5/pause", json={})
    mock_api.post(f"{API}/households/hh1/chores/c5/resume", json={})
    await hass.services.async_call(
        DOMAIN,
        "pause_chore",
        {"entity_id": ENTITY, "chore": "Take out bins", "until": "2026-12-24"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN, "pause_chore", {"entity_id": ENTITY, "chore": "c5"}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "resume_chore", {"entity_id": ENTITY, "chore": "Paused thing"}, blocking=True
    )
    posts = _posts(mock_api)
    assert str(posts[0][1]).endswith("/chores/c1/pause")
    assert posts[0][2] == {"until": "2026-12-24"}
    assert posts[1][2] == {}
    assert str(posts[2][1]).endswith("/chores/c5/resume")


async def test_undo_completion(hass: HomeAssistant, setup, mock_api) -> None:
    """Undo reverts the most recent completion that is not reverted yet."""
    await setup()
    mock_api.get(
        f"{API}/households/hh1/chores/c1/completions",
        json={
            "items": [
                {"id": "k3", "revertedAt": "2026-11-21T10:00:00Z"},
                {"id": "k2", "revertedAt": None},
                {"id": "k1", "revertedAt": None},
            ],
            "next": None,
        },
    )
    mock_api.post(f"{API}/households/hh1/chores/c1/completions/k2/revert", status=204)
    await hass.services.async_call(
        DOMAIN, "undo_completion", {"entity_id": ENTITY, "chore": "Take out bins"}, blocking=True
    )
    posts = _posts(mock_api)
    assert len(posts) == 1 and str(posts[0][1]).endswith("/completions/k2/revert")


async def test_undo_nothing(hass: HomeAssistant, setup, mock_api) -> None:
    """With no completion left to undo the action says so and changes nothing."""
    await setup()
    mock_api.get(f"{API}/households/hh1/chores/c3/completions", json={"items": [], "next": None})
    with pytest.raises(ServiceValidationError, match="no completion to undo"):
        await hass.services.async_call(
            DOMAIN, "undo_completion", {"entity_id": ENTITY, "chore": "c3"}, blocking=True
        )
    assert not _posts(mock_api)


@pytest.mark.parametrize("service", ["pause_chore", "resume_chore", "undo_completion"])
async def test_new_actions_need_scope(hass: HomeAssistant, setup, mock_api, service) -> None:
    """Pause, resume and undo need chores:complete like completing does."""
    set_scopes(mock_api, ["chores:read", "chores:write"])
    await setup()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, service, {"entity_id": ENTITY, "chore": "c1"}, blocking=True
        )
    assert not _posts(mock_api)
