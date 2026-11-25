"""Calendar tests."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.gunkly.api import date_windows

from .conftest import API, CHORES, token_payload

ENTITY = "calendar.home_chores"


def test_date_windows() -> None:
    """Ranges are cut into inclusive windows of at most 62 days."""
    assert date_windows(date(2026, 1, 1), date(2026, 1, 1)) == [
        (date(2026, 1, 1), date(2026, 1, 1))
    ]
    assert date_windows(date(2026, 1, 1), date(2026, 3, 3)) == [
        (date(2026, 1, 1), date(2026, 3, 3))
    ]  # 62 days
    windows = date_windows(date(2026, 1, 1), date(2026, 3, 4))  # 63 days
    assert windows == [(date(2026, 1, 1), date(2026, 3, 3)), (date(2026, 3, 4), date(2026, 3, 4))]
    assert date_windows(date(2026, 2, 1), date(2026, 1, 1)) == []


async def test_next_event_state(hass: HomeAssistant, setup) -> None:
    """The entity state shows the earliest due chore."""
    await setup()
    state = hass.states.get(ENTITY)
    assert state.attributes["message"] == "Take out bins"
    assert state.attributes["all_day"] is True


async def test_get_events_chunks(hass: HomeAssistant, setup, mock_api: AiohttpClientMocker) -> None:
    """A long range makes one request per 62 days and merges the results."""
    await setup()
    mock_api.get(
        f"{API}/households/hh1/calendar",
        json={
            "items": [
                {"choreId": "c1", "name": "Take out bins", "dates": ["2026-11-01", "2026-12-20"]}
            ]
        },
    )
    start = dt_util.as_utc(datetime(2026, 11, 1))
    cal = hass.data["calendar"].get_entity(ENTITY)
    events = await cal.async_get_events(hass, start, dt_util.as_utc(datetime(2027, 3, 1)))
    calls = [
        c
        for c in mock_api.mock_calls
        if str(c[1]).endswith("/hh1/calendar") or "calendar?" in str(c[1])
    ]
    # 2026-11-01 .. 2027-02-28 = 120 days -> 2 windows
    assert len(calls) == 2
    queries = [dict(c[1].query) for c in calls]
    assert queries[0] == {"from": "2026-11-01", "to": "2027-01-01"}
    assert queries[1] == {"from": "2027-01-02", "to": "2027-02-28"}
    assert len(events) == 4  # the mock answers both windows with the same payload
    assert events[0].start == date(2026, 11, 1)
    assert events[0].end == date(2026, 11, 2)


async def test_get_events_error(hass: HomeAssistant, setup, mock_api: AiohttpClientMocker) -> None:
    """Server errors surface as HomeAssistantError."""
    await setup()
    mock_api.get(f"{API}/households/hh1/calendar", status=500)
    cal = hass.data["calendar"].get_entity(ENTITY)
    with pytest.raises(HomeAssistantError):
        await cal.async_get_events(
            hass, dt_util.as_utc(datetime(2026, 11, 1)), dt_util.as_utc(datetime(2026, 11, 8))
        )


async def test_reminder_time_events(
    hass: HomeAssistant, setup, mock_api: AiohttpClientMocker
) -> None:
    """Chores with a reminder time are short events at that time (household zone)."""
    await setup()
    mock_api.get(
        f"{API}/households/hh1/calendar",
        json={
            "items": [
                {"choreId": "c2", "name": "Water plants", "dates": ["2026-11-22"]},
                {"choreId": "c3", "name": "Clean oven", "dates": ["2026-11-25"]},
            ]
        },
    )
    cal = hass.data["calendar"].get_entity(ENTITY)
    start = dt_util.as_utc(datetime(2026, 11, 20))
    events = await cal.async_get_events(hass, start, dt_util.as_utc(datetime(2026, 11, 30)))
    timed, allday = events
    tokyo = ZoneInfo("Asia/Tokyo")
    assert timed.summary == "Water plants"
    assert timed.start == datetime(2026, 11, 22, 7, 30, tzinfo=tokyo)
    assert timed.end == datetime(2026, 11, 22, 8, 0, tzinfo=tokyo)
    assert allday.start == date(2026, 11, 25)
    assert allday.end == date(2026, 11, 26)


async def test_no_reminder_times_no_household_request(
    hass: HomeAssistant, setup, mock_api: AiohttpClientMocker
) -> None:
    """Without reminder times (older Gunkly) the household is never fetched."""
    mock_api.clear_requests()
    mock_api.get(f"{API}/token", json=token_payload())
    mock_api.get(f"{API}/households/hh1/chores", json=[{**c, "reminderTime": None} for c in CHORES])
    mock_api.get(f"{API}/households/hh2/chores", json=[])
    await setup()
    assert not [c for c in mock_api.mock_calls if str(c[1]).endswith("/households/hh1")]
    assert hass.states.get(ENTITY).attributes["all_day"] is True
