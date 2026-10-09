#!/usr/bin/env python3
"""Convert Android app screenshots to iPhone App Store dimensions."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

__version__ = "1.2.0"

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATUS_OVERLAY = SKILL_ROOT / "assets" / "ios-status-bar-overlay.png"
DEFAULT_HOME_OVERLAY = SKILL_ROOT / "assets" / "ios-home-indicator-overlay.png"

REF_BG_COLOR = (255, 253, 247)
STATUS_BAR_HEIGHT = 155
HOME_INDICATOR_HEIGHT = 42
REF_BG_TOLERANCE = 42
SOURCE_STATUS_HEIGHT = 96


def _luminance(r: int, g: int, b: int) -> float:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _saturation(r: int, g: int, b: int) -> int:
    return max(r, g, b) - min(r, g, b)


def _avg_colors(colors: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    n = len(colors)
    return (
        sum(c[0] for c in colors) // n,
        sum(c[1] for c in colors) // n,
        sum(c[2] for c in colors) // n,
        sum(c[3] for c in colors) // n,
    )


def _dynamic_island_bounds(width: int) -> tuple[int, int]:
    """Island span derived from the 1242px reference overlay (x 426-815)."""
    scale = width / 1242
    return round(426 * scale), round(815 * scale)


def _is_island_flank_zone(x: int, width: int) -> bool:
    island_min, island_max = _dynamic_island_bounds(width)
    margin = round(120 * width / 1242)
    return island_min - margin <= x < island_min or island_max < x <= island_max + margin


def _chrome_side_margins(width: int) -> tuple[int, int]:
    """Left/right status-icon bands scaled from the 1242px reference overlay."""
    scale = width / 1242
    return round(300 * scale), round(340 * scale)


def _is_status_chrome_zone(x: int, width: int) -> bool:
    left, right = _chrome_side_margins(width)
    return x < left or x >= width - right or _is_island_flank_zone(x, width)


def _color_dist(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def _estimate_status_bar_bg(px, width: int, bar_height: int) -> tuple[int, int, int]:
    """Sample solid app chrome from status-bar corners (avoids icon-row contamination)."""
    samples: list[tuple[int, int, int]] = []
    y_end = min(24, bar_height)
    for y in range(y_end):
        for x in range(min(56, width)):
            samples.append(px[x, y][:3])
        for x in range(max(0, width - 56), width):
            samples.append(px[x, y][:3])
    if not samples:
        r, g, b, _ = px[0, 0]
        return (r, g, b)
    samples.sort(key=lambda c: _luminance(*c))
    return samples[len(samples) // 2]


def _estimate_status_row_bg(px, y: int, width: int) -> tuple[int, int, int]:
    """Compatibility helper — prefer corner-based bar bg when possible via caller."""
    island_min, island_max = _dynamic_island_bounds(width)
    left, right = _chrome_side_margins(width)
    samples: list[tuple[int, int, int]] = []
    for x in range(left, max(left + 1, width - right)):
        if island_min - 8 <= x <= island_max + 8:
            continue
        r, g, b, _ = px[x, y]
        samples.append((r, g, b))
    if not samples:
        x = max(0, island_min - 40)
        r, g, b, _ = px[x, y]
        return (r, g, b)
    samples.sort(key=lambda c: _luminance(*c))
    return samples[len(samples) // 2]


def _is_android_status_artifact(
    r: int,
    g: int,
    b: int,
    x: int,
    width: int,
    row_bg: tuple[int, int, int] | None = None,
) -> bool:
    """Detect Android status icons relative to the row's app background when known."""
    lum = _luminance(r, g, b)
    sat = _saturation(r, g, b)

    if row_bg is not None:
        bg_lum = _luminance(*row_bg)
        bg_sat = _saturation(*row_bg)
        # Preserve solid app chrome (dark bars, orange headers, etc.).
        if _color_dist((r, g, b), row_bg) < 38:
            return False
        if bg_sat >= 45:
            # Brand-colored header (e.g. orange): Android icons are white/light/green, not the brand color.
            return _color_dist((r, g, b), row_bg) > 28
        if bg_lum < 140:
            # Dark UI: Android icons/ghosts are lighter OR slightly darker than the flat bg.
            return abs(lum - bg_lum) > 12 or (sat >= 30 and _color_dist((r, g, b), row_bg) > 30)
        # Light UI: dark glyphs, OR brighter white ghosts (common when Android used light chrome).
        if lum < bg_lum - 22:
            return True
        if lum > bg_lum + 10 and sat < 45:
            return True
        if sat >= 38 and lum < 210 and _color_dist((r, g, b), row_bg) > 40:
            return True
        return False

    # Legacy absolute heuristics (light-decor screenshots).
    if lum < 115:
        return True
    if lum < 155 and sat < 28:
        return True
    if not _is_status_chrome_zone(x, width):
        if _is_island_flank_zone(x, width):
            if lum < 210 and sat < 42:
                return True
            if sat >= 38 and lum < 220:
                return True
        return lum < 168 and sat < 36
    if lum < 190 and sat < 38:
        return True
    if sat >= 38 and lum < 210:
        return True
    if g > r + 10 and g > b + 6 and lum < 200:
        return True
    return False


