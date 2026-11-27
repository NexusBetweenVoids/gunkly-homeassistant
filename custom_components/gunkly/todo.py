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
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util

from .api import (
    STATUS_LATER,
    STATUS_OVERDUE,
    STATUS_THIS_WEEK,
    STATUS_TODAY,
    Chore,
    HouseholdRef,
)
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

TURN_KEY = f"component.{DOMAIN}.entity.todo.chores.state_attributes.turn.name"
AREA_KEY = f"component.{DOMAIN}.entity.todo.chores.state_attributes.area.name"


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
        self._turn_label = "Turn"
        self._area_label = "Area"
        self._statuses = {STATUS_OVERDUE, STATUS_TODAY, STATUS_THIS_WEEK}
        if show_later:
            self._statuses.add(STATUS_LATER)
        scopes = coordinator.token.scopes
        features = TodoListEntityFeature(0)
        if household.role == ROLE_GUEST:
            # A token acts with its owner's role: guests can only read.
            self._attr_supported_features = features
            return
        # Checking an item and moving its due date (snooze) need chores:complete, renaming and
        # creating items need chores:write.
        if SCOPE_COMPLETE in scopes or SCOPE_WRITE in scopes:
            features |= (
                TodoListEntityFeature.UPDATE_TODO_ITEM | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
            )
        if SCOPE_WRITE in scopes:
            features |= TodoListEntityFeature.CREATE_TODO_ITEM
        self._attr_supported_features = features

    async def async_added_to_hass(self) -> None:
        """Load the translated "Turn" and "Area" labels for item descriptions."""
        await super().async_added_to_hass()
        strings = await async_get_translations(
            self.hass, self.hass.config.language, "entity", {DOMAIN}
        )
        self._turn_label = strings.get(TURN_KEY, self._turn_label)
        self._area_label = strings.get(AREA_KEY, self._area_label)

    def _description(self, chore: Chore) -> str | None:
        """The area, whose turn it is (if the chore takes turns), then the notes."""
        parts = []
        if chore.area_name:
            parts.append(f"{self._area_label}: {chore.area_name}")
        if chore.turn_name:
            parts.append(f"{self._turn_label}: {chore.turn_name}")
        if chore.notes:
            parts.append(chore.notes)
        return "\n\n".join(parts) or None

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
                due=self.coordinator.at(self.household.id, c.due_date, c.reminder_time)
                if c.due_date
                else None,
                description=self._description(c),
            )
            for c in chores
        ]

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Checking an item completes the chore; the name and due date can be changed."""
        if item.uid is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_item")
        chore = self.coordinator.resolve_chore(self.household.id, item.uid)
        scopes = self.coordinator.token.scopes
        client = self.coordinator.client
        rename = item.summary is not None and item.summary.strip() not in ("", chore.name)
        due = item.due
        if isinstance(due, datetime):
            # The list shows due times in the household's zone, so compare the day there.
            zone = self.coordinator.timezones.get(self.household.id)
            due = (due.astimezone(zone) if zone and due.tzinfo else due).date()
        reschedule = due is not None and due != chore.due_date
        if (rename and SCOPE_WRITE not in scopes) or (
            (reschedule or item.status == TodoItemStatus.COMPLETED) and SCOPE_COMPLETE not in scopes
        ):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="missing_scope")

        async def update() -> None:
            if rename and item.summary:
                await client.rename_chore(self.household.id, chore.id, item.summary.strip())
            if reschedule and due is not None:
                await client.snooze_chore(self.household.id, chore.id, due)
            if item.status == TodoItemStatus.COMPLETED:
                await client.complete_chore(self.household.id, chore.id)

        if rename or reschedule or item.status == TodoItemStatus.COMPLETED:
            await self.api_call(update())

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
