"""To-do entity tests."""

from __future__ import annotations

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.todo import (
    DOMAIN as TODO,
)
from homeassistant.components.todo import (
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.gunkly.const import CONF_SHOW_LATER

from .conftest import API, set_scopes

ENTITY = "todo.home_chores"


def _posts(mock: AiohttpClientMocker) -> list[tuple]:
    return [c for c in mock.mock_calls if c[0] == "POST"]


async def _items(hass: HomeAssistant) -> list[dict]:
    resp = await hass.services.async_call(
        TODO, "get_items", {"entity_id": ENTITY}, blocking=True, return_response=True
    )
    return resp[ENTITY]["items"]


async def test_items(hass: HomeAssistant, setup) -> None:
    """Overdue, today and this-week chores are listed, earliest first."""
    await setup()
    items = await _items(hass)
    assert [i["summary"] for i in items] == ["Take out bins", "Water plants", "Clean oven"]
    assert items[1]["uid"] == "c2"
    assert items[1]["due"] == "2026-11-22"
    assert items[1]["description"] == "Fern needs extra"
    assert items[0]["description"] == "Turn: Alex"  # takes turns
    assert all(i["status"] == "needs_action" for i in items)
    assert hass.states.get(ENTITY).state == "3"


async def test_show_later_option(hass: HomeAssistant, entry: MockConfigEntry, setup) -> None:
    """The show_later option adds chores due later."""
    await setup({CONF_SHOW_LATER: True})
    assert "Deep clean" in [i["summary"] for i in await _items(hass)]


async def test_complete_item(hass: HomeAssistant, setup, mock_api: AiohttpClientMocker) -> None:
    """Checking an item POSTs to the complete endpoint of that chore."""
    await setup()
    mock_api.post(f"{API}/households/hh1/chores/c2/complete", status=201, json={})
    await hass.services.async_call(
        TODO,
        "update_item",
        {"entity_id": ENTITY, "item": "c2", "status": "completed"},
        blocking=True,
    )
    posts = _posts(mock_api)
    assert len(posts) == 1
    assert str(posts[0][1]).endswith("/households/hh1/chores/c2/complete")


async def test_complete_forbidden(
    hass: HomeAssistant, setup, mock_api: AiohttpClientMocker
) -> None:
    """A 403 from the server becomes a HomeAssistantError."""
    await setup()
    mock_api.post(
        f"{API}/households/hh1/chores/c2/complete",
        status=403,
        json={"error": {"code": "forbidden"}},
    )
    with pytest.raises(HomeAssistantError, match="does not allow"):
        await hass.services.async_call(
            TODO,
            "update_item",
            {"entity_id": ENTITY, "item": "c2", "status": "completed"},
            blocking=True,
        )


async def test_create_item(
    hass: HomeAssistant, setup, mock_api: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    """Adding an item creates a one-off chore due today."""
    freezer.move_to("2026-11-22 10:00:00+00:00")
    await setup()
    mock_api.post(f"{API}/households/hh1/chores", status=201, json={})
    await hass.services.async_call(
        TODO, "add_item", {"entity_id": ENTITY, "item": "Buy filters"}, blocking=True
    )
    posts = _posts(mock_api)
    assert posts[0][2] == {
        "name": "Buy filters",
        "kind": "oneoff",
        "schedule": {"firstDue": "2026-11-22"},
    }
    await hass.services.async_call(
        TODO,
        "add_item",
        {"entity_id": ENTITY, "item": "Mow", "due_date": "2026-11-30"},
        blocking=True,
    )
    assert _posts(mock_api)[1][2]["schedule"] == {"firstDue": "2026-11-30"}


@pytest.mark.parametrize(
    ("scopes", "features"),
    [
        (["chores:read"], TodoListEntityFeature(0)),
        (["chores:read", "chores:complete"], TodoListEntityFeature.UPDATE_TODO_ITEM),
        (
            ["chores:read", "chores:write"],
            TodoListEntityFeature.CREATE_TODO_ITEM | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM,
        ),
    ],
)
async def test_feature_gating(
    hass: HomeAssistant, setup, mock_api: AiohttpClientMocker, scopes, features
) -> None:
    """Supported features follow the token scopes (no scope: read-only)."""
    set_scopes(mock_api, scopes)
    await setup()
    assert hass.states.get(ENTITY).attributes["supported_features"] == int(features)
    # never delete or move
    assert not features & (
        TodoListEntityFeature.DELETE_TODO_ITEM | TodoListEntityFeature.MOVE_TODO_ITEM
    )


async def test_guest_household_is_read_only(hass: HomeAssistant, setup) -> None:
    """A guest role in a household makes its list read-only whatever the scopes."""
    await setup()
    assert hass.states.get("todo.cabin_chores").attributes["supported_features"] == 0
    assert hass.states.get(ENTITY).attributes["supported_features"] != 0
