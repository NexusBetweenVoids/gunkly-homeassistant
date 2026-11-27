"""Service tests."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.gunkly.const import DOMAIN

from .conftest import API, TOKEN, set_chores, set_scopes

ENTITY = "todo.home_chores"


def _posts(mock: AiohttpClientMocker) -> list[tuple]:
    return [c for c in mock.mock_calls if c[0] == "POST"]


async def test_complete_by_id_and_name(hass: HomeAssistant, setup, mock_api) -> None:
    """The chore may be an id or an exact (case-insensitive) name."""
    await setup()
    mock_api.post(f"{API}/households/hh1/chores/c1/complete", status=201, json={})
    mock_api.post(f"{API}/households/hh1/chores/c3/complete", status=201, json={})
    await hass.services.async_call(
        DOMAIN,
        "complete_chore",
        {"entity_id": ENTITY, "chore": "c1", "note": "done"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN, "complete_chore", {"entity_id": ENTITY, "chore": "clean OVEN"}, blocking=True
    )
    posts = _posts(mock_api)
    assert str(posts[0][1]).endswith("/chores/c1/complete")
    assert posts[0][2] == {"note": "done"}
    assert str(posts[1][1]).endswith("/chores/c3/complete")


async def test_complete_needs_scope(hass: HomeAssistant, setup, mock_api) -> None:
    """Completing without chores:complete is refused locally."""
    set_scopes(mock_api, ["chores:read"])
    await setup()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "complete_chore", {"entity_id": ENTITY, "chore": "c1"}, blocking=True
        )
    assert not _posts(mock_api)


async def test_snooze_and_skip(hass: HomeAssistant, setup, mock_api) -> None:
    """Snooze sends the date; skip posts to the skip endpoint."""
    await setup()
    mock_api.post(f"{API}/households/hh1/chores/c2/snooze", json={})
    mock_api.post(f"{API}/households/hh1/chores/c2/skip", json={})
    await hass.services.async_call(
        DOMAIN,
        "snooze_chore",
        {"entity_id": ENTITY, "chore": "Water plants", "until": "2026-11-30"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN, "skip_chore", {"entity_id": ENTITY, "chore": "c2"}, blocking=True
    )
    posts = _posts(mock_api)
    assert posts[0][2] == {"until": "2026-11-30"}
    assert str(posts[1][1]).endswith("/chores/c2/skip")


async def test_server_rejections_are_explained(hass: HomeAssistant, setup, mock_api) -> None:
    """A server 4xx becomes a validation error naming the server's code, never the token."""
    await setup()
    mock_api.post(
        f"{API}/households/hh1/chores/c1/snooze", status=400, json={"error": {"code": "invalid"}}
    )
    mock_api.post(
        f"{API}/households/hh1/chores/c1/pause",
        status=409,
        json={"error": {"code": "conflict", "message": "chore is archived"}},
    )
    with pytest.raises(ServiceValidationError, match=r"invalid.*today or later") as exc:
        await hass.services.async_call(
            DOMAIN,
            "snooze_chore",
            {"entity_id": ENTITY, "chore": "c1", "until": "2020-01-01"},
            blocking=True,
        )
    assert TOKEN not in str(exc.value)
    with pytest.raises(ServiceValidationError, match="chore is archived"):
        await hass.services.async_call(
            DOMAIN, "pause_chore", {"entity_id": ENTITY, "chore": "c1"}, blocking=True
        )


@pytest.mark.parametrize("ref", ["nope", "does-not-exist/../c1", "c1/pause?x=", "", "../c1", "c1/"])
async def test_unknown_chore_refused_before_any_request(
    hass: HomeAssistant, setup, mock_api, ref
) -> None:
    """Only a known chore id or name is accepted: anything else never reaches the server."""
    await setup()
    before = len(mock_api.mock_calls)
    for service, extra in (
        ("snooze_chore", {"until": "2026-12-01"}),
        ("skip_chore", {}),
        ("complete_chore", {}),
        ("pause_chore", {}),
        ("resume_chore", {}),
        ("undo_completion", {}),
    ):
        with pytest.raises(ServiceValidationError, match="not found"):
            await hass.services.async_call(
                DOMAIN, service, {"entity_id": ENTITY, "chore": ref, **extra}, blocking=True
            )
    # only the archived lookup of undo may be requested, never a write
    assert not _posts(mock_api)
    assert all(c[0] == "GET" and "archived" in str(c[1]) for c in mock_api.mock_calls[before:])


