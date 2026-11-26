"""Calendar entity for Gunkly households."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import GunklyError, HouseholdRef, next_due
from .const import DOMAIN
from .coordinator import GunklyConfigEntry, GunklyCoordinator
from .entity import GunklyEntity

PARALLEL_UPDATES = 0

# A chore with a reminder time becomes a short event starting then (so calendar
# triggers fire at that time); without one it stays an all-day event.
TIMED_EVENT = timedelta(minutes=30)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GunklyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the calendars."""
    coordinator = entry.runtime_data
    async_add_entities(
        GunklyCalendar(coordinator, household) for household in coordinator.token.households
    )


class GunklyCalendar(GunklyEntity, CalendarEntity):
    """Chore occurrences of a household: at their reminder time, else all day."""

    _attr_translation_key = "chores"

    def __init__(self, coordinator: GunklyCoordinator, household: HouseholdRef) -> None:
        """Initialise the calendar."""
        super().__init__(coordinator, household, "calendar")

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next due chore as the current/next event."""
        if (found := next_due(self.chores)) is None:
            return None
        chore, due = found
        start, end = self._span(due, chore.reminder_time)
        return CalendarEvent(
            start=start,
            end=end,
            summary=chore.name,
            description=chore.notes or None,
            location=chore.area_name,
            uid=f"{chore.id}-{due.isoformat()}",
        )

    def _span(self, day: date, when: time | None) -> tuple[date | datetime, date | datetime]:
        start = self.coordinator.at(self.household.id, day, when)
        if isinstance(start, datetime):
            return start, start + TIMED_EVENT
        return start, start + timedelta(days=1)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return occurrences between start_date and end_date."""
        first = dt_util.as_local(start_date).date()
        last = dt_util.as_local(end_date - timedelta(microseconds=1)).date()
        if last < first:
            return []
        try:
            entries = await self.coordinator.client.get_calendar(self.household.id, first, last)
        except GunklyError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="request_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        times = {c.id: c.reminder_time for c in self.chores}
        areas = {c.id: c.area_name for c in self.chores}
        events = []
        for e in sorted(entries, key=lambda e: (e.day, e.name)):
            begin, end = self._span(e.day, times.get(e.chore_id))
            events.append(
                CalendarEvent(
                    start=begin,
                    end=end,
                    summary=e.name,
                    location=areas.get(e.chore_id),
                    uid=f"{e.chore_id}-{e.day.isoformat()}",
                )
            )
        return events
