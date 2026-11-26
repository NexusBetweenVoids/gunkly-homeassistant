"""Constants for the Gunkly integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "gunkly"

CONF_URL: Final = "url"
CONF_TOKEN: Final = "token"
CONF_POLL_INTERVAL: Final = "poll_interval"
CONF_SHOW_LATER: Final = "show_later"

DEFAULT_POLL_INTERVAL: Final = 60  # seconds
MIN_POLL_INTERVAL: Final = 30
MAX_POLL_INTERVAL: Final = 3600
DEFAULT_SHOW_LATER: Final = False

REQUEST_TIMEOUT: Final = 15  # seconds
MAX_CALENDAR_DAYS: Final = 62  # server limit, inclusive

SCOPE_READ: Final = "chores:read"
SCOPE_COMPLETE: Final = "chores:complete"
SCOPE_WRITE: Final = "chores:write"

ROLE_GUEST: Final = "guest"

EVENT_CHORE_OVERDUE: Final = "gunkly_chore_overdue"

ATTR_CHORE: Final = "chore"
ATTR_NOTE: Final = "note"
ATTR_UNTIL: Final = "until"
SERVICE_COMPLETE_CHORE: Final = "complete_chore"
SERVICE_SNOOZE_CHORE: Final = "snooze_chore"
SERVICE_SKIP_CHORE: Final = "skip_chore"
SERVICE_PAUSE_CHORE: Final = "pause_chore"
SERVICE_RESUME_CHORE: Final = "resume_chore"
SERVICE_UNDO_COMPLETION: Final = "undo_completion"

DEFAULT_SCAN_INTERVAL: Final = timedelta(seconds=DEFAULT_POLL_INTERVAL)