async def test_ambiguous_name(hass: HomeAssistant, setup, mock_api) -> None:
    """Two chores with one name: refused with a hint to use the id; the id still works."""
    from .conftest import CHORES, chore

    set_chores(mock_api, [*CHORES, chore("c9", "TAKE OUT BINS", "later", "2026-12-30")])
    await setup()
    with pytest.raises(ServiceValidationError, match="matches 2 chores, use the chore id"):
        await hass.services.async_call(
            DOMAIN, "skip_chore", {"entity_id": ENTITY, "chore": "take out bins"}, blocking=True
        )
    mock_api.post(f"{API}/households/hh1/chores/c9/skip", json={})
    await hass.services.async_call(
        DOMAIN, "skip_chore", {"entity_id": ENTITY, "chore": "c9"}, blocking=True
    )
    assert len(_posts(mock_api)) == 1


async def test_skip_oneoff_refused_locally(hass: HomeAssistant, setup, mock_api) -> None:
    """A one-off chore does not repeat, so skipping it is explained without a request."""
    from .conftest import CHORES, chore

    set_chores(
        mock_api, [*CHORES, chore("c8", "Buy filters", "today", "2026-11-22", kind="oneoff")]
    )
    await setup()
    with pytest.raises(ServiceValidationError, match="one-off"):
        await hass.services.async_call(
            DOMAIN, "skip_chore", {"entity_id": ENTITY, "chore": "Buy filters"}, blocking=True
        )
    assert not _posts(mock_api)


async def test_state_is_current_after_back_to_back_actions(
    hass: HomeAssistant, setup, mock_api
) -> None:
    """Every action refreshes at once, not debounced to the next poll."""
    await setup()
    mock_api.post(f"{API}/households/hh1/chores/c1/skip", json={})
    mock_api.post(f"{API}/households/hh1/chores/c2/skip", json={})

    def lists() -> int:
        return len([c for c in mock_api.mock_calls if str(c[1]).endswith("/hh1/chores")])

    start = lists()
    for chore_id in ("c1", "c2"):
        await hass.services.async_call(
            DOMAIN, "skip_chore", {"entity_id": ENTITY, "chore": chore_id}, blocking=True
        )
    assert lists() == start + 2


async def test_undo_completed_oneoff_by_name(hass: HomeAssistant, setup, mock_api) -> None:
    """A completed one-off is found by name (latest completed) and its completion reverted."""
    from .conftest import CHORES, chore

    old = chore(
        "a1", "Buy filters", "archived", None, kind="oneoff", archivedAt="2026-11-01T10:00:00Z"
    )
    new = chore(
        "a2", "buy filters", "archived", None, kind="oneoff", archivedAt="2026-11-20T10:00:00Z"
    )
    rec = chore("a3", "Buy filters", "archived", None, archivedAt="2026-11-25T10:00:00Z")
    set_chores(mock_api, CHORES, archived=[old, new, rec])
    await setup()
    mock_api.get(
        f"{API}/households/hh1/chores/a2/completions",
        json={"items": [{"id": "k1", "revertedAt": None}], "next": None},
    )
    mock_api.post(f"{API}/households/hh1/chores/a2/completions/k1/revert", json={})
    await hass.services.async_call(
        DOMAIN, "undo_completion", {"entity_id": ENTITY, "chore": "Buy Filters"}, blocking=True
    )
    posts = _posts(mock_api)
    assert len(posts) == 1 and str(posts[0][1]).endswith("/chores/a2/completions/k1/revert")


