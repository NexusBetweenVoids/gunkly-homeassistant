# Draft: add Gunkly to the HACS default repository list

Not submitted. Do this once the repository is public, the validate workflow is green and a GitHub release exists.

## HACS requirements checklist (integration)

- [ ] Repository is public and not archived; description and topics set (for example `home-assistant`, `hacs`, `integration`).
- [ ] Issues are enabled.
- [ ] Exactly one integration under `custom_components/gunkly/`.
- [ ] `manifest.json` has `domain`, `documentation`, `issue_tracker`, `codeowners`, `name`, `version`.
- [ ] `hacs.json` in the repository root (`name`, `render_readme`, `homeassistant`).
- [ ] README describes the integration.
- [ ] The HACS Action (`hacs/action`) passes in `validate.yml`.
- [ ] hassfest passes in `validate.yml`.
- [ ] At least one full GitHub release (not just a tag), for example `v0.1.0`, whose version matches `manifest.json`.
- [ ] The submitter is the owner or a major contributor of the repository.
- [ ] Brand images: this integration ships them in `custom_components/gunkly/brand/`; if HACS validation still insists on the brands repository, send the brands PR first (see `brands.md`).

## Steps

1. Tag and release: `git tag v0.1.0 && git push origin v0.1.0`, then create a GitHub release from it.
2. Fork `https://github.com/hacs/default`, create a branch from `master`.
3. Add this line to the file `integration` (a JSON list, sorted alphabetically, one repository per line):

```json
  "NexusBetweenVoids/gunkly-homeassistant",
```

   Keep the list valid JSON (comma placement) and alphabetical order.
4. Open a PR to `hacs/default` using their PR template; link the passing workflow runs and the release.
5. Wait for the HACS bot checks and review. Fix anything it reports on this repository, then re-run the checks.

## PR description draft

> Add NexusBetweenVoids/gunkly-homeassistant: Home Assistant integration for Gunkly, a self-hosted recurring-chore tracker (to-do list, sensors, calendar, services, events). Repository passes hassfest and the HACS action; release v0.1.0 exists.
