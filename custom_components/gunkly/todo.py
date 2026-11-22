"""To-do list entity for Gunkly households."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import STATUS_LATER, STATUS_OVERDUE, STATUS_THIS_WEEK, STATUS_TODAY, HouseholdRef
from .const import (
    CONF_SHOW_LATER,
    DEFAULT_SHOW_LATER,
    DOMAIN,
    ROLE_GUEST,
    SCOPE_COMPLETE,
    SCOPE_WRITE,
)
from .coordinator import GunklyConfigEntry, GunklyCoordinator
from .entity import GunklyEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GunklyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the to-do lists."""
    coordinator = entry.runtime_data
    async_add_entities(
        GunklyTodoList(
            coordinator, household, entry.options.get(CONF_SHOW_LATER, DEFAULT_SHOW_LATER)
        )
        for household in coordinator.token.households
    )


class GunklyTodoList(GunklyEntity, TodoListEntity):
    """The chores that are due soon, as a to-do list."""

    _attr_translation_key = "chores"

    def __init__(
        self, coordinator: GunklyCoordinator, household: HouseholdRef, show_later: bool
    ) -> None:
        """Initialise the list; features follow the token's scopes."""
        super().__init__(coordinator, household, "todo")
        self._statuses = {STATUS_OVERDUE, STATUS_TODAY, STATUS_THIS_WEEK}
        if show_later:
            self._statuses.add(STATUS_LATER)
        scopes = coordinator.token.scopes
        features = TodoListEntityFeature(0)
        if household.role == ROLE_GUEST:
            # A token acts with its owner's role: guests can only read.
            self._attr_supported_features = features
            return
        if SCOPE_COMPLETE in scopes:
            features |= TodoListEntityFeature.UPDATE_TODO_ITEM
        if SCOPE_WRITE in scopes:
            features |= (
                TodoListEntityFeature.CREATE_TODO_ITEM | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
            )
        self._attr_supported_features = features

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return the open items, earliest due first."""
        chores = [c for c in self.chores if c.status in self._statuses]
        chores.sort(key=lambda c: (c.due_date is None, c.due_date, c.name))
        return [
            TodoItem(
                uid=c.id,
                summary=c.name,
                status=TodoItemStatus.NEEDS_ACTION,
                due=c.due_date,
                description=c.notes or None,
            )
            for c in chores
        ]

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Checking an item completes the chore."""
        if item.status != TodoItemStatus.COMPLETED:
            return
        if item.uid is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_item")
        await self.async_complete_chore(item.uid)

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Create a one-off chore, due today unless a date is given."""
        due = item.due
        if isinstance(due, datetime):
            due = dt_util.as_local(due).date()
        elif due is None:
            due = dt_util.now().date()
        await self.api_call(
            self.coordinator.client.create_chore(self.household.id, item.summary or "", due)
        )
