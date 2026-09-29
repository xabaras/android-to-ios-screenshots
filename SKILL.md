---
name: android-to-ios-screenshots
version: 1.1.0
description: Converts Android app screenshots to iPhone App Store dimensions (1242x2688) with iOS status bar and home indicator overlays. Removes Android status/nav chrome via targeted inpainting, not band flattening. Use when preparing App Store screenshots from Android captures, converting screenshot dimensions for iOS, or when the user mentions android-to-ios-screenshots.
---

# Android → iOS App Store screenshots

## Quick start

Run the bundled tool (requires **Pillow**: `pip3 install Pillow`):

```bash
android-to-ios-screenshots \
  --input "/path/to/android/pngs" \
  --output "/path/to/ios/pngs" \
  --prefix iphone_
```

Or directly:

```bash
python3 ~/.cursor/skills/android-to-ios-screenshots/scripts/convert_android_to_ios_screenshots.py \
  --input "..." --output "..." --prefix iphone_
```

**Do not reimplement the pipeline.** Execute this script.

## Required inputs

- `--input` — folder with source Android PNGs (portrait)
- `--output` — folder for converted PNGs (created if missing)

Ask the user for these paths if not provided.

## Defaults (do not change unless asked)

| Flag | Value | Why |
|------|-------|-----|
| `--width` / `--height` | 1242 × 2688 | App Store 6.5" display |
| `--status-bar-crop` | 0 | Keeps decor circles under status bar |
| `--nav-bar-crop` | 48 | Removes Android gesture bar |
| `--prefix` | `iphone_` | Output naming |

For 6.7" display: `--width 1284 --height 2778`.

## Overlays

Pre-built iOS chrome lives in `assets/` next to this skill:

- `ios-status-bar-overlay.png` — Dynamic Island, time, Wi‑Fi, battery (white chrome for dark/colored app headers)
- `ios-home-indicator-overlay.png` — home indicator line (inverted to light on dark bottoms at runtime)

Normal runs use these assets. To regenerate from a native iOS simulator screenshot:

```bash
android-to-ios-screenshots \
  --status-bar-ref "/path/to/Simulator Screenshot - iPhone ....png" \
  --refresh-status-bar-overlay \
  --refresh-home-indicator-overlay \
  --input /tmp --output /tmp
```

(`--input`/`--output` still required by argparse; use any folder with at least one PNG, or a dummy folder — prefer running refresh only when user explicitly asks.)

## Visual checklist (after conversion)

For each output PNG:

- [ ] Exact dimensions (1242×2688 or requested size)
- [ ] No Android icons visible under transparent status bar areas (left, right, beside Dynamic Island)
- [ ] No flat sage rectangles in status/nav bands (never use full-band flatten)
- [ ] Status chrome is white on dark or colored headers (not dark glyphs / peach bands)
- [ ] iOS home indicator visible at bottom — **light** on dark UIs, dark on light UIs
- [ ] App UI content not cropped at sides

## Anti-patterns

- **Do not** flatten entire top/bottom bands with median colors (creates sage rectangle artifacts)
- **Do not** crop the top status area (`--status-bar-crop` must stay 0 unless user explicitly wants it)
- **Do not** copy this script into app repos — it lives in this skill package only

## Package layout

```
~/.cursor/skills/android-to-ios-screenshots/
├── README.md          ← human docs (usage + how it works)
├── SKILL.md
├── scripts/convert_android_to_ios_screenshots.py
└── assets/*.png
```

For full details, see [README.md](README.md).
