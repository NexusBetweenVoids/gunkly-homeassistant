# Brand images: no home-assistant/brands PR needed

Since Home Assistant 2026.3, custom integrations ship their brand images themselves, and the brands
repository calls its `custom_integrations` folder legacy. Gunkly's images are in
`custom_components/gunkly/brand/` (`icon.png` 256x256, `icon@2x.png` 512x512, `logo.png`, `logo@2x.png`,
`dark_icon.png`, `dark_icon@2x.png`). Local images take precedence over the brands repository.

The catalog's "brands" check accepts this: "a `brand` folder with at least an `icon.png`, or images for
the domain in the brands repository". The Marketplace syncs the icon from the latest release.

If the integration ever moves into Home Assistant core, remove `brand/` and add the images to
home-assistant/brands instead.
