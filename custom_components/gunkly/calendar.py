"""Calendar entity for Gunkly households."""

from __future__ import annotations

from datetime import datetime, timedelta

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
    """Chore occurrences of a household as all-day events."""

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
        return CalendarEvent(
            start=due,
            end=due + timedelta(days=1),
            summary=chore.name,
            description=chore.notes or None,
            uid=f"{chore.id}-{due.isoformat()}",
        )

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
        return [
            CalendarEvent(
                start=e.day,
                end=e.day + timedelta(days=1),
                summary=e.name,
                uid=f"{e.chore_id}-{e.day.isoformat()}",
            )
            for e in sorted(entries, key=lambda e: (e.day, e.name))
        ]
