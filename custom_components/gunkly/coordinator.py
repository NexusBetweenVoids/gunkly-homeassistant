"""Data update coordinator for Gunkly."""

from __future__ import annotations

import dataclasses
import logging
from datetime import date, datetime, time, timedelta, tzinfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ServiceValidationError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    STATUS_OVERDUE,
    Chore,
    GunklyAuthError,
    GunklyClient,
    GunklyConnectionError,
    GunklyError,
    GunklyRateLimitError,
    TokenInfo,
)
from .const import (
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    EVENT_CHORE_OVERDUE,
)

_LOGGER = logging.getLogger(__name__)

AREA_REFRESH = 30  # polls between area name refreshes (30 min at the default interval)
AREA_RETRY = 5  # polls before refetching for an area id that is not known yet

type GunklyConfigEntry = ConfigEntry[GunklyCoordinator]
type GunklyData = dict[str, list[Chore]]


class GunklyCoordinator(DataUpdateCoordinator[GunklyData]):
    """Poll the chores of every household the token is bound to."""

    config_entry: GunklyConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GunklyConfigEntry,
        client: GunklyClient,
        token: TokenInfo,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=int(entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
            ),
        )
        self.client = client
        self.token = token
        # Household time zones, fetched once when a chore first has a reminder time.
        self.timezones: dict[str, tzinfo] = {}
        # Area names per household (empty while areas are off), fetched when chores carry an
        # area, refreshed every AREA_REFRESH polls and (at most every AREA_RETRY polls) when a
        # chore points at an area not seen yet.
        self.area_names: dict[str, dict[str, str]] = {}
        self._area_age: dict[str, int] = {}

    async def _async_update_data(self) -> GunklyData:
        previous = self.data
        data: GunklyData = {}
        try:
            for household in self.token.households:
                chores = await self.client.get_chores(household.id)
                if household.id not in self.timezones and any(c.reminder_time for c in chores):
                    self.timezones[household.id] = await self._zone(household.id)
                data[household.id] = await self._with_areas(household.id, chores)
        except GunklyAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except GunklyRateLimitError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="rate_limited",
                retry_after=err.retry_after,
            ) from err
        except GunklyConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err
        except GunklyError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err

        if previous is not None:
            self._fire_overdue_events(previous, data)
        return data

    async def _with_areas(self, household_id: str, chores: list[Chore]) -> list[Chore]:
        """Fill in area names, fetching them when needed (see area_names)."""
        ids = {c.area_id for c in chores if c.area_id}
        if not ids:
            return chores
        known = self.area_names.get(household_id)
        age = self._area_age.get(household_id, 0) + 1
        stale = (
            known is None or age >= AREA_REFRESH or (age >= AREA_RETRY and not ids <= known.keys())
        )
        if stale:
            known = self.area_names[household_id] = await self.client.get_area_names(household_id)
            age = 0
        self._area_age[household_id] = age
        names = known or {}
        return [
            dataclasses.replace(c, area_name=names.get(c.area_id)) if c.area_id else c
            for c in chores
        ]

    async def _zone(self, household_id: str) -> tzinfo:
        """The household's time zone, or Home Assistant's when it is unknown."""
        name = await self.client.get_household_timezone(household_id)
        zone = await dt_util.async_get_time_zone(name) if name else None
        return zone or dt_util.get_default_time_zone()

    def at(self, household_id: str, day: date, when: time | None) -> date | datetime:
        """A chore's day, at its reminder time when it has one (household zone)."""
        if when is None:
            return day
        zone = self.timezones.get(household_id) or dt_util.get_default_time_zone()
        return datetime.combine(day, when, tzinfo=zone)

    def _fire_overdue_events(self, previous: GunklyData, current: GunklyData) -> None:
        """Fire an event for each chore that became overdue since the last poll."""
        names = {h.id: h.name for h in self.token.households}
        for household_id, chores in current.items():
            was_overdue = {
                c.id for c in previous.get(household_id, ()) if c.status == STATUS_OVERDUE
            }
            for chore in chores:
                if chore.status == STATUS_OVERDUE and chore.id not in was_overdue:
                    self.hass.bus.async_fire(
                        EVENT_CHORE_OVERDUE,
                        {
                            "entry_id": self.config_entry.entry_id,
                            "household_id": household_id,
                            "household_name": names.get(household_id),
                            "chore_id": chore.id,
                            "chore_name": chore.name,
                            "due_date": chore.due_date.isoformat() if chore.due_date else None,
                        },
                    )

    def resolve_chore(self, household_id: str, ref: str) -> Chore:
        """Return the household's chore with this exact id, or this name (case-insensitive).

        Anything else is refused here, before any request is made.
        """
        return match_chore((self.data or {}).get(household_id, []), ref)


def match_chore(chores: list[Chore], ref: str) -> Chore:
    """Pick a chore by exact id, else by unique case-insensitive name."""
    for chore in chores:
        if chore.id == ref:
            return chore
    matches = [c for c in chores if c.name.casefold() == ref.casefold()]
    if not matches:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="chore_not_found",
            translation_placeholders={"chore": ref},
        )
    if len(matches) > 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="chore_ambiguous",
            translation_placeholders={"chore": ref, "count": str(len(matches))},
        )
    return matches[0]
