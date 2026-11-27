"""Base entity for Gunkly."""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import UTC, date, datetime
from http import HTTPStatus

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from yarl import URL

from .api import Chore, GunklyApiError, GunklyError, HouseholdRef
from .const import CONF_URL, DOMAIN, ROLE_GUEST, SCOPE_COMPLETE
from .coordinator import GunklyCoordinator

# Rejections the caller can fix, by HTTP status (the server answers 400 for a bad value, 404 for
# an unknown chore, 409 for an archived chore or no further occurrence).
REJECTION_KEYS: dict[int, str] = {
    HTTPStatus.BAD_REQUEST: "request_invalid",
    HTTPStatus.NOT_FOUND: "request_not_found",
    HTTPStatus.CONFLICT: "request_conflict",
}


def _device_name(coordinator: GunklyCoordinator, household: HouseholdRef) -> str:
    """The household's name; with the server host added when several Gunkly accounts exist."""
    entry = coordinator.config_entry
    if len(coordinator.hass.config_entries.async_entries(DOMAIN)) > 1 and (
        host := URL(entry.data[CONF_URL]).host
    ):
        return f"{household.name} ({host})"
    return household.name


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
            name=_device_name(coordinator, household),
            manufacturer="Gunkly",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=entry.data[CONF_URL],
        )

    @property
    def chores(self) -> list[Chore]:
        """Return the household's chores from the last poll."""
        return self.coordinator.data.get(self.household.id, [])

    async def _guard[T](self, call: Awaitable[T]) -> T:
        """Await a request and map Gunkly errors to Home Assistant ones."""
        try:
            return await call
        except GunklyApiError as err:
            detail = err.message or err.code or f"HTTP {err.status}"
            if err.status == HTTPStatus.FORBIDDEN:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="forbidden",
                    translation_placeholders={"error": detail},
                ) from err
            if key := REJECTION_KEYS.get(err.status):
                # The caller can fix these: wrong value, unknown or archived chore.
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key=key,
                    translation_placeholders={"error": detail},
                ) from err
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="request_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except GunklyError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="request_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def api_call(self, call: Awaitable[None]) -> None:
        """Await a write request, map errors, then refresh so the state is current on return."""
        await self._guard(call)
        await self.coordinator.async_refresh()

    def chore_id(self, ref: str) -> str:
        """Resolve a chore id or name to the id of a known chore (anything else is refused)."""
        return self.coordinator.resolve_chore(self.household.id, ref).id

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

    async def _chore_for_undo(self, ref: str) -> Chore:
        """An active chore, or else a completed (archived) one-off, by id or exact name."""
        try:
            return self.coordinator.resolve_chore(self.household.id, ref)
        except ServiceValidationError as err:
            if err.translation_key != "chore_not_found":
                raise
            archived = await self._guard(
                self.coordinator.client.get_archived_chores(self.household.id)
            )
            found = [c for c in archived if c.kind == "oneoff"]
            by_id = [c for c in found if c.id == ref]
            matches = by_id or [c for c in found if c.name.casefold() == ref.casefold()]
            if not matches:
                raise
            # Several archived one-offs may share a name: take the most recently completed.
            return max(matches, key=lambda c: c.archived_at or datetime.min.replace(tzinfo=UTC))

    async def async_undo_completion(self, chore: str) -> None:
        """Undo the chore's most recent completion (entity service)."""
        self._require_complete()
        target = await self._chore_for_undo(chore)
        undone: list[bool] = []

        async def undo() -> None:
            undone.append(
                await self.coordinator.client.undo_last_completion(self.household.id, target.id)
            )

        await self.api_call(undo())
        if not undone[0]:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="nothing_to_undo"
            )

    async def async_skip_chore(self, chore: str) -> None:
        """Skip a chore occurrence (entity service)."""
        self._require_complete()
        target = self.coordinator.resolve_chore(self.household.id, chore)
        if target.kind == "oneoff":
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="skip_oneoff",
                translation_placeholders={"chore": target.name},
            )
        await self.api_call(self.coordinator.client.skip_chore(self.household.id, target.id))
