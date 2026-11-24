# Gunkly for Home Assistant

[![Validate](https://github.com/NexusBetweenVoids/gunkly-homeassistant/actions/workflows/validate.yml/badge.svg)](https://github.com/NexusBetweenVoids/gunkly-homeassistant/actions/workflows/validate.yml)
[![Tests](https://github.com/NexusBetweenVoids/gunkly-homeassistant/actions/workflows/tests.yml/badge.svg)](https://github.com/NexusBetweenVoids/gunkly-homeassistant/actions/workflows/tests.yml)

A Home Assistant custom integration for [Gunkly](https://github.com/NexusBetweenVoids/gunkly), the self-hosted recurring-chore tracker. It polls your Gunkly server (local polling, default every 60 seconds) and gives each household:

- a **to-do list** of the chores that need doing, which you can tick off,
- **sensors** for overdue chores, chores due today and the next chore due,
- a **calendar** of upcoming chore occurrences,
- **actions** to complete, snooze or skip a chore from automations,
- a **`gunkly_chore_overdue` event** when a chore becomes overdue.

It uses only Home Assistant's own HTTP client; there are no extra Python dependencies. Requires Home Assistant 2026.10 or newer.

<!-- Screenshots to add: to-do card, household device page, calendar card, config flow -->

## Installation

### HACS (custom repository)

1. In HACS open the three-dot menu, then **Custom repositories**.
2. Add `https://github.com/NexusBetweenVoids/gunkly-homeassistant` with type **Integration**.
3. Search for **Gunkly**, download it and restart Home Assistant.

### Manual

Copy `custom_components/gunkly` from this repository into the `custom_components` folder of your Home Assistant configuration and restart.

## Create an API token in Gunkly

1. In Gunkly open **Account, Integrations** and create a token (step-up verification is required).
2. Pick the households the token may access.
3. Recommended scopes:
   - `chores:read` (required): lists, sensors, calendar.
   - `chores:complete`: lets you tick off chores in the to-do list and use `gunkly.complete_chore`.
   - `chores:write`: lets you add items to the to-do list, which creates one-off chores.
4. Copy the token (`gk_...`). It is shown once.

A token acts with its owner's role in each household, so a household where you are only a guest stays read-only whatever the scopes. Gunkly limits a token to 120 requests per minute; the default polling uses one request per household per minute.

## Setup

**Settings, Devices & services, Add integration, Gunkly.** Enter the server address (for example `https://gunkly.example.com` or `http://192.168.1.10:4865`) and the token. One device is created per household the token is bound to. If the token is revoked or expires, Home Assistant asks you to enter a new one (reauthentication).

### Options

| Option | Default | Meaning |
| --- | --- | --- |
| Update interval | 60 s | How often Gunkly is polled (30 to 3600 s). |
| Also list chores that are due later | off | By default the to-do list shows overdue chores and chores due up to this week. |

### Removal

Delete the integration from **Settings, Devices & services**, then (optionally) revoke the token in Gunkly under Account, Integrations. Nothing else is stored.

## Entities (per household)

| Entity | Description |
| --- | --- |
| `todo.<household>_chores` | Overdue, today and this-week chores (plus later ones if enabled), earliest due first, with due date and notes; for chores that take turns the description starts with whose turn it is (Gunkly 0.5 or newer). Checking an item completes the chore (needs `chores:complete`). Adding an item creates a one-off chore due that day, today by default (needs `chores:write`). Items cannot be deleted or reordered. Without the scopes the list is read-only. |
| `sensor.<household>_overdue_chores` | Number of overdue chores; attribute `chores` lists their names, `turns` maps each chore that takes turns to whose turn it is. |
| `sensor.<household>_chores_due_today` | Number of chores due today; attributes `chores` and `turns` as above. |
| `sensor.<household>_next_chore_due` | Date of the earliest due active chore (overdue chores count, paused ones do not); attributes `chore_id`, `chore_name`, `turn_name` (whose turn it is, if the chore takes turns). |
| `calendar.<household>_chores` | Chore occurrences as all-day events. Ranges longer than Gunkly's 62-day limit are fetched in several requests. |

## Actions

All actions target the household's to-do entity (or its device or area) and take the chore **id or exact name**.

| Action | Fields | Needs |
| --- | --- | --- |
| `gunkly.complete_chore` | `chore`, optional `note` | `chores:complete` |
| `gunkly.snooze_chore` | `chore`, `until` (date, today or later) | `chores:complete` |
| `gunkly.skip_chore` | `chore` | `chores:complete` |

## Events

`gunkly_chore_overdue` fires once when a chore becomes overdue between two polls (never on the first poll after startup). Data: `entry_id`, `household_id`, `household_name`, `chore_id`, `chore_name`, `due_date`.

## Example automations

Announce a newly overdue chore:

```yaml
automation:
  - alias: Chore became overdue
    triggers:
      - trigger: event
        event_type: gunkly_chore_overdue
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "{{ trigger.event.data.chore_name }} is overdue ({{ trigger.event.data.household_name }})"
```

Morning reminder when something is due:

```yaml
automation:
  - alias: Chores today
    triggers:
      - trigger: time
        at: "08:00:00"
    conditions:
      - condition: numeric_state
        entity_id: sensor.home_chores_due_today
        above: 0
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "Due today: {{ state_attr('sensor.home_chores_due_today', 'chores') | join(', ') }}"
```

Mark a chore done when the washing machine finishes:

```yaml
automation:
  - alias: Washer done
    triggers:
      - trigger: state
        entity_id: binary_sensor.washer_running
        to: "off"
    actions:
      - action: gunkly.complete_chore
        target:
          entity_id: todo.home_chores
        data:
          chore: Clean washing machine filter
          note: Marked by Home Assistant
```

## Development

```sh
uv venv && uv pip install -r requirements_test.txt
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy custom_components
```

## License

[AGPL-3.0](LICENSE), like Gunkly itself.