def _is_android_icon_pixel(r: int, g: int, b: int, *, aggressive: bool = False) -> bool:
    del aggressive
    lum = _luminance(r, g, b)
    sat = _saturation(r, g, b)
    if lum < 115:
        return True
    if lum < 155 and sat < 28:
        return True
    if lum < 185 and sat < 35:
        return True
    return False


def _is_decor_pixel(r: int, g: int, b: int, *, strict: bool = False) -> bool:
    lum = _luminance(r, g, b)
    sat = _saturation(r, g, b)
    if strict:
        return lum >= 185 and sat < 50
    return lum >= 150 or (lum >= 90 and sat >= 25)


def _is_fill_neighbor(
    r: int,
    g: int,
    b: int,
    row_bg: tuple[int, int, int],
) -> bool:
    """Accept neighbors that match the app status-row background (light or dark)."""
    if _color_dist((r, g, b), row_bg) < 42:
        return True
    bg_lum = _luminance(*row_bg)
    lum = _luminance(r, g, b)
    sat = _saturation(r, g, b)
    if bg_lum < 140:
        return abs(lum - bg_lum) < 28 and sat < max(35, _saturation(*row_bg) + 15)
    return _is_decor_pixel(r, g, b, strict=True)


def _inpaint_icon_pixels(
    image: Image.Image,
    y_start: int,
    y_end: int,
    passes: int = 5,
    search_radius: int = 24,
    aggressive_zones: bool = False,
) -> Image.Image:
    """Remove Android status glyphs via horizontal same-row inpainting, preserving app bg."""
    del aggressive_zones
    result = image.copy()
    px = result.load()
    w, h = result.size
    y_end = min(y_end, h)
    bar_bg = _estimate_status_bar_bg(px, w, max(1, y_end - y_start))

    for _ in range(passes):
        updates: list[tuple[int, int, tuple[int, int, int, int]]] = []
        for y in range(y_start, y_end):
            for x in range(w):
                r, g, b, a = px[x, y]
                if not _is_android_status_artifact(r, g, b, x, w, row_bg=bar_bg):
                    continue
                in_chrome = _is_status_chrome_zone(x, w)
                _, right = _chrome_side_margins(w)
                radius = search_radius + (16 if in_chrome and x >= w - right else 0)
                neighbors: list[tuple[int, int, int, int]] = []
                for dx in range(-radius, radius + 1):
                    if dx == 0:
                        continue
                    nx = x + dx
                    if 0 <= nx < w:
                        nr, ng, nb, na = px[nx, y]
                        if _is_fill_neighbor(nr, ng, nb, bar_bg):
                            neighbors.append((nr, ng, nb, na))
                if neighbors:
                    updates.append((x, y, _avg_colors(neighbors)))
                else:
                    updates.append((x, y, (*bar_bg, a)))
        for x, y, color in updates:
            px[x, y] = color

    return result


def remove_status_bar_ghosts(
    image: Image.Image,
    bar_height: int,
    status_overlay: Image.Image,
) -> Image.Image:
    """Final pass: scrub Android residue under transparent overlay areas toward app bg."""
    result = image.copy()
    px = result.load()
    sop = status_overlay.load()
    w, h = result.size
    zone_end = min(bar_height, h, status_overlay.height)
    bar_bg = _estimate_status_bar_bg(px, w, zone_end)

    for _ in range(6):
        updates: list[tuple[int, int, tuple[int, int, int, int]]] = []
        for y in range(zone_end):
            for x in range(w):
                if sop[x, y][3] > 0:
                    continue
                r, g, b, a = px[x, y]
                if not _is_android_status_artifact(r, g, b, x, w, row_bg=bar_bg):
                    continue
                in_chrome = _is_status_chrome_zone(x, w)
                _, right = _chrome_side_margins(w)
                radius = 48 if in_chrome and x >= w - right else 36
                neighbors: list[tuple[int, int, int, int]] = []
                for dx in range(-radius, radius + 1):
                    if dx == 0:
                        continue
                    nx = x + dx
                    if 0 <= nx < w:
                        nr, ng, nb, na = px[nx, y]
                        if _is_fill_neighbor(nr, ng, nb, bar_bg):
                            neighbors.append((nr, ng, nb, na))
                if neighbors:
                    updates.append((x, y, _avg_colors(neighbors)))
                else:
                    updates.append((x, y, (*bar_bg, a)))
        for x, y, color in updates:
            px[x, y] = color

    return result


