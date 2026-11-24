"""Small typed async client for the Gunkly REST API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from http import HTTPStatus
from typing import Any

import aiohttp
from yarl import URL

from .const import MAX_CALENDAR_DAYS, REQUEST_TIMEOUT

STATUS_OVERDUE = "overdue"
STATUS_TODAY = "today"
STATUS_THIS_WEEK = "thisWeek"
STATUS_LATER = "later"
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

    def __init__(self, status: int, code: str | None) -> None:
        """Store the HTTP status and Gunkly error code."""
        super().__init__(f"HTTP {status}: {code or 'unknown'}")
        self.status = status
        self.code = code


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

    @property
    def active(self) -> bool:
        """Return True if the chore is due at some point (not paused/archived)."""
        return self.status in ACTIVE_STATUSES


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
                    try:
                        body = await resp.json(content_type=None)
                        code = body["error"]["code"]
                    except aiohttp.ClientError, ValueError, KeyError, TypeError:
                        pass
                    raise GunklyApiError(resp.status, code)
                if resp.status == HTTPStatus.NO_CONTENT:
                    return None
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise GunklyConnectionError(str(err)) from err
        except ValueError as err:  # invalid JSON
            raise GunklyConnectionError("invalid JSON in response") from err

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
        data = await self._request("GET", f"/households/{household_id}/chores")
        try:
            return [_parse_chore(c) for c in data]
        except (KeyError, TypeError, AttributeError) as err:
            raise GunklyConnectionError("unexpected chores response") from err

    async def complete_chore(
        self, household_id: str, chore_id: str, note: str | None = None
    ) -> None:
        """Mark a chore done."""
        await self._request(
            "POST",
            f"/households/{household_id}/chores/{chore_id}/complete",
            json={"note": note} if note else {},
        )

    async def snooze_chore(self, household_id: str, chore_id: str, until: date) -> None:
        """Move the current occurrence to a later date."""
        await self._request(
            "POST",
            f"/households/{household_id}/chores/{chore_id}/snooze",
            json={"until": until.isoformat()},
        )

    async def skip_chore(self, household_id: str, chore_id: str) -> None:
        """Skip the current occurrence."""
        await self._request("POST", f"/households/{household_id}/chores/{chore_id}/skip")

    async def create_chore(self, household_id: str, name: str, due: date) -> None:
        """Create a one-off chore due on the given date."""
        await self._request(
            "POST",
            f"/households/{household_id}/chores",
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
                f"/households/{household_id}/calendar",
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
