# Submission: add Gunkly to the Marketplace catalog (hacs/default)

Home Assistant 2026.11 replaced HACS with the built-in **Marketplace**. Its catalog is still the
`hacs/default` repository, and getting in still works with a pull request there. The review queue is long
(the docs say "months"); until then people install Gunkly with **Add from link** (see the README).

## Checks (all must pass; ignored checks are not accepted)

- [x] Public repository, not archived, issues enabled, description and topics set.
- [x] One integration under `custom_components/gunkly/`; domain `gunkly` does not clash with a core integration.
- [x] `manifest.json`: `domain`, `documentation`, `issue_tracker`, `codeowners`, `name`, `version`, and
      `categories` (`productivity_information.calendars_todos`; without it the HACS action warns).
- [x] `hacs.json` with `name` (and `homeassistant`, the minimum version).
- [x] Brand: `custom_components/gunkly/brand/icon.png` (see `brands.md`).
- [x] License recognised by GitHub and OSI approved: AGPL-3.0.
- [x] `validate.yml` runs the HACS action (`category: integration`, no `ignore`) and hassfest; both green
      with no warnings. The catalog runs the same `ghcr.io/hacs/action:main` image and fails new additions
      on any hassfest `[BRAND_IMAGES]` warning.
- [x] The entry sorts with `str.casefold` (their `scripts/is_sorted.py`): between
      `nextcode4u/Nightwave-UI---Home-Assistant` and `nexusplan-io/nexusplan-ha`.
- [x] A full GitHub release created **after** the validation runs passed, with the version in `manifest.json`.
- [x] Submitted by the owner, from a personal account (the PR must be editable; not from an organisation).

## Steps

1. Fork https://github.com/hacs/default (with the NexusBetweenVoids account) and create a branch from `master`.
2. In the file `integration` (a JSON list, one `"owner/repository"` per line), add this line **in
   alphabetical order**, not at the end, keeping the commas valid:

   ```json
     "NexusBetweenVoids/gunkly-homeassistant",
   ```

3. Turn on **Allow edits by maintainers** (their `edits` check fails without it).
4. Open the pull request against `hacs/default` `master` and fill in the template completely (an
   incomplete template gets the PR closed without notice): tick each checklist line and fill the links
   section (below).
5. The bot runs the checks. A failing check on our side: fix it here, make a new release, re-run. A PR set
   to draft for small issues: fix, then mark it "Ready for review" yourself.
6. Wait for review. Do not request reviewers (the template says that gets the PR closed). After the merge the next scheduled scan lists Gunkly in the Marketplace.

## Links for the PR template

- Current release: https://github.com/NexusBetweenVoids/gunkly-homeassistant/releases/latest
- HACS action run (without ignore) and hassfest run: the latest green "Validate" run,
  https://github.com/NexusBetweenVoids/gunkly-homeassistant/actions/workflows/validate.yml

## PR description draft

> Adds NexusBetweenVoids/gunkly-homeassistant: a Home Assistant integration for Gunkly, a self-hosted
> chore and home-maintenance tracker (to-do list, sensors and calendar per household, complete/snooze/skip
> actions, an overdue event). Brand images ship in `custom_components/gunkly/brand/`. The HACS action and
> hassfest pass without ignores; the release was made after they passed.