def _bright_samples_on_row(px, y: int, x: int, w: int, radius: int) -> list[tuple[int, int, int, int]]:
    samples: list[tuple[int, int, int, int]] = []
    for dx in range(-radius, radius + 1):
        if dx == 0:
            continue
        nx = x + dx
        if 0 <= nx < w:
            nr, ng, nb, na = px[nx, y]
            if _luminance(nr, ng, nb) >= 198 and _saturation(nr, ng, nb) < 58:
                samples.append((nr, ng, nb, na))
    return samples


def polish_status_chrome(
    image: Image.Image,
    bar_height: int,
    status_overlay: Image.Image,
) -> Image.Image:
    """Lift faint Android outlines on light decor only (skip dark / saturated headers)."""
    result = image.copy()
    px = result.load()
    sop = status_overlay.load()
    w, h = result.size
    zone_end = min(bar_height, h, status_overlay.height)
    bar_bg = _estimate_status_bar_bg(px, w, zone_end)
    bg_lum = _luminance(*bar_bg)
    bg_sat = _saturation(*bar_bg)
    if bg_lum < 160 or bg_sat >= 50:
        return result

    for pass_idx in range(4):
        updates: list[tuple[int, int, tuple[int, int, int, int]]] = []
        for y in range(zone_end):
            for x in range(w):
                if sop[x, y][3] > 0:
                    continue
                if not _is_status_chrome_zone(x, w):
                    continue
                _, right = _chrome_side_margins(w)
                on_right = x >= w - right
                on_island_flank = _is_island_flank_zone(x, w)
                if on_right or on_island_flank:
                    lum_delta = 3.0
                    if pass_idx >= 2:
                        lum_delta = 2.0
                    radius = 44
                else:
                    lum_delta = 6.5
                    radius = 30
                r, g, b, a = px[x, y]
                lum = _luminance(r, g, b)
                bright_neighbors = _bright_samples_on_row(px, y, x, w, radius)
                if len(bright_neighbors) < 3:
                    continue
                ref_lum = sum(_luminance(*c[:3]) for c in bright_neighbors) / len(bright_neighbors)
                if ref_lum - lum > lum_delta:
                    updates.append((x, y, _avg_colors(bright_neighbors)))
        for x, y, color in updates:
            px[x, y] = color

    return result


def polish_island_flanks(
    image: Image.Image,
    bar_height: int,
    status_overlay: Image.Image,
) -> Image.Image:
    """Extra cleanup beside the Dynamic Island where Android icons often remain visible."""
    result = image.copy()
    px = result.load()
    sop = status_overlay.load()
    w, h = result.size
    zone_end = min(bar_height, h, status_overlay.height)
    bar_bg = _estimate_status_bar_bg(px, w, zone_end)
    dark_or_brand = _luminance(*bar_bg) < 160 or _saturation(*bar_bg) >= 50

    for _ in range(4):
        updates: list[tuple[int, int, tuple[int, int, int, int]]] = []
        for y in range(zone_end):
            for x in range(w):
                if sop[x, y][3] > 0 or not _is_island_flank_zone(x, w):
                    continue
                r, g, b, a = px[x, y]
                if dark_or_brand:
                    if _is_android_status_artifact(r, g, b, x, w, row_bg=bar_bg):
                        updates.append((x, y, (*bar_bg, a)))
                    continue
                lum = _luminance(r, g, b)
                bright_neighbors: list[tuple[int, int, int, int]] = []
                for dx in range(-56, 57):
                    if dx == 0:
                        continue
                    nx = x + dx
                    if 0 <= nx < w:
                        nr, ng, nb, na = px[nx, y]
                        nl = _luminance(nr, ng, nb)
                        ns = _saturation(nr, ng, nb)
                        if nl >= 192 and ns < 60:
                            bright_neighbors.append((nr, ng, nb, na))
                if len(bright_neighbors) < 2:
                    continue
                ref_lum = sum(_luminance(*c[:3]) for c in bright_neighbors) / len(bright_neighbors)
                if ref_lum - lum > 1.2:
                    updates.append((x, y, _avg_colors(bright_neighbors)))
        for x, y, color in updates:
            px[x, y] = color

    return result

