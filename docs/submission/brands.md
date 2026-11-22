# Draft: home-assistant/brands PR for Gunkly

Not submitted.

## Is it needed?

Recent Home Assistant releases serve brand images for custom integrations from a `brand/` folder inside the integration, and `custom_components/gunkly/brand/` ships them (checked against HA 2026.10: `homeassistant/components/brands` serves `icon.png`, `logo.png`, `dark_*` and `@2x` files from there, with fallbacks `logo` to `icon`, `icon@2x` to `icon`). Older Home Assistant versions, and the HACS UI, still read from the brands repository, so submitting the PR is still worthwhile.

## Files

Copy the images from `docs/submission/brands/` into a fork of `https://github.com/home-assistant/brands`:

```
custom_integrations/gunkly/icon.png        256x256
custom_integrations/gunkly/icon@2x.png     512x512
custom_integrations/gunkly/logo.png        256x256
custom_integrations/gunkly/logo@2x.png     512x512
custom_integrations/gunkly/dark_icon.png   256x256 (optional, for dark themes)
custom_integrations/gunkly/dark_icon@2x.png 512x512 (optional)
```

```sh
git clone https://github.com/<you>/brands && cd brands
mkdir -p custom_integrations/gunkly
cp /path/to/gunkly-homeassistant/docs/submission/brands/*.png custom_integrations/gunkly/
git checkout -b add-gunkly && git add . && git commit -m "Add Gunkly custom integration brand"
```

## Requirements to double-check against the brands README

- PNG, transparent background, square icon 256x256 and 512x512 (`@2x`), trimmed.
- Folder name equals the integration domain (`gunkly`).
- The integration's repository is public (the brands bot checks `manifest.json` for custom integrations).

## PR description draft

> Add brand images for the Gunkly custom integration (domain `gunkly`, https://github.com/NexusBetweenVoids/gunkly-homeassistant). Icon and logo are the project's own mark, supplied by the project owner.
