"""Base entity for Gunkly."""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import date

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Chore, GunklyApiError, GunklyError, HouseholdRef
from .const import CONF_URL, DOMAIN, ROLE_GUEST, SCOPE_COMPLETE
from .coordinator import GunklyCoordinator


class GunklyEntity(CoordinatorEntity[GunklyCoordinator]):
    """An entity belonging to one Gunkly household."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GunklyCoordinator, household: HouseholdRef, key: str) -> None:
        """Initialise the entity and its household device."""
        super().__init__(coordinator)
        self.household = household
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{household.id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{household.id}")},
            name=household.name,
            manufacturer="Gunkly",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=entry.data[CONF_URL],
        )

    @property
    def chores(self) -> list[Chore]:
        """Return the household's chores from the last poll."""
        return self.coordinator.data.get(self.household.id, [])

    async def api_call(self, call: Awaitable[None]) -> None:
        """Await a write request, map errors, then refresh the coordinator."""
        try:
            await call
        except GunklyApiError as err:
            key = "forbidden" if err.status == 403 else "request_failed"
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=key,
                translation_placeholders={"error": str(err)},
            ) from err
        except GunklyError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="request_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()

    def chore_id(self, ref: str) -> str:
        """Resolve a chore id or unique name to an id (unknown refs pass through)."""
        chore = self.coordinator.find_chore(self.household.id, ref)
        return chore.id if chore else ref

    def _require_complete(self) -> None:
        """Refuse locally when the token cannot complete chores in this household."""
        if SCOPE_COMPLETE not in self.coordinator.token.scopes or self.household.role == ROLE_GUEST:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="missing_scope")

    async def async_complete_chore(self, chore: str, note: str | None = None) -> None:
        """Complete a chore (entity service)."""
        if SCOPE_COMPLETE not in self.coordinator.token.scopes:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="missing_scope")
        await self.api_call(
            self.coordinator.client.complete_chore(self.household.id, self.chore_id(chore), note)
        )

    async def async_snooze_chore(self, chore: str, until: date) -> None:
        """Snooze a chore (entity service)."""
        self._require_complete()
        await self.api_call(
            self.coordinator.client.snooze_chore(self.household.id, self.chore_id(chore), until)
        )

    async def async_pause_chore(self, chore: str, until: date | None = None) -> None:
        """Pause a chore until a date, or until it is resumed (entity service)."""
        self._require_complete()
        await self.api_call(
            self.coordinator.client.pause_chore(self.household.id, self.chore_id(chore), until)
        )

    async def async_resume_chore(self, chore: str) -> None:
        """Resume a paused chore (entity service)."""
        self._require_complete()
        await self.api_call(
            self.coordinator.client.resume_chore(self.household.id, self.chore_id(chore))
        )

    async def async_undo_completion(self, chore: str) -> None:
        """Undo the chore's most recent completion (entity service)."""
        self._require_complete()
        undone: list[bool] = []

        async def undo() -> None:
            undone.append(
                await self.coordinator.client.undo_last_completion(
                    self.household.id, self.chore_id(chore)
                )
            )

        await self.api_call(undo())
        if not undone[0]:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="nothing_to_undo"
            )

    async def async_skip_chore(self, chore: str) -> None:
        """Skip a chore occurrence (entity service)."""
        self._require_complete()
        await self.api_call(
            self.coordinator.client.skip_chore(self.household.id, self.chore_id(chore))
        )
