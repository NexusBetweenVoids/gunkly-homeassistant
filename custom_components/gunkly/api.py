"""Small typed async client for the Gunkly REST API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import aiohttp
from yarl import URL

from .const import MAX_CALENDAR_DAYS, REQUEST_TIMEOUT

STATUS_OVERDUE = "overdue"
STATUS_TODAY = "today"
STATUS_THIS_WEEK = "thisWeek"
STATUS_LATER = "later"
STATUS_PAUSED = "paused"
ACTIVE_STATUSES = frozenset({STATUS_OVERDUE, STATUS_TODAY, STATUS_THIS_WEEK, STATUS_LATER})


class GunklyError(Exception):
    """Base class for Gunkly API errors."""


class GunklyAuthError(GunklyError):
    """The token was rejected (HTTP 401)."""


class GunklyConnectionError(GunklyError):
    """The server could not be reached or answered with a server error."""


class GunklyRateLimitError(GunklyConnectionError):
    """The server answered 429."""

    def __init__(self, retry_after: float | None) -> None:
        """Store the Retry-After delay in seconds, when given."""
        super().__init__("rate limited")
        self.retry_after = retry_after


class GunklyApiError(GunklyError):
    """The server rejected a request (4xx other than 401/429)."""

    def __init__(self, status: int, code: str | None, message: str | None = None) -> None:
        """Store the HTTP status, Gunkly error code and the server's message, when it sends one."""
        super().__init__(f"HTTP {status}: {message or code or 'unknown'}")
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class HouseholdRef:
    """A household the token is bound to."""

    id: str
    name: str
    role: str


@dataclass(frozen=True, slots=True)
class TokenInfo:
    """Result of GET /api/v1/token."""

    id: str
    name: str
    scopes: frozenset[str]
    households: tuple[HouseholdRef, ...]
    user_name: str | None = None
    expires_at: str | None = None


@dataclass(frozen=True, slots=True)
class Chore:
    """A chore with its computed due status."""

    id: str
    name: str
    status: str
    due_date: date | None = None
    notes: str = ""
    link: str = ""
    kind: str = "recurring"
    assignees: tuple[str, ...] = field(default_factory=tuple)
    turn_name: str | None = None  # whose turn it is (chores that take turns; Gunkly 0.5+)
    # When the due-day reminder goes off, in the household's time zone (Gunkly 0.5.3+).
    reminder_time: time | None = None
    area_id: str | None = None
    # Paused chores keep their due date but are not due: until the date, or (None) until resumed.
    paused_until: date | None = None
    # Set on archived chores (completed one-offs are archived).
    archived_at: datetime | None = None
    # Resolved by the coordinator from the household's areas (when areas are on).
    area_name: str | None = None

    @property
    def active(self) -> bool:
        """Return True if the chore is due at some point (not paused/archived)."""
        return self.status in ACTIVE_STATUSES

    @property
    def paused(self) -> bool:
        """Return True if the chore is paused (indefinitely or until a date)."""
        return self.status == STATUS_PAUSED


@dataclass(frozen=True, slots=True)
class CalendarEntry:
    """One chore occurrence on a date."""

    chore_id: str
    name: str
    day: date


def normalize_url(value: str) -> str:
    """Return the base URL without trailing slash; raise ValueError if invalid."""
    value = value.strip()
    if "://" not in value:
        value = f"https://{value}"
    url = URL(value)
    if url.scheme not in ("http", "https") or not url.host:
        raise ValueError("invalid url")
    return str(url).rstrip("/")


def date_windows(
    start: date, end: date, max_days: int = MAX_CALENDAR_DAYS
) -> list[tuple[date, date]]:
    """Split the inclusive range start..end into inclusive windows of <= max_days."""
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        last = min(cursor + timedelta(days=max_days - 1), end)
        windows.append((cursor, last))
        cursor = last + timedelta(days=1)
    return windows


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_time(value: Any) -> time | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _seg(value: str) -> str:
    """Percent-encode a value so it stays a single path segment (no "/", "?", "#" or "..")."""
    return quote(value, safe="")


