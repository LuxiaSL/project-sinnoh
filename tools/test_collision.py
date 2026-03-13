#!/usr/bin/env python3
"""Quick test of the CollisionReader module."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "dummy"

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from desmume.emulator import DeSmuME  # noqa: E402
from src.harness.collision import CollisionReader  # noqa: E402


def test_savestate(emu: DeSmuME, path: str, expected_map: int) -> None:
    print(f"\n{'='*60}")
    print(f"Testing: {path}")
    print(f"{'='*60}")

    emu.savestate.load_file(path)
    for _ in range(10):
        emu.cycle(with_joystick=False)

    # Read player position
    general = emu.memory.unsigned.read_long(0x02101D40) + 0x14
    map_id = emu.memory.unsigned.read_short(general + 0x1280)
    rt_x = emu.memory.unsigned[0x021C5CE6]
    rt_y = emu.memory.unsigned[0x021C5CEE]

    # Use save block coords if RT coords look bad
    if rt_x == 0 and rt_y in (0, 254):
        x = emu.memory.unsigned.read_short(general + 0x1288)
        y = emu.memory.unsigned.read_short(general + 0x128C)
        print(f"  Using save block coords: ({x}, {y})")
    else:
        x, y = rt_x, rt_y
        print(f"  Using RT coords: ({x}, {y})")

    print(f"  Map ID: {map_id} (expected {expected_map})")

    # Test collision reader
    reader = CollisionReader(emu)
    found = reader.find_field_system()
    print(f"  FieldSystem found: {found}")
    print(f"  Reader: {reader}")

    if not found:
        print("  FAILED: Could not find FieldSystem")
        return

    # Read player grid
    grid = reader.read_player_grid(x, y)
    if not grid:
        print("  FAILED: Could not read player grid")
        return

    local_x = x % 32
    local_y = y % 32
    player_tile = grid.get(local_x, local_y)
    print(f"  Player tile ({local_x}, {local_y}): walkable={player_tile.walkable}, behavior={player_tile.behavior:#04x}")
    print(f"  Grid stats: {grid.walkable_count} walkable, {grid.wall_count} walls")

    # Format spatial grid
    formatted = reader.format_grid(x, y, radius=5)
    if formatted:
        print(f"\n{formatted}")

    # Verify player tile is walkable
    assert player_tile.walkable, f"Player tile should be walkable! Got {player_tile.raw:#06x}"
    print("\n  ✓ Player tile is walkable")

    # Check for warps
    warp_count = 0
    for ty in range(32):
        for tx in range(32):
            t = grid.get(tx, ty)
            if t.is_warp:
                warp_count += 1
    print(f"  ✓ Found {warp_count} warp tile(s)")


def main() -> None:
    emu = DeSmuME()
    emu.open("roms/Pokemon - Platinum Version (USA).nds")

    # Test with live savestate (player on first floor, Map 417)
    live = "platinum_save/emulator.dst"
    if Path(live).exists():
        test_savestate(emu, live, expected_map=417)

    # Test with walking savestate (player in bedroom, Map 415)
    walking = "tests/output/coord_search/walking.dst"
    if Path(walking).exists():
        test_savestate(emu, walking, expected_map=415)

    print("\n\nAll tests passed!")


if __name__ == "__main__":
    main()
