"""Sensor tests."""

from __future__ import annotations

from homeassistant.core import HomeAssistant


async def test_sensor_values(hass: HomeAssistant, setup) -> None:
    """Counts, names and the next due date come from the chore list."""
    await setup()
    overdue = hass.states.get("sensor.home_overdue_chores")
    assert overdue.state == "1"
    assert overdue.attributes["chores"] == ["Take out bins"]
    today = hass.states.get("sensor.home_chores_due_today")
    assert today.state == "1"
    assert today.attributes["chores"] == ["Water plants"]
    nxt = hass.states.get("sensor.home_next_chore_due")
    assert nxt.state == "2026-11-20"  # overdue counts; paused chores do not
    assert nxt.attributes["chore_name"] == "Take out bins"
    assert nxt.attributes["chore_id"] == "c1"


async def test_empty_household(hass: HomeAssistant, setup) -> None:
    """A household without chores reports zero and an unknown next date."""
    await setup()
    assert hass.states.get("sensor.cabin_overdue_chores").state == "0"
    assert hass.states.get("sensor.cabin_next_chore_due").state == "unknown"
