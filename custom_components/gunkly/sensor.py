"""Sensors for Gunkly households."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import STATUS_OVERDUE, STATUS_TODAY, Chore, HouseholdRef, next_due
from .coordinator import GunklyConfigEntry, GunklyCoordinator
from .entity import GunklyEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GunklySensorDescription(SensorEntityDescription):
    """Describe a Gunkly sensor."""

    value_fn: Callable[[list[Chore]], int | date | None]
    attrs_fn: Callable[[list[Chore]], dict[str, Any]]


def _names(status: str) -> Callable[[list[Chore]], dict[str, Any]]:
    def attrs(chores: list[Chore]) -> dict[str, Any]:
        found = [c for c in chores if c.status == status]
        return {
            "chores": [c.name for c in found],
            "turns": {c.name: c.turn_name for c in found if c.turn_name},
            "reminder_times": {
                c.name: c.reminder_time.strftime("%H:%M") for c in found if c.reminder_time
            },
        }

    return attrs


def _count(status: str) -> Callable[[list[Chore]], int]:
    return lambda chores: sum(1 for c in chores if c.status == status)


def _next_attrs(chores: list[Chore]) -> dict[str, Any]:
    if (found := next_due(chores)) is None:
        return {}
    return {
        "chore_id": found[0].id,
        "chore_name": found[0].name,
        "turn_name": found[0].turn_name,
        "reminder_time": found[0].reminder_time.strftime("%H:%M")
        if found[0].reminder_time
        else None,
    }


def _next_value(chores: list[Chore]) -> date | None:
    return found[1] if (found := next_due(chores)) else None


SENSORS: tuple[GunklySensorDescription, ...] = (
    GunklySensorDescription(
        key="overdue",
        translation_key="overdue",
        native_unit_of_measurement="chores",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_count(STATUS_OVERDUE),
        attrs_fn=_names(STATUS_OVERDUE),
    ),
    GunklySensorDescription(
        key="due_today",
        translation_key="due_today",
        native_unit_of_measurement="chores",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_count(STATUS_TODAY),
        attrs_fn=_names(STATUS_TODAY),
    ),
    GunklySensorDescription(
        key="next_due",
        translation_key="next_due",
        device_class=SensorDeviceClass.DATE,
        value_fn=_next_value,
        attrs_fn=_next_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GunklyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        GunklySensor(coordinator, household, description)
        for household in coordinator.token.households
        for description in SENSORS
    )


class GunklySensor(GunklyEntity, SensorEntity):
    """A household summary sensor."""

    entity_description: GunklySensorDescription

    def __init__(
        self,
        coordinator: GunklyCoordinator,
        household: HouseholdRef,
        description: GunklySensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, household, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | date | None:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.chores)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the chore names behind the value."""
        return self.entity_description.attrs_fn(self.chores)