def _parse_chore(raw: dict[str, Any]) -> Chore:
    return Chore(
        id=str(raw["id"]),
        name=str(raw.get("name", "")),
        status=str(raw.get("status", "none")),
        due_date=_parse_date(raw.get("dueDate")),
        notes=str(raw.get("notes") or ""),
        link=str(raw.get("link") or ""),
        kind=str(raw.get("kind") or "recurring"),
        assignees=tuple(str(a) for a in raw.get("assignees") or ()),
        turn_name=str(raw["turnName"]) if raw.get("turnName") else None,
        reminder_time=_parse_time(raw.get("reminderTime")),
        area_id=str(raw["areaId"]) if raw.get("areaId") else None,
        paused_until=_parse_date(raw.get("pausedUntil")),
        archived_at=_parse_datetime(raw.get("archivedAt")),
    )


class GunklyClient:
    """Client for the Gunkly API using a shared aiohttp session."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str, token: str) -> None:
        """Initialise the client."""
        self._session = session
        self._base = f"{base_url.rstrip('/')}/api/v1"
        self._headers = {"Authorization": f"Bearer {token}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        try:
            async with self._session.request(
                method,
                f"{self._base}{path}",
                headers=self._headers,
                params=params,
                json=json,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status == HTTPStatus.UNAUTHORIZED:
                    raise GunklyAuthError
                if resp.status == HTTPStatus.TOO_MANY_REQUESTS:
                    try:
                        retry = float(resp.headers.get("Retry-After", ""))
                    except ValueError:
                        retry = None
                    raise GunklyRateLimitError(retry)
                if resp.status >= HTTPStatus.INTERNAL_SERVER_ERROR:
                    raise GunklyConnectionError(f"server error {resp.status}")
                if resp.status >= HTTPStatus.BAD_REQUEST:
                    code: str | None = None
                    message: str | None = None
                    try:
                        body = await resp.json(content_type=None)
                        code = body["error"]["code"]
                        if isinstance(msg := body["error"].get("message"), str) and msg:
                            message = msg[:200]
                    except aiohttp.ClientError, ValueError, KeyError, TypeError, AttributeError:
                        pass
                    raise GunklyApiError(resp.status, code, message)
                if resp.status == HTTPStatus.NO_CONTENT:
                    return None
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise GunklyConnectionError(str(err)) from err
        except ValueError as err:  # invalid JSON
            raise GunklyConnectionError("invalid JSON in response") from err

    @staticmethod
    def _hh(household_id: str) -> str:
        return f"/households/{_seg(household_id)}"

    def _chore(self, household_id: str, chore_id: str) -> str:
        return f"{self._hh(household_id)}/chores/{_seg(chore_id)}"

    async def get_token_info(self) -> TokenInfo:
        """Return the token's scopes and households."""
        data = await self._request("GET", "/token")
        try:
            user = data.get("user") or {}
            return TokenInfo(
                id=str(data["id"]),
                name=str(data.get("name", "")),
                scopes=frozenset(data.get("scopes") or ()),
                households=tuple(
                    HouseholdRef(str(h["id"]), str(h.get("name", h["id"])), str(h.get("role", "")))
                    for h in data.get("households") or ()
                ),
                user_name=user.get("displayName"),
                expires_at=data.get("expiresAt"),
            )
        except (KeyError, TypeError, AttributeError) as err:
            raise GunklyConnectionError("unexpected token response") from err

    async def get_chores(self, household_id: str) -> list[Chore]:
        """Return the active chores of a household."""
        data = await self._request("GET", f"{self._hh(household_id)}/chores")
        try:
            return [_parse_chore(c) for c in data]
        except (KeyError, TypeError, AttributeError) as err:
            raise GunklyConnectionError("unexpected chores response") from err

    async def get_archived_chores(self, household_id: str) -> list[Chore]:
        """Return the archived chores (completed one-offs are archived)."""
        data = await self._request(
            "GET", f"{self._hh(household_id)}/chores", params={"archived": "1"}
        )
        try:
            return [_parse_chore(c) for c in data]
        except (KeyError, TypeError, AttributeError) as err:
            raise GunklyConnectionError("unexpected chores response") from err

    async def rename_chore(self, household_id: str, chore_id: str, name: str) -> None:
        """Rename a chore: read it, then replace it with only the name changed."""
        path = self._chore(household_id, chore_id)
        raw = await self._request("GET", path)
        try:
            body: dict[str, Any] = {
                "name": name,
                "notes": str(raw.get("notes") or ""),
                "link": str(raw.get("link") or ""),
                "kind": str(raw.get("kind") or "recurring"),
                "schedule": raw["schedule"],
                "assignees": list(raw.get("assignees") or ()),
            }
        except (KeyError, TypeError, AttributeError) as err:
            raise GunklyConnectionError("unexpected chore response") from err
        # Omitted: areaId, rotation, advanceOn, reminderPreset, reminderTime (all kept as they are).
        await self._request("PUT", path, json=body)

    async def get_household_timezone(self, household_id: str) -> str | None:
        """Return the household's IANA time zone (reminder times are local to it)."""
        data = await self._request("GET", self._hh(household_id))
        zone = data.get("timezone") if isinstance(data, dict) else None
        return str(zone) if zone else None

    async def get_area_names(self, household_id: str) -> dict[str, str]:
        """Return the household's area names by id; empty while areas are off."""
        info = await self._request("GET", self._hh(household_id))
        if not isinstance(info, dict) or not info.get("areasEnabled"):
            return {}
        data = await self._request("GET", f"{self._hh(household_id)}/areas")
        try:
            return {str(a["id"]): str(a.get("name", "")) for a in data}
        except (KeyError, TypeError) as err:
            raise GunklyConnectionError("unexpected areas response") from err

    async def pause_chore(self, household_id: str, chore_id: str, until: date | None) -> None:
        """Pause a chore, until a date or indefinitely."""
        await self._request(
            "POST",
            f"{self._chore(household_id, chore_id)}/pause",
            json={"until": until.isoformat()} if until else {},
        )

    async def resume_chore(self, household_id: str, chore_id: str) -> None:
        """Resume a paused chore."""
        await self._request("POST", f"{self._chore(household_id, chore_id)}/resume")

    async def undo_last_completion(self, household_id: str, chore_id: str) -> bool:
        """Revert the chore's most recent completion; False when there is none to undo."""
        data = await self._request(
            "GET",
            f"{self._chore(household_id, chore_id)}/completions",
            params={"limit": "20"},
        )
        try:
            items = data.get("items") if isinstance(data, dict) else data
            latest = next((c for c in items or () if not c.get("revertedAt")), None)
        except (AttributeError, TypeError) as err:
            raise GunklyConnectionError("unexpected completions response") from err
        if latest is None:
            return False
        await self._request(
            "POST",
            f"{self._chore(household_id, chore_id)}/completions/{_seg(str(latest['id']))}/revert",
        )
        return True

    async def complete_chore(
        self, household_id: str, chore_id: str, note: str | None = None
    ) -> None:
        """Mark a chore done."""
        await self._request(
            "POST",
            f"{self._chore(household_id, chore_id)}/complete",
            json={"note": note} if note else {},
        )

    async def snooze_chore(self, household_id: str, chore_id: str, until: date) -> None:
        """Move the current occurrence to a later date."""
        await self._request(
            "POST",
            f"{self._chore(household_id, chore_id)}/snooze",
            json={"until": until.isoformat()},
        )

    async def skip_chore(self, household_id: str, chore_id: str) -> None:
        """Skip the current occurrence."""
        await self._request("POST", f"{self._chore(household_id, chore_id)}/skip")

    async def create_chore(self, household_id: str, name: str, due: date) -> None:
        """Create a one-off chore due on the given date."""
        await self._request(
            "POST",
            f"{self._hh(household_id)}/chores",
            json={
                "name": name,
                "kind": "oneoff",
                "schedule": {"firstDue": due.isoformat()},
            },
        )

    async def get_calendar(self, household_id: str, start: date, end: date) -> list[CalendarEntry]:
        """Return occurrences in the inclusive range, in <= 62 day requests."""
        entries: list[CalendarEntry] = []
        for window_start, window_end in date_windows(start, end):
            data = await self._request(
                "GET",
                f"{self._hh(household_id)}/calendar",
                params={"from": window_start.isoformat(), "to": window_end.isoformat()},
            )
            try:
                for item in data.get("items") or ():
                    for raw_day in item.get("dates") or ():
                        if (day := _parse_date(raw_day)) is not None:
                            entries.append(
                                CalendarEntry(str(item["choreId"]), str(item.get("name", "")), day)
                            )
            except (KeyError, TypeError, AttributeError) as err:
                raise GunklyConnectionError("unexpected calendar response") from err
        return entries


def next_due(chores: list[Chore]) -> tuple[Chore, date] | None:
    """Return the active chore with the earliest due date (overdue counts)."""
    dated = [(c.due_date, c.name, c) for c in chores if c.active and c.due_date]
    if not dated:
        return None
    due, _, chore = min(dated, key=lambda t: (t[0], t[1]))
    return chore, due
