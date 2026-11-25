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


async def test_empty_household(hass: HomeAssistant, setup) -> None:
    """A household without chores reports zero and an unknown next date."""
    await setup()
    assert hass.states.get("sensor.cabin_overdue_chores").state == "0"
    assert hass.states.get("sensor.cabin_next_chore_due").state == "unknown"
