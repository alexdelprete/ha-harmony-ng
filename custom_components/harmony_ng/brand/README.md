# Brand Assets

Brand images for the Home Assistant UI. Starting with HA 2026.3, custom
integrations serve brand images locally via the brands proxy API.

## Supported Files

| File | Purpose | Size |
|------|---------|------|
| `icon.png` | Square icon | 256x256 px |
| `icon@2x.png` | High-DPI icon | 512x512 px |
| `logo.png` | Rectangular logo | shortest side 128-256 px |
| `logo@2x.png` | High-DPI logo | 2x logo dimensions |
| `dark_icon.png` | Dark mode icon | same as icon |
| `dark_logo.png` | Dark mode logo | same as logo |

All files are PNG format. Dark variants are optional — the system falls back
to the standard variant when dark is not available.

Local brand images take priority over the CDN (home-assistant/brands repo).
