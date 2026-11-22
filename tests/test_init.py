"""Coordinator, setup and error mapping tests."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.gunkly.const import CONF_POLL_INTERVAL, EVENT_CHORE_OVERDUE

from .conftest import API, CHORES, chore


async def test_setup_and_unload(hass: HomeAssistant, setup) -> None:
    """The entry loads, creates a device per household and unloads."""
    entry = await setup()
    assert entry.state is ConfigEntryState.LOADED
    assert len(hass.states.async_entity_ids("todo")) == 2
    assert len(hass.states.async_entity_ids("calendar")) == 2
    assert len(hass.states.async_entity_ids("sensor")) == 6
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_auth_failure_starts_reauth(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """A rejected token at setup triggers reauth."""
    aioclient_mock.get(f"{API}/token", status=401)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(hass.config_entries.flow.async_progress_by_handler("gunkly"))


async def test_setup_connection_failure_retries(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """An unreachable server leaves the entry in setup retry."""
    aioclient_mock.get(f"{API}/token", exc=TimeoutError)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_first_refresh_errors(
    hass: HomeAssistant, entry: MockConfigEntry, mock_api: AiohttpClientMocker
) -> None:
    """Chore fetch failures map to retry (server error) and reauth (401)."""
    mock_api.clear_requests()
    from .conftest import token_payload

    mock_api.get(f"{API}/token", json=token_payload())
    mock_api.get(f"{API}/households/hh1/chores", status=429, headers={"Retry-After": "30"})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY

    await hass.config_entries.async_unload(entry.entry_id)
    mock_api.clear_requests()
    mock_api.get(f"{API}/token", json=token_payload())
    mock_api.get(f"{API}/households/hh1/chores", status=401)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_update_failure_marks_unavailable_then_recovers(
    hass: HomeAssistant, setup, mock_api: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    """A failed poll makes entities unavailable; the next good poll restores them."""
    await setup()
    mock_api.clear_requests()
    mock_api.get(f"{API}/households/hh1/chores", status=500)
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("todo.home_chores").state == "unavailable"

    mock_api.clear_requests()
    mock_api.get(f"{API}/households/hh1/chores", json=CHORES)
    mock_api.get(f"{API}/households/hh2/chores", json=[])
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("todo.home_chores").state == "3"


async def test_poll_interval_option(hass: HomeAssistant, entry: MockConfigEntry, setup) -> None:
    """The poll interval option is applied."""
    await setup({CONF_POLL_INTERVAL: 300})
    assert entry.runtime_data.update_interval == timedelta(seconds=300)


async def test_overdue_event(
    hass: HomeAssistant, setup, mock_api: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    """Only chores that newly became overdue fire an event."""
    events = async_capture_events(hass, EVENT_CHORE_OVERDUE)
    await setup()
    assert events == []  # the first poll never fires

    chores = [dict(c) for c in CHORES]
    chores[1] = chore("c2", "Water plants", "overdue", "2026-11-22", notes="Fern needs extra")
    mock_api.clear_requests()
    mock_api.get(f"{API}/households/hh1/chores", json=chores)
    mock_api.get(f"{API}/households/hh2/chores", json=[])
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["chore_id"] == "c2"
    assert events[0].data["household_name"] == "Home"
    assert events[0].data["due_date"] == "2026-11-22"

    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(events) == 1  # still overdue, no repeat
