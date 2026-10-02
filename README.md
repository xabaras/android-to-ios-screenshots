# android-to-ios-screenshots

**Version:** 1.1.0

Convert Android app screenshots into PNGs ready for **App Store Connect** (iPhone 6.5" format, 1242×2688) directly into your AI agents of choice.

Built for **KMP/Compose** apps (same UI on Android and iOS): capture screenshots on an Android device or emulator and reuse them for the iOS App Store listing, with an iOS status bar and home indicator, and no visible Android system visuals.

## Changelog

### 1.1.0

- Dark-friendly status bar overlay (white glyphs + Dynamic Island) with light/dark auto-detect on refresh
- Status inpainting relative to the app header background (works on dark UIs and colored headers such as orange)
- Scrub residual Android ghosts in chrome zones before pasting the iOS overlay
- Home indicator polarity adapts at runtime: light on dark bottoms, dark on light bottoms



### 1.0.0

- Initial skill: cover resize to 1242×2688, targeted status inpainting, iOS overlays



## Requirements

- Python 3
- [Pillow](https://pypi.org/project/Pillow/): `pip3 install Pillow`



## Installation



### From Git

Clone this repository into your AI agent’s skills directory (for example Cursor, Claude, or another agent that loads skills from disk), then create the CLI wrapper (see below). The examples below use Cursor paths; for other agents, substitute the correct skills directory for your setup.

Example:

```bash
git clone https://github.com/xabaras/android-to-ios-screenshots.git \
  ~/.cursor/skills/android-to-ios-screenshots
```



### CLI Wrapper

The package lives at:

```
~/.cursor/skills/android-to-ios-screenshots/
├── README.md          ← this file
├── SKILL.md           ← Cursor agent instructions
├── scripts/
│   └── convert_android_to_ios_screenshots.py
└── assets/
    ├── ios-status-bar-overlay.png
    └── ios-home-indicator-overlay.png
```

Create the CLI wrapper:

```bash
cat > ~/.local/bin/android-to-ios-screenshots << 'EOF'
#!/bin/sh
exec python3 "$HOME/.cursor/skills/android-to-ios-screenshots/scripts/convert_android_to_ios_screenshots.py" "$@"
EOF
chmod +x ~/.local/bin/android-to-ios-screenshots
```



## Usage

This skill is meant to be used mainly through your AI agent: ask it to convert Android screenshots for the App Store (provide the input and output folders) and it will do the job using the bundled converter.
Your AI agent will load [SKILL.md](SKILL.md) when asked to working on App Store screenshots, the skill will tell the agent to run the command line tool, w/o reimplementing the pipeline.

### Command-line tool

You can also call the converter yourself from the terminal:

```bash
android-to-ios-screenshots \
  --input "/path/to/android/screenshots" \
  --output "/path/to/ios/screenshots" \
  --prefix iphone_
```

Or without the wrapper:

```bash
python3 ~/.cursor/skills/android-to-ios-screenshots/scripts/convert_android_to_ios_screenshots.py \
  --input "..." --output "..." --prefix iphone_
```

Converts every `.png` in `--input` and writes prefixed files to `--output` (default prefix: `iphone_`).

#### Example

```bash
android-to-ios-screenshots \
  --input "./android-screenshots" \
  --output "./ios-screenshots" \
  --prefix iphone_
```



## Main options


| Flag                               | Default      | Description                                                   |
| ---------------------------------- | ------------ | ------------------------------------------------------------- |
| `--input`                          | *(required)* | Folder with source Android PNGs                               |
| `--output`                         | *(required)* | Output folder                                                 |
| `--prefix`                         | `iphone_`    | Output filename prefix                                        |
| `--width`                          | `1242`       | Target width                                                  |
| `--height`                         | `2688`       | Target height (6.5" display)                                  |
| `--status-bar-crop`                | `0`          | Pixels to crop from top (**keep 0** to preserve header decor) |
| `--nav-bar-crop`                   | `48`         | Pixels to crop from bottom (Android gesture bar)              |
| `--no-ios-status-bar`              | off          | Resize only, no status bar overlay                            |
| `--no-ios-home-indicator`          | off          | Skip iOS home indicator overlay                               |
| `--status-bar-ref`                 | —            | iOS simulator screenshot used to regenerate overlays          |
| `--refresh-status-bar-overlay`     | off          | Regenerate `assets/ios-status-bar-overlay.png`                |
| `--refresh-home-indicator-overlay` | off          | Regenerate `assets/ios-home-indicator-overlay.png`            |




### 6.7" format (optional)

```bash
android-to-ios-screenshots --input "..." --output "..." --width 1284 --height 2778
```



### Regenerating iOS overlays

Requires a native iOS Simulator screenshot (e.g. iPhone 16, portrait). Prefer a **dark** status bar reference when regenerating the status overlay for dark apps:

```bash
android-to-ios-screenshots \
  --status-bar-ref "/path/to/Simulator Screenshot - iPhone 16 - ....png" \
  --refresh-status-bar-overlay \
  --refresh-home-indicator-overlay \
  --input /tmp/dummy --output /tmp/dummy
```

(`--input` and `--output` are required by argparse; the input folder must contain at least one PNG.)

## Post-conversion visual checklist

For each output PNG:

- [ ] Exact dimensions (1242×2688 or requested size)
- [ ] No Android icons under transparent status bar areas (left, right, beside Dynamic Island)
- [ ] No flat sage rectangles at top or bottom
- [ ] Status chrome is white on dark or colored headers (not dark glyphs / color bands)
- [ ] iOS home indicator visible at the bottom — light on dark UIs, dark on light UIs
- [ ] App UI content not cropped at the sides



## How the script works



### Pipeline

```
Source Android PNG
  → remove status bar icons (source, top ~96 px)
  → remove gesture bar line (source, bottom)
  → crop nav bar (--nav-bar-crop, default 48 px)
  → “cover” resize to 1242×2688 (top-aligned, horizontal crop if needed)
  → remove status bar icons (scaled image, top ~155 px; relative to app header bg)
  → ghost scrub under transparent overlay
  → polish chrome zones (light decor only; skipped on dark/saturated headers)
  → Dynamic Island flank cleanup
  → hard scrub chrome zones to solid app status bg
  → paste iOS status bar overlay
  → paste iOS home indicator (light on dark bottoms, dark on light)
  → automatic verification + save PNG
```



### Resize

The script uses **cover + crop** (not letterbox): scales to fill 1242×2688, keeps the top edge aligned, and center-crops horizontally. Avoids side bars and keeps the status bar area consistent.

### Android icon removal (targeted inpainting)

It does **not** replace entire bands with a flat median color (that produced visible sage rectangles). Instead:

1. **Samples** the solid app status/header background from the top corners.
2. **Detects** Android icon pixels as deviations from that background (works for dark UIs and colored headers, not only light decor).
3. **Replaces** each icon pixel with same-row neighbors matching the app background (or the background color itself).

Zones cleaned more aggressively (“chrome zones”):


| Zone                  | Position (1242 px)      | Typical content             |
| --------------------- | ----------------------- | --------------------------- |
| Left                  | x < 300                 | Time, Android notifications |
| Right                 | x ≥ 902                 | Battery, signal icons       |
| Dynamic Island flanks | x ≈ 306–426 and 816–936 | Residue beside the pill     |




### iOS overlays

Two transparent PNGs in `assets/`:

- **Status bar** (155 px): Dynamic Island, time, Wi‑Fi, battery — transparent background so app content shows through (white chrome for dark apps)
- **Home indicator** (42 px): centered line at the bottom; polarity is adapted at runtime for dark vs light bottoms

Generated from an iOS Simulator screenshot; normal runs reuse them (home indicator may be recolored per frame).

### What to avoid

- `--status-bar-crop` **> 0** — crops decorative circles under the status bar
- **Full-band flatten** — produces rectangular sage patches (replaced by targeted inpainting)
- **Copying the script into app repos** — keep it in this skill; use the CLI from app projects

## License / notes

MIT License; iOS overlays are derived from simulator screenshots. Always visually review every PNG before uploading to App Store Connect.