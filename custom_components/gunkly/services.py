"""Services for Gunkly (targeting a household's to-do entity)."""

from __future__ import annotations

from typing import Any

import probatio
from homeassistant.components.todo import DOMAIN as TODO_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service

from .const import (
    ATTR_CHORE,
    ATTR_NOTE,
    ATTR_UNTIL,
    DOMAIN,
    SERVICE_COMPLETE_CHORE,
    SERVICE_PAUSE_CHORE,
    SERVICE_RESUME_CHORE,
    SERVICE_SKIP_CHORE,
    SERVICE_SNOOZE_CHORE,
    SERVICE_UNDO_COMPLETION,
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the chore actions as entity services of the household to-do list."""
    commands: tuple[tuple[str, str, dict[str | probatio.Marker, Any]], ...] = (
        (
            SERVICE_COMPLETE_CHORE,
            "async_complete_chore",
            {probatio.Required(ATTR_CHORE): cv.string, probatio.Optional(ATTR_NOTE): cv.string},
        ),
        (
            SERVICE_SNOOZE_CHORE,
            "async_snooze_chore",
            {probatio.Required(ATTR_CHORE): cv.string, probatio.Required(ATTR_UNTIL): cv.date},
        ),
        (SERVICE_SKIP_CHORE, "async_skip_chore", {probatio.Required(ATTR_CHORE): cv.string}),
        (
            SERVICE_PAUSE_CHORE,
            "async_pause_chore",
            {probatio.Required(ATTR_CHORE): cv.string, probatio.Optional(ATTR_UNTIL): cv.date},
        ),
        (SERVICE_RESUME_CHORE, "async_resume_chore", {probatio.Required(ATTR_CHORE): cv.string}),
        (
            SERVICE_UNDO_COMPLETION,
            "async_undo_completion",
            {probatio.Required(ATTR_CHORE): cv.string},
        ),
    )
    for name, func, fields in commands:
        service.async_register_platform_entity_service(
            hass,
            DOMAIN,
            name,
            entity_domain=TODO_DOMAIN,
            schema=fields,
            func=func,
        )