def scrub_status_chrome_to_bg(
    image: Image.Image,
    bar_height: int,
    status_overlay: Image.Image,
) -> Image.Image:
    """Hard-replace residual Android ghosts in chrome zones with solid app status bg."""
    result = image.copy()
    px = result.load()
    w, h = result.size
    zone_end = min(bar_height, h, status_overlay.height)
    bar_bg = _estimate_status_bar_bg(px, w, zone_end)
    bg_lum = _luminance(*bar_bg)
    # Tighter on flat dark/brand headers; looser on light textured decor.
    tol = 10 if (bg_lum < 160 or _saturation(*bar_bg) >= 45) else 18

    for y in range(zone_end):
        for x in range(w):
            if not _is_status_chrome_zone(x, w):
                continue
            # Scrub under opaque overlay too so AA fringes don't reveal Android ghosts.
            r, g, b, a = px[x, y]
            lum = _luminance(r, g, b)
            sat = _saturation(r, g, b)
            # Also wipe near-white ghosts that sit close to a cream header bg.
            white_ghost = bg_lum >= 160 and lum > bg_lum + 6 and sat < 40
            dark_ghost = bg_lum >= 160 and lum < bg_lum - 12
            if _color_dist((r, g, b), bar_bg) > tol or white_ghost or dark_ghost:
                px[x, y] = (*bar_bg, a)

    return result


def remove_android_status_icons(image: Image.Image, bar_height: int = STATUS_BAR_HEIGHT) -> Image.Image:
    image = _inpaint_icon_pixels(image, 0, bar_height, passes=10, search_radius=36, aggressive_zones=True)
    return image


def remove_android_status_icons_source(image: Image.Image) -> Image.Image:
    return _inpaint_icon_pixels(
        image, 0, SOURCE_STATUS_HEIGHT, passes=8, search_radius=28, aggressive_zones=True
    )


def remove_android_nav_line_source(image: Image.Image) -> Image.Image:
    """Remove only the thin Android gesture line near the bottom of the source frame."""
    result = image.copy()
    px = result.load()
    w, h = result.size
    for y in range(max(0, h - 36), h):
        dark = sum(1 for x in range(w) if _luminance(*px[x, y][:3]) < 70)
        if dark < w * 0.12:
            continue
        for x in range(w):
            r, g, b, a = px[x, y]
            if _luminance(r, g, b) >= 70:
                continue
            if y > 0 and _is_decor_pixel(*px[x, y - 1][:3]):
                px[x, y] = px[x, y - 1]
    return result


def crop_bars(image: Image.Image, status_bar_crop: int, nav_bar_crop: int) -> Image.Image:
    width, height = image.size
    top = status_bar_crop
    bottom = height - nav_bar_crop if nav_bar_crop > 0 else height
    return image.crop((0, top, width, bottom))


def resize_with_cover(image: Image.Image, target_width: int, target_height: int) -> Image.Image:
    src_width, src_height = image.size
    scale = max(target_width / src_width, target_height / src_height)
    scaled_width = round(src_width * scale)
    scaled_height = round(src_height * scale)

    resized = image.resize((scaled_width, scaled_height), Image.Resampling.LANCZOS)
    left = (scaled_width - target_width) // 2
    top = 0
    return resized.crop((left, top, left + target_width, top + target_height))


def _sample_corner_bg(strip: Image.Image) -> tuple[int, int, int]:
    """Average RGB from top-left corner pixels (away from Dynamic Island / icons)."""
    pixels = strip.load()
    width, height = strip.size
    samples: list[tuple[int, int, int]] = []
    for y in range(min(24, height)):
        for x in range(min(48, width)):
            r, g, b, _ = pixels[x, y]
            samples.append((r, g, b))
    if not samples:
        return REF_BG_COLOR
    n = len(samples)
    return (
        sum(c[0] for c in samples) // n,
        sum(c[1] for c in samples) // n,
        sum(c[2] for c in samples) // n,
    )


