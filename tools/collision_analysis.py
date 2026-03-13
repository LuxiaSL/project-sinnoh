#!/usr/bin/env python3
"""Visual analysis of collision grids — renders full 32x32 grids alongside screenshots.

For each savestate:
1. Captures the top screen screenshot (what the player sees)
2. Reads the full 32x32 collision grid from RAM
3. Saves both to /tmp for manual review

Usage:
    python tools/collision_analysis.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "dummy"

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from desmume.emulator import DeSmuME  # noqa: E402
from src.harness.collision import (  # noqa: E402
    COLLISION_BIT,
    BEHAVIOR_MASK,
    MAP_TILES,
    CollisionReader,
    TileBehavior,
    WARP_BEHAVIORS,
    WATER_BEHAVIORS,
    GRASS_BEHAVIORS,
    LEDGE_BEHAVIORS,
)


# Color map for tile types
COLORS = {
    "wall": (60, 60, 60),        # dark gray
    "floor": (200, 200, 180),    # light tan
    "player": (255, 50, 50),     # red
    "warp": (255, 180, 0),       # orange
    "grass": (80, 180, 60),      # green
    "water": (60, 120, 220),     # blue
    "ledge": (180, 120, 60),     # brown
    "pc": (100, 200, 255),       # cyan
    "tv": (200, 100, 255),       # purple
    "table": (150, 130, 100),    # dark tan
    "bookshelf": (120, 80, 40),  # dark brown
    "ice": (180, 220, 255),      # light blue
    "sand": (220, 200, 140),     # sand
    "unknown": (255, 0, 255),    # magenta (shouldn't appear)
}


def tile_color(raw: int) -> tuple[int, int, int]:
    """Get color for a tile value."""
    collision = bool(raw & COLLISION_BIT)
    behavior = raw & BEHAVIOR_MASK

    if collision:
        return COLORS["wall"]
    if behavior in WARP_BEHAVIORS:
        return COLORS["warp"]
    if behavior in GRASS_BEHAVIORS:
        return COLORS["grass"]
    if behavior in WATER_BEHAVIORS:
        return COLORS["water"]
    if behavior in LEDGE_BEHAVIORS:
        return COLORS["ledge"]
    if behavior == TileBehavior.PC:
        return COLORS["pc"]
    if behavior == TileBehavior.TV:
        return COLORS["tv"]
    if behavior == TileBehavior.TABLE:
        return COLORS["table"]
    if behavior in (TileBehavior.BOOKSHELF, TileBehavior.BOOKSHELF_SM, TileBehavior.BOOKSHELF_2):
        return COLORS["bookshelf"]
    if behavior == TileBehavior.ICE:
        return COLORS["ice"]
    if behavior == TileBehavior.SAND:
        return COLORS["sand"]
    if behavior == TileBehavior.NONE:
        return COLORS["floor"]
    return COLORS["floor"]


def tile_label(raw: int) -> str:
    """Get 1-2 char label for a tile."""
    collision = bool(raw & COLLISION_BIT)
    behavior = raw & BEHAVIOR_MASK

    if collision:
        return "#"
    if behavior in WARP_BEHAVIORS:
        return "D"
    if behavior in GRASS_BEHAVIORS:
        return "G"
    if behavior in WATER_BEHAVIORS:
        return "~"
    if behavior in LEDGE_BEHAVIORS:
        return "J"
    if behavior == TileBehavior.PC:
        return "P"
    if behavior == TileBehavior.TV:
        return "T"
    if behavior == TileBehavior.TABLE:
        return "="
    if behavior in (TileBehavior.BOOKSHELF, TileBehavior.BOOKSHELF_SM, TileBehavior.BOOKSHELF_2):
        return "B"
    return "."


def render_grid_image(tiles: list[int], player_lx: int, player_ly: int, cell_size: int = 20) -> Image.Image:
    """Render a 32x32 collision grid as a color-coded image."""
    w = MAP_TILES * cell_size
    h = MAP_TILES * cell_size
    img = Image.new("RGB", (w + 40, h + 40), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Try to get a small font
    try:
        font = ImageFont.truetype("/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf", 11)
    except Exception:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 11)
        except Exception:
            font = ImageFont.load_default()

    ox, oy = 20, 20  # offset for labels

    # Draw axis labels
    for x in range(MAP_TILES):
        if x % 4 == 0:
            draw.text((ox + x * cell_size + 2, 2), str(x), fill=(0, 0, 0), font=font)
    for y in range(MAP_TILES):
        if y % 4 == 0:
            draw.text((0, oy + y * cell_size + 2), str(y), fill=(0, 0, 0), font=font)

    # Draw tiles
    for y in range(MAP_TILES):
        for x in range(MAP_TILES):
            raw = tiles[y * MAP_TILES + x]
            color = tile_color(raw)

            x0 = ox + x * cell_size
            y0 = oy + y * cell_size
            x1 = x0 + cell_size - 1
            y1 = y0 + cell_size - 1

            draw.rectangle([x0, y0, x1, y1], fill=color)

            # Player marker
            if x == player_lx and y == player_ly:
                draw.rectangle([x0, y0, x1, y1], fill=COLORS["player"])
                draw.text((x0 + 4, y0 + 2), "@", fill=(255, 255, 255), font=font)
            else:
                label = tile_label(raw)
                if label != "." and label != "#":
                    # Draw label for special tiles
                    text_color = (255, 255, 255) if color[0] < 128 else (0, 0, 0)
                    draw.text((x0 + 4, y0 + 2), label, fill=text_color, font=font)

    # Draw grid lines
    for x in range(MAP_TILES + 1):
        draw.line([(ox + x * cell_size, oy), (ox + x * cell_size, oy + h)], fill=(180, 180, 180))
    for y in range(MAP_TILES + 1):
        draw.line([(ox, oy + y * cell_size), (ox + w, oy + y * cell_size)], fill=(180, 180, 180))

    return img


def render_ascii_grid(tiles: list[int], player_lx: int, player_ly: int) -> str:
    """Full 32x32 ASCII grid."""
    lines: list[str] = []

    # Header
    lines.append("     " + "".join(f"{x:>3}" for x in range(MAP_TILES)))
    lines.append("")

    for y in range(MAP_TILES):
        row: list[str] = []
        for x in range(MAP_TILES):
            raw = tiles[y * MAP_TILES + x]
            if x == player_lx and y == player_ly:
                row.append(" @")
            else:
                collision = bool(raw & COLLISION_BIT)
                behavior = raw & BEHAVIOR_MASK
                if collision:
                    row.append(" #")
                elif behavior in WARP_BEHAVIORS:
                    row.append(" D")
                elif behavior in GRASS_BEHAVIORS:
                    row.append(" G")
                elif behavior in WATER_BEHAVIORS:
                    row.append(" ~")
                elif behavior in LEDGE_BEHAVIORS:
                    row.append(" J")
                elif behavior == TileBehavior.PC:
                    row.append(" P")
                elif behavior == TileBehavior.TV:
                    row.append(" T")
                elif behavior == TileBehavior.TABLE:
                    row.append(" =")
                elif behavior in (TileBehavior.BOOKSHELF, TileBehavior.BOOKSHELF_SM):
                    row.append(" B")
                else:
                    row.append(" .")
        lines.append(f" {y:>3} {''.join(row)}")

    return "\n".join(lines)


def capture_screenshot(emu: DeSmuME) -> Image.Image:
    """Capture top screen as PIL Image."""
    buf = emu.display_buffer_as_rgbx()
    arr = np.frombuffer(buf, dtype=np.uint8).reshape((384, 256, 4))
    # Top screen is first 192 rows, BGRX format
    top = arr[:192, :, :3][:, :, ::-1]  # BGRX → RGB
    return Image.fromarray(top)


def analyze_savestate(emu: DeSmuME, path: str, label: str, output_dir: Path) -> None:
    """Analyze one savestate — screenshot + collision grid."""
    print(f"\n{'='*70}")
    print(f"  {label}: {path}")
    print(f"{'='*70}")

    emu.savestate.load_file(path)
    for _ in range(30):
        emu.cycle(with_joystick=False)

    # Player info
    general = emu.memory.unsigned.read_long(0x02101D40) + 0x14
    map_id = emu.memory.unsigned.read_short(general + 0x1280)
    rt_x = emu.memory.unsigned[0x021C5CE6]
    rt_y = emu.memory.unsigned[0x021C5CEE]

    if rt_x == 0 and rt_y in (0, 254):
        x = emu.memory.unsigned.read_short(general + 0x1288)
        y = emu.memory.unsigned.read_short(general + 0x128C)
        coord_src = "save_block"
    else:
        x, y = rt_x, rt_y
        coord_src = "realtime"

    print(f"  Map ID: {map_id}")
    print(f"  Position: ({x}, {y}) [from {coord_src}]")
    print(f"  Local tile: ({x % 32}, {y % 32})")

    # Screenshot
    screenshot = capture_screenshot(emu)
    screenshot_path = output_dir / f"{label}_screenshot.png"
    screenshot.save(str(screenshot_path))
    print(f"  Screenshot saved: {screenshot_path}")

    # Also capture bottom screen
    buf = emu.display_buffer_as_rgbx()
    arr = np.frombuffer(buf, dtype=np.uint8).reshape((384, 256, 4))
    bottom = arr[192:, :, :3][:, :, ::-1]
    bottom_img = Image.fromarray(bottom)
    bottom_path = output_dir / f"{label}_bottom.png"
    bottom_img.save(str(bottom_path))

    # Collision data
    reader = CollisionReader(emu)
    if not reader.find_field_system():
        print("  ⚠ FieldSystem not found — no collision data")
        return

    grids = reader.read_loaded_maps()
    print(f"  Found {len(grids)} loaded map quadrants")

    for grid in grids:
        local_x = x % 32
        local_y = y % 32
        player_tile = grid.get(local_x, local_y)

        tag = "PLAYER_MAP" if player_tile.walkable else "other"
        print(f"\n  Quadrant {grid.quadrant} [{tag}]: {grid.walkable_count} walkable, {grid.wall_count} walls")

        # Behavior distribution
        behaviors: dict[int, int] = {}
        for t in grid.tiles:
            b = t & BEHAVIOR_MASK
            if not (t & COLLISION_BIT):  # only count walkable tile behaviors
                behaviors[b] = behaviors.get(b, 0) + 1

        if behaviors:
            sorted_b = sorted(behaviors.items(), key=lambda kv: -kv[1])
            parts = []
            for bval, cnt in sorted_b[:6]:
                try:
                    name = TileBehavior(bval).name.lower()
                except ValueError:
                    name = f"0x{bval:02x}"
                parts.append(f"{name}:{cnt}")
            print(f"  Walkable behaviors: {', '.join(parts)}")

        # ASCII grid
        ascii_grid = render_ascii_grid(grid.tiles, local_x if tag == "PLAYER_MAP" else -1, local_y if tag == "PLAYER_MAP" else -1)
        print(f"\n{ascii_grid}")

        # Color image
        grid_img = render_grid_image(
            grid.tiles,
            local_x if tag == "PLAYER_MAP" else -1,
            local_y if tag == "PLAYER_MAP" else -1,
        )
        grid_path = output_dir / f"{label}_q{grid.quadrant}_collision.png"
        grid_img.save(str(grid_path))
        print(f"\n  Grid image saved: {grid_path}")

        # Also save the cropped view (what Claude would see — 11x11 around player)
        if tag == "PLAYER_MAP":
            formatted = reader.format_grid(x, y, radius=5)
            if formatted:
                print(f"\n  === Claude's View (11×11) ===")
                print(formatted)


def main() -> None:
    output_dir = Path("/tmp/collision_analysis")
    output_dir.mkdir(exist_ok=True)
    print(f"Output directory: {output_dir}")

    emu = DeSmuME()
    emu.open("roms/Pokemon - Platinum Version (USA).nds")

    savestates = [
        ("platinum_save/emulator.dst", "live_run"),
        ("tests/output/coord_search/walking.dst", "bedroom"),
        ("tests/output/get_starter/progress_v3.dst", "starter_attempt"),
    ]

    for path, label in savestates:
        if Path(path).exists():
            analyze_savestate(emu, path, label, output_dir)
        else:
            print(f"\n  Skipped (not found): {path}")

    print(f"\n\n{'='*70}")
    print(f"  All outputs in: {output_dir}")
    print(f"  Open screenshots and grid images side-by-side for comparison.")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
