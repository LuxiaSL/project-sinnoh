#!/usr/bin/env python3
"""Test the enhanced collision grid with NPCs, warps, and dynamic legend."""

from __future__ import annotations
import os, sys
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "dummy"
sys.path.insert(0, str(Path(__file__).parent.parent))

from desmume.emulator import DeSmuME
from src.harness.collision import CollisionReader


def test(emu: DeSmuME, path: str, label: str) -> None:
    if not Path(path).exists():
        return

    print(f"\n{'='*70}")
    print(f"  {label} — {path}")
    print(f"{'='*70}")

    emu.savestate.load_file(path)
    for _ in range(30):
        emu.cycle(with_joystick=False)

    # Player position
    general = emu.memory.unsigned.read_long(0x02101D40) + 0x14
    rt_x = emu.memory.unsigned[0x021C5CE6]
    rt_y = emu.memory.unsigned[0x021C5CEE]
    save_x = emu.memory.unsigned.read_short(general + 0x1288)
    save_y = emu.memory.unsigned.read_short(general + 0x128C)
    map_id = emu.memory.unsigned.read_short(general + 0x1280)

    x = rt_x if not (rt_x == 0 and rt_y in (0, 254)) else save_x
    y = rt_y if not (rt_x == 0 and rt_y in (0, 254)) else save_y

    print(f"  Map {map_id}, Position ({x}, {y})")

    reader = CollisionReader(emu)
    if not reader.find_field_system():
        print("  FieldSystem not found!")
        return

    # Show NPCs
    npcs = reader.read_npcs()
    print(f"  NPCs: {len(npcs)}")
    for npc in npcs:
        d = {0: "N", 1: "S", 2: "W", 3: "E"}.get(npc.facing, "?")
        print(f"    id={npc.local_id} pos=({npc.x},{npc.z}) facing={d} gfx={npc.graphics_id}")

    # Show warps
    warps = reader.read_warps()
    print(f"  Warps: {len(warps)}")
    for w in warps:
        print(f"    ({w.x},{w.z}) → {w.dest_name} (map {w.dest_map_id})")

    # Player facing
    facing = reader.read_player_facing()
    print(f"  Player facing: {facing} = {['N','S','W','E'][facing] if 0<=facing<=3 else '?'}")

    # The main event: formatted grid
    grid = reader.format_grid(x, y, radius=5)
    if grid:
        print(f"\n--- SPATIAL GRID --- [{label}]  You: ({x},{y})")
        print(grid)
    else:
        print("  Grid unavailable!")


def main():
    emu = DeSmuME()
    emu.open("roms/Pokemon - Platinum Version (USA).nds")

    test(emu, "platinum_save/emulator.dst", "First Floor (Map 417)")
    test(emu, "tests/output/coord_search/walking.dst", "Bedroom (Map 415)")


if __name__ == "__main__":
    main()
