"""Sensor tests."""

from __future__ import annotations

from homeassistant.core import HomeAssistant


async def test_sensor_values(hass: HomeAssistant, setup) -> None:
    """Counts, names and the next due date come from the chore list."""
    await setup()
    overdue = hass.states.get("sensor.home_overdue_chores")
    assert overdue.state == "1"
    assert overdue.attributes["chores"] == ["Take out bins"]
    assert overdue.attributes["turns"] == {"Take out bins": "Alex"}
    today = hass.states.get("sensor.home_chores_due_today")
    assert today.state == "1"
    assert today.attributes["chores"] == ["Water plants"]
    assert today.attributes["turns"] == {}
    assert today.attributes["reminder_times"] == {"Water plants": "07:30"}
    assert overdue.attributes["reminder_times"] == {}
    nxt = hass.states.get("sensor.home_next_chore_due")
    assert nxt.state == "2026-11-20"  # overdue counts; paused chores do not
    assert nxt.attributes["chore_name"] == "Take out bins"
    assert nxt.attributes["chore_id"] == "c1"
    assert nxt.attributes["turn_name"] == "Alex"
    assert nxt.attributes["reminder_time"] is None
    assert nxt.attributes["area"] is None
    assert overdue.attributes["areas"] == {}


async def test_area_names(hass: HomeAssistant, setup, mock_api) -> None:
    """Area names come from the household's areas; with areas off there are none."""
    from .conftest import API, CHORES, HOUSEHOLD

    await setup()
    coordinator = hass.config_entries.async_entries("gunkly")[0].runtime_data
    oven = coordinator.find_chore("hh1", "c3")
    assert oven is not None and oven.area_name == "Kitchen"

    # Areas switched off in Gunkly: the next refresh of the names drops them.
    mock_api.clear_requests()
    mock_api.get(f"{API}/households/hh1/chores", json=CHORES)
    mock_api.get(f"{API}/households/hh2/chores", json=[])
    mock_api.get(f"{API}/households/hh1", json={**HOUSEHOLD, "areasEnabled": False})
    coordinator._area_age["hh1"] = 99  # due for a refresh
    await coordinator.async_refresh()
    oven = coordinator.find_chore("hh1", "c3")
    assert oven is not None and oven.area_name is None
    assert not [c for c in mock_api.mock_calls if str(c[1]).endswith("/areas")]


async def test_empty_household(hass: HomeAssistant, setup) -> None:
    """A household without chores reports zero and an unknown next date."""
    await setup()
    assert hass.states.get("sensor.cabin_overdue_chores").state == "0"
    assert hass.states.get("sensor.cabin_next_chore_due").state == "unknown"
