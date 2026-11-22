"""Data update coordinator for Gunkly."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

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

    async def _async_update_data(self) -> GunklyData:
        previous = self.data
        data: GunklyData = {}
        try:
            for household in self.token.households:
                data[household.id] = await self.client.get_chores(household.id)
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

    def find_chore(self, household_id: str, ref: str) -> Chore | None:
        """Find a chore by id, or by unique case-insensitive name."""
        chores = (self.data or {}).get(household_id, [])
        for chore in chores:
            if chore.id == ref:
                return chore
        matches = [c for c in chores if c.name.casefold() == ref.casefold()]
        return matches[0] if len(matches) == 1 else None