def _extract_chrome_overlay(strip: Image.Image) -> Image.Image:
    """Punch background; keep status chrome. Auto-detects light vs dark reference."""
    pixels = strip.load()
    width, height = strip.size
    bg = _sample_corner_bg(strip)
    dark_ref = _luminance(*bg) < 140

    for y in range(height):
        for x in range(width):
            r, g, b, _ = pixels[x, y]
            luminance = _luminance(r, g, b)
            sat = _saturation(r, g, b)
            dist = ((r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2) ** 0.5

            if dark_ref:
                # Keep white glyphs + black island; punch colored/dark background.
                near_bg = dist < max(REF_BG_TOLERANCE, 36)
                is_island = luminance < 28 and sat < 20
                is_bright_chrome = luminance >= 175
                is_chrome_aa = luminance >= 110 and sat < 45 and not near_bg
                if is_island:
                    pixels[x, y] = (r, g, b, 255)
                elif is_bright_chrome or is_chrome_aa:
                    # Neutralize simulator color cast so glyphs stay white on any app bg.
                    v = max(r, g, b)
                    pixels[x, y] = (v, v, v, 255)
                else:
                    pixels[x, y] = (0, 0, 0, 0)
            else:
                # Keep dark glyphs + island; punch cream/bg and bright fills.
                cream_dist = (
                    (r - REF_BG_COLOR[0]) ** 2
                    + (g - REF_BG_COLOR[1]) ** 2
                    + (b - REF_BG_COLOR[2]) ** 2
                ) ** 0.5
                if cream_dist < REF_BG_TOLERANCE or dist < REF_BG_TOLERANCE or luminance > 200:
                    pixels[x, y] = (0, 0, 0, 0)
                else:
                    pixels[x, y] = (r, g, b, 255)

    return strip


def extract_status_bar_overlay(reference_path: Path) -> Image.Image:
    image = Image.open(reference_path).convert("RGBA")
    strip = image.crop((0, 0, image.width, STATUS_BAR_HEIGHT))
    return _extract_chrome_overlay(strip)


def extract_home_indicator_overlay(reference_path: Path) -> Image.Image:
    image = Image.open(reference_path).convert("RGBA")
    strip = image.crop((0, image.height - HOME_INDICATOR_HEIGHT, image.width, image.height))
    return _extract_chrome_overlay(strip)


def _load_chrome_overlay(
    overlay_path: Path,
    reference_path: Path | None,
    target_width: int,
    extract_fn,
    label: str,
) -> Image.Image:
    if overlay_path.exists():
        overlay = Image.open(overlay_path).convert("RGBA")
    elif reference_path and reference_path.exists():
        overlay = extract_fn(reference_path)
        overlay_path.parent.mkdir(parents=True, exist_ok=True)
        overlay.save(overlay_path)
    else:
        raise FileNotFoundError(
            f"{label} overlay not found at {overlay_path} and no reference at {reference_path}"
        )

    if overlay.width != target_width:
        target_height = round(overlay.height * (target_width / overlay.width))
        overlay = overlay.resize((target_width, target_height), Image.Resampling.LANCZOS)

    return overlay


def load_status_bar_overlay(
    overlay_path: Path,
    reference_path: Path | None,
    target_width: int,
) -> Image.Image:
    return _load_chrome_overlay(
        overlay_path, reference_path, target_width, extract_status_bar_overlay, "Status bar"
    )


def load_home_indicator_overlay(
    overlay_path: Path,
    reference_path: Path | None,
    target_width: int,
) -> Image.Image:
    return _load_chrome_overlay(
        overlay_path, reference_path, target_width, extract_home_indicator_overlay, "Home indicator"
    )


def verify_output(
    image: Image.Image,
    status_bar_overlay: Image.Image | None,
    home_indicator_overlay: Image.Image | None,
) -> None:
    px = image.load()
    w, h = image.size

    if status_bar_overlay is not None:
        sop = status_bar_overlay.load()
        sh = status_bar_overlay.height
        ghosts = 0
        bar_bg = _estimate_status_bar_bg(px, w, min(sh, h))
        for y in range(min(sh, h)):
            for x in range(w):
                if sop[x, y][3] == 0 and _is_status_chrome_zone(x, w):
                    if _is_android_status_artifact(*px[x, y][:3], x, w, row_bg=bar_bg):
                        ghosts += 1
        if ghosts > 5:
            print(f"  warning: {ghosts} Android-like pixels under transparent status bar")

    if home_indicator_overlay is not None:
        hh = home_indicator_overlay.height
        bottom_start = max(0, h - hh)
        for y in range(bottom_start, h):
            row_dark = sum(1 for x in range(w) if _luminance(*px[x, y][:3]) < 75)
            if row_dark > w * 0.5:
                print(f"  warning: full-width dark row at y={y} ({row_dark}/{w} pixels)")

        hop = home_indicator_overlay.load()
        # Sample bottom corners to decide expected indicator polarity.
        corner: list[tuple[int, int, int]] = []
        for y in range(bottom_start, h):
            for x in range(min(40, w)):
                corner.append(px[x, y][:3])
            for x in range(max(0, w - 40), w):
                corner.append(px[x, y][:3])
        bottom_dark = bool(corner) and (sum(_luminance(*c) for c in corner) / len(corner)) < 140
        center_hits = 0
        for y in range(hh):
            out_y = bottom_start + y
            for x in range(w // 2 - 200, w // 2 + 200):
                if not (0 <= x < w) or hop[x, y][3] <= 200:
                    continue
                lum = _luminance(*px[x, out_y][:3])
                if bottom_dark:
                    if lum > 180:
                        center_hits += 1
                elif lum < 100:
                    center_hits += 1
        if center_hits < 100:
            polarity = "light" if bottom_dark else "dark"
            print(f"  warning: home indicator may be missing ({center_hits} {polarity} center pixels)")


def _adapt_home_indicator_overlay(
    overlay: Image.Image,
    framed: Image.Image,
) -> Image.Image:
    """Use a light home indicator on dark bottoms (match status-bar chrome polarity)."""
    w, h = framed.size
    hh = overlay.height
    y0 = max(0, h - hh)
    samples: list[tuple[int, int, int]] = []
    for y in range(y0, h):
        for x in range(min(80, w)):
            samples.append(framed.getpixel((x, y))[:3])
        for x in range(max(0, w - 80), w):
            samples.append(framed.getpixel((x, y))[:3])
    if not samples:
        return overlay
    bg_lum = sum(_luminance(*c) for c in samples) / len(samples)
    if bg_lum >= 140:
        return overlay

    adapted = overlay.copy()
    px = adapted.load()
    ow, oh = adapted.size
    for y in range(oh):
        for x in range(ow):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            # Invert dark light-mode chrome → light bar on dark UI (near status-bar white).
            inv = 255 - int(_luminance(r, g, b))
            inv = max(220, inv)
            px[x, y] = (inv, inv, inv, a)
    return adapted


def _status_region_samples(
    framed: Image.Image,
    bar_height: int,
    *,
    skip_chrome: bool = False,
) -> list[float]:
    """Luminance samples from the status band (island skipped; optional chrome skip)."""
    px = framed.load()
    w, h = framed.size
    zone = min(bar_height, h)
    samples: list[float] = []
    island_l, island_r = _dynamic_island_bounds(w)
    for y in range(zone):
        for x in range(w // 5, 4 * w // 5):
            if island_l - 8 <= x <= island_r + 8:
                continue
            if skip_chrome and _is_status_chrome_zone(x, w):
                continue
            samples.append(_luminance(*px[x, y][:3]))
    return samples


def _status_region_is_busy(framed: Image.Image, bar_height: int) -> bool:
    """True when the status band looks like photo/map content, not flat app chrome."""
    samples = _status_region_samples(framed, bar_height)
    if len(samples) < 80:
        return False
    mean = sum(samples) / len(samples)
    var = sum((s - mean) ** 2 for s in samples) / len(samples)
    # High threshold so flat UI + Android status icons are not treated as photo/map.
    return var > 900


def _status_content_luminance(framed: Image.Image, bar_height: int) -> float:
    samples = _status_region_samples(framed, bar_height, skip_chrome=True)
    if len(samples) < 40:
        samples = _status_region_samples(framed, bar_height)
    if not samples:
        px = framed.load()
        return _luminance(*_estimate_status_bar_bg(px, framed.size[0], bar_height))
    return sum(samples) / len(samples)


def _adapt_status_bar_overlay(
    overlay: Image.Image,
    framed: Image.Image,
    *,
    prefer_light_chrome: bool | None = None,
) -> Image.Image:
    """Use dark glyphs on light backgrounds; keep white glyphs on dark/busy headers."""
    w, h = framed.size
    bar_h = min(STATUS_BAR_HEIGHT, overlay.height, h)
    px = framed.load()
    bar_bg = _estimate_status_bar_bg(px, w, bar_h)
    bg_lum = _luminance(*bar_bg)
    if prefer_light_chrome is None:
        prefer_light_chrome = _status_region_is_busy(framed, bar_h) or bg_lum < 160

    # Dark / mid / photographic headers: keep the white chrome overlay as-is.
    if prefer_light_chrome:
        return overlay

    adapted = overlay.copy()
    op = adapted.load()
    ow, oh = adapted.size
    for y in range(oh):
        for x in range(ow):
            r, g, b, a = op[x, y]
            if a == 0:
                continue
            lum = _luminance(r, g, b)
            if lum < 40:
                # Dynamic Island stays black.
                op[x, y] = (0, 0, 0, a)
            else:
                # White / light glyphs → dark for light app chrome.
                inv = 255 - max(r, g, b)
                inv = min(inv, 45)
                op[x, y] = (inv, inv, inv, a)
    return adapted


def _clean_status_chrome_icons_keep_content(
    image: Image.Image,
    bar_height: int,
    *,
    prefer_light_chrome: bool,
) -> Image.Image:
    """Remove Android status icons only in left/right icon boxes.

    Center photo/map under the Dynamic Island is left untouched. Each icon pixel
    is replaced with the median color of the same row's center (icon-free) span so
    the header stays continuous horizontally — no vertical smear.
    """
    result = image.copy()
    px = result.load()
    w, h = result.size
    zone = min(bar_height, h)
    boxes = ((0, round(w * 0.30)), (round(w * 0.70), w))
    cx0, cx1 = round(w * 0.34), round(w * 0.66)
    island_l, island_r = _dynamic_island_bounds(w)

    def is_icon(r: int, g: int, b: int) -> bool:
        lum = _luminance(r, g, b)
        sat = _saturation(r, g, b)
        if prefer_light_chrome:
            # Dark photo: Android icons are white / light.
            if lum >= 185 and sat < 65:
                return True
            if g > r + 20 and g > b + 12 and lum > 100:
                return True
            return False
        # Light map: dark Android icons, plus any leftover bright ghosts.
        if lum <= 75 and sat < 45:
            return True
        if lum >= 215 and sat < 45:
            return True
        return False

    for y in range(zone):
        for x0, x1 in boxes:
            # Propagate real photo/map color inward from the content-facing edge.
            if x0 == 0:
                seed_x = min(x1 + 2, w - 1)
                scan = range(x1 - 1, x0 - 1, -1)
            else:
                seed_x = max(x0 - 3, 0)
                scan = range(x0, x1)
            sr, sg, sb, sa = px[seed_x, y]
            if is_icon(sr, sg, sb):
                # Rare: seed sits on an icon — use center row median.
                samples = [
                    px[x, y][:3]
                    for x in range(cx0, cx1)
                    if not (island_l - 4 <= x <= island_r + 4)
                    and not is_icon(*px[x, y][:3])
                ]
                if samples:
                    samples.sort(key=lambda c: _luminance(*c))
                    sr, sg, sb = samples[len(samples) // 2]
                else:
                    sr, sg, sb, sa = px[seed_x, min(zone + 4, h - 1)]
            good = (sr, sg, sb, sa)
            for x in scan:
                r, g, b, a = px[x, y]
                if is_icon(r, g, b):
                    px[x, y] = good
                else:
                    good = (r, g, b, a)
    return result


def convert_screenshot(
    source_path: Path,
    dest_path: Path,
    target_width: int,
    target_height: int,
    status_bar_crop: int,
    nav_bar_crop: int,
    status_bar_overlay: Image.Image | None,
    home_indicator_overlay: Image.Image | None,
) -> None:
    image = Image.open(source_path).convert("RGBA")
    source_busy = _status_region_is_busy(image, SOURCE_STATUS_HEIGHT)

    if status_bar_overlay is not None and not source_busy:
        # Flat chrome only — aggressive source inpaint flattens photo/map under the status bar.
        image = remove_android_status_icons_source(image)
    elif source_busy:
        # Photo/map: drop Android status so real content pixels sit under the iOS chrome.
        # (Inpainting icons on busy headers leaves ghosts / smears.)
        image = crop_bars(image, SOURCE_STATUS_HEIGHT, 0)

    image = remove_android_nav_line_source(image)
    cropped = crop_bars(image, status_bar_crop, nav_bar_crop)
    framed = resize_with_cover(cropped, target_width, target_height).convert("RGBA")

    if status_bar_overlay is not None:
        # Trust source detection — after extend, framed status variance can look "flat".
        busy_status = source_busy
        if not busy_status:
            framed = remove_android_status_icons(framed, bar_height=status_bar_overlay.height)
            framed = remove_status_bar_ghosts(framed, status_bar_overlay.height, status_bar_overlay)
            # Flat UI chrome: polish + hard scrub to solid header bg.
            framed = polish_status_chrome(framed, status_bar_overlay.height, status_bar_overlay)
            framed = polish_island_flanks(framed, status_bar_overlay.height, status_bar_overlay)
            framed = scrub_status_chrome_to_bg(framed, status_bar_overlay.height, status_bar_overlay)
            bar_bg = _estimate_status_bar_bg(framed.load(), framed.size[0], status_bar_overlay.height)
            prefer_light = _luminance(*bar_bg) < 160
            status = _adapt_status_bar_overlay(
                status_bar_overlay, framed, prefer_light_chrome=prefer_light
            )
        else:
            # Edge-to-edge photo/map: polarity from content under the extended header.
            prefer_light = _status_content_luminance(framed, status_bar_overlay.height) < 160
            status = _adapt_status_bar_overlay(
                status_bar_overlay, framed, prefer_light_chrome=prefer_light
            )
        framed.paste(status, (0, 0), status)

    if home_indicator_overlay is not None:
        home = _adapt_home_indicator_overlay(home_indicator_overlay, framed)
        framed.paste(
            home,
            (0, framed.height - home.height),
            home,
        )

    verify_output(framed, status_bar_overlay, home_indicator_overlay)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    framed.convert("RGB").save(dest_path, format="PNG", optimize=True)
    print(f"Wrote {dest_path} ({target_width}x{target_height})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prefix", default="iphone_")
    parser.add_argument(
        "--width",
        type=int,
        default=1206,
        help="Target width (default 1206: iPhone Dynamic Island medium / 1206×2622)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=2622,
        help="Target height (default 2622: App Store Connect Dynamic Island medium display)",
    )
    parser.add_argument(
        "--status-bar-crop",
        type=int,
        default=0,
        help="Optional pixels to remove from top (default 0 keeps decor under status bar)",
    )
    parser.add_argument(
        "--nav-bar-crop",
        type=int,
        default=48,
        help="Pixels to remove from bottom Android gesture bar (default 48)",
    )
    parser.add_argument(
        "--status-bar-ref",
        type=Path,
        default=None,
        help="iOS simulator screenshot used to regenerate overlays (--refresh-*). Not needed for normal runs.",
    )
    parser.add_argument("--status-bar-overlay", type=Path, default=DEFAULT_STATUS_OVERLAY)
    parser.add_argument("--home-indicator-overlay", type=Path, default=DEFAULT_HOME_OVERLAY)
    parser.add_argument("--no-ios-status-bar", action="store_true")
    parser.add_argument("--no-ios-home-indicator", action="store_true")
    parser.add_argument("--refresh-status-bar-overlay", action="store_true")
    parser.add_argument("--refresh-home-indicator-overlay", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    status_overlay: Image.Image | None = None
    home_overlay: Image.Image | None = None

    if not args.no_ios_status_bar:
        if args.refresh_status_bar_overlay:
            if not args.status_bar_ref or not args.status_bar_ref.exists():
                raise SystemExit("--status-bar-ref is required when using --refresh-status-bar-overlay")
            status_overlay = extract_status_bar_overlay(args.status_bar_ref)
            args.status_bar_overlay.parent.mkdir(parents=True, exist_ok=True)
            status_overlay.save(args.status_bar_overlay)
            print(f"Refreshed overlay {args.status_bar_overlay}")
        status_overlay = load_status_bar_overlay(args.status_bar_overlay, args.status_bar_ref, args.width)

    if not args.no_ios_home_indicator:
        if args.refresh_home_indicator_overlay:
            if not args.status_bar_ref or not args.status_bar_ref.exists():
                raise SystemExit("--status-bar-ref is required when using --refresh-home-indicator-overlay")
            home_overlay = extract_home_indicator_overlay(args.status_bar_ref)
            args.home_indicator_overlay.parent.mkdir(parents=True, exist_ok=True)
            home_overlay.save(args.home_indicator_overlay)
            print(f"Refreshed overlay {args.home_indicator_overlay}")
        home_overlay = load_home_indicator_overlay(args.home_indicator_overlay, args.status_bar_ref, args.width)

    files = sorted(args.input.glob("*.png"))
    if not files:
        raise SystemExit(f"No PNG files found in {args.input}")

    for source in files:
        dest = args.output / f"{args.prefix}{source.name}"
        convert_screenshot(
            source_path=source,
            dest_path=dest,
            target_width=args.width,
            target_height=args.height,
            status_bar_crop=args.status_bar_crop,
            nav_bar_crop=args.nav_bar_crop,
            status_bar_overlay=status_overlay,
            home_indicator_overlay=home_overlay,
        )


if __name__ == "__main__":
    main()