async def test_path_segments_are_encoded(hass: HomeAssistant, setup, mock_api) -> None:
    """The client keeps every id one path segment, whatever it contains."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from custom_components.gunkly.api import GunklyClient

    await setup()
    client = GunklyClient(async_get_clientsession(hass), "https://gunkly.test", "gk_x")
    mock_api.post(f"{API}/households/h%2Fh%3F/chores/x%2F..%2Fy%3Fz%23/skip", json={})
    await client.skip_chore("h/h?", "x/../y?z#")
    url = _posts(mock_api)[0][1]
    assert url.raw_path == "/api/v1/households/h%2Fh%3F/chores/x%2F..%2Fy%3Fz%23/skip"
    assert not url.query_string


@pytest.mark.parametrize("service", ["snooze_chore", "skip_chore"])
async def test_snooze_skip_need_scope(hass: HomeAssistant, setup, mock_api, service) -> None:
    """Snooze and skip need chores:complete like complete does."""
    set_scopes(mock_api, ["chores:read", "chores:write"])
    await setup()
    data = {"entity_id": ENTITY, "chore": "c1"}
    if service == "snooze_chore":
        data["until"] = "2026-12-01"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, service, data, blocking=True)
    assert not _posts(mock_api)


async def test_guest_household_refuses_actions(hass: HomeAssistant, setup, mock_api) -> None:
    """A guest role refuses actions locally even with all scopes."""
    await setup()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "skip_chore", {"entity_id": "todo.cabin_chores", "chore": "c1"}, blocking=True
        )
    assert not _posts(mock_api)


async def test_pause_resume(hass: HomeAssistant, setup, mock_api) -> None:
    """Pause sends an optional date, resume posts; paused chores resolve by name too."""
    await setup()
    mock_api.post(f"{API}/households/hh1/chores/c1/pause", json={})
    mock_api.post(f"{API}/households/hh1/chores/c5/pause", json={})
    mock_api.post(f"{API}/households/hh1/chores/c5/resume", json={})
    await hass.services.async_call(
        DOMAIN,
        "pause_chore",
        {"entity_id": ENTITY, "chore": "Take out bins", "until": "2026-12-24"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN, "pause_chore", {"entity_id": ENTITY, "chore": "c5"}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "resume_chore", {"entity_id": ENTITY, "chore": "Paused thing"}, blocking=True
    )
    posts = _posts(mock_api)
    assert str(posts[0][1]).endswith("/chores/c1/pause")
    assert posts[0][2] == {"until": "2026-12-24"}
    assert posts[1][2] == {}
    assert str(posts[2][1]).endswith("/chores/c5/resume")


async def test_undo_completion(hass: HomeAssistant, setup, mock_api) -> None:
    """Undo reverts the most recent completion that is not reverted yet."""
    await setup()
    mock_api.get(
        f"{API}/households/hh1/chores/c1/completions",
        json={
            "items": [
                {"id": "k3", "revertedAt": "2026-11-21T10:00:00Z"},
                {"id": "k2", "revertedAt": None},
                {"id": "k1", "revertedAt": None},
            ],
            "next": None,
        },
    )
    mock_api.post(f"{API}/households/hh1/chores/c1/completions/k2/revert", status=204)
    await hass.services.async_call(
        DOMAIN, "undo_completion", {"entity_id": ENTITY, "chore": "Take out bins"}, blocking=True
    )
    posts = _posts(mock_api)
    assert len(posts) == 1 and str(posts[0][1]).endswith("/completions/k2/revert")


async def test_undo_nothing(hass: HomeAssistant, setup, mock_api) -> None:
    """With no completion left to undo the action says so and changes nothing."""
    await setup()
    mock_api.get(f"{API}/households/hh1/chores/c3/completions", json={"items": [], "next": None})
    with pytest.raises(ServiceValidationError, match="no completion to undo"):
        await hass.services.async_call(
            DOMAIN, "undo_completion", {"entity_id": ENTITY, "chore": "c3"}, blocking=True
        )
    assert not _posts(mock_api)


@pytest.mark.parametrize("service", ["pause_chore", "resume_chore", "undo_completion"])
async def test_new_actions_need_scope(hass: HomeAssistant, setup, mock_api, service) -> None:
    """Pause, resume and undo need chores:complete like completing does."""
    set_scopes(mock_api, ["chores:read", "chores:write"])
    await setup()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, service, {"entity_id": ENTITY, "chore": "c1"}, blocking=True
        )
    assert not _posts(mock_api)
