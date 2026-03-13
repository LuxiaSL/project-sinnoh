#!/usr/bin/env python3
"""Find FieldSystem* and collision data in Pokemon Platinum RAM.

Scans RAM to locate the FieldSystem struct, then follows pointer chains
to read the actual 32x32 tile collision grid.

Multiple strategies:
1. Pointer density scan: FieldSystem has ~22 consecutive pointer fields
2. Pattern match on terrain data blocks
3. Scan for SaveData-related pointers

Usage:
    python tools/find_field_system.py [savestate_path]

Default: platinum_save/emulator.dst (live run, field map active)
Fallback: tests/output/coord_search/walking.dst
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "dummy"

from desmume.emulator import DeSmuME  # noqa: E402


# === Constants from pret/pokeplatinum ===

# FieldSystem struct offsets (confirmed from field_system.h)
FS_PROCESS_MANAGER = 0x00   # FieldProcessManager*
FS_UNK_04 = 0x04            # FieldSystem_sub2*
FS_BG_CONFIG = 0x08         # BgConfig*
FS_SAVE_DATA = 0x0C         # SaveData*
FS_TASK = 0x10              # FieldTask*
FS_MAP_HEADER_DATA = 0x14   # MapHeaderData*
FS_BOTTOM_SCREEN = 0x18     # int
FS_LOCATION = 0x1C          # Location*
FS_UNK_20 = 0x20            # int
FS_CAMERA = 0x24            # Camera*
FS_LAND_DATA_MAN = 0x28     # LandDataManager*
FS_MAP_MATRIX = 0x2C        # MapMatrix*
FS_AREA_DATA_MAN = 0x30     # AreaDataManager*
FS_UNK_34 = 0x34            # ptr
FS_MAP_OBJ_MAN = 0x38       # MapObjectManager*
FS_PLAYER_AVATAR = 0x3C     # PlayerAvatar*
FS_FIELD_EFF_MAN = 0x40     # FieldEffectManager*
FS_AREA_MODEL_ATTRS = 0x44  # ModelAttributes*
FS_UNK_48 = 0x48            # ptr
FS_AREA_LIGHT_MAN = 0x4C    # AreaLightManager*
FS_MAP_PROP_ANIM_MAN = 0x50 # MapPropAnimationManager*
FS_MAP_PROP_ONESHOT = 0x54  # MapPropOneShotAnimationManager*
FS_TERRAIN_ATTRS = 0x58     # TerrainAttributes*
FS_TERRAIN_COLL_MAN = 0x5C  # TerrainCollisionManager*

# Offsets that MUST be valid heap pointers in FieldSystem
FS_POINTER_OFFSETS = [
    0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x1C,
    0x24, 0x28, 0x2C, 0x30, 0x38, 0x3C, 0x40,
    0x44, 0x4C, 0x50, 0x54,
]

# LandDataManager offsets
LDM_LOADED_MAPS = 0x90      # LoadedMap* loadedMaps[4] — confirmed offset

# Map constants
MAP_TILES_X = 32
MAP_TILES_Z = 32
TERRAIN_SIZE = MAP_TILES_X * MAP_TILES_Z  # 1024 tiles

# Terrain attribute masks
COLLISION_BIT = 0x8000  # bit 15
BEHAVIOR_MASK = 0xFF    # bits 0-7

# Known addresses
SAVE_BLOCK_PTR_ADDR = 0x02101D40
FIXED_X_ADDR = 0x021C5CE6       # Player X tile (byte)
FIXED_Y_ADDR = 0x021C5CEE       # Player Y tile (byte)
SAVE_BLOCK_PTR_OFFSET = 0x14

# Tile behavior names (subset)
TILE_BEHAVIORS: dict[int, str] = {
    0x00: "floor", 0x02: "tall_grass", 0x03: "very_tall_grass",
    0x08: "cave_floor", 0x0B: "old_chateau", 0x0C: "mountain",
    0x10: "water_river", 0x13: "waterfall", 0x15: "water_sea",
    0x16: "puddle", 0x17: "shallow_water",
    0x20: "ice", 0x21: "sand",
    0x30: "block_east", 0x31: "block_west", 0x32: "block_north", 0x33: "block_south",
    0x38: "jump_east", 0x39: "jump_west", 0x3A: "jump_north", 0x3B: "jump_south",
    0x40: "slide_east", 0x41: "slide_west", 0x42: "slide_north", 0x43: "slide_south",
    0x4B: "rock_climb_ns", 0x4C: "rock_climb_ew",
    0x5D: "warp_stairs_e", 0x5E: "warp_stairs_w",
    0x62: "warp_ent_e", 0x63: "warp_ent_w", 0x64: "warp_ent_n", 0x65: "warp_ent_s",
    0x67: "warp_panel", 0x69: "door",
    0x6C: "warp_east", 0x6D: "warp_west", 0x6E: "warp_north", 0x6F: "warp_south",
    0x80: "table", 0x83: "PC", 0x85: "town_map", 0x86: "TV",
    0xA0: "berry_patch", 0xA1: "snow_deep",
    0xE0: "bookshelf_sm", 0xE1: "bookshelf", 0xE4: "trash_can",
}


def read8(emu: DeSmuME, addr: int) -> int:
    return emu.memory.unsigned[addr]


def read16(emu: DeSmuME, addr: int) -> int:
    return emu.memory.unsigned.read_short(addr)


def read32(emu: DeSmuME, addr: int) -> int:
    return emu.memory.unsigned.read_long(addr)


def is_valid_ptr(val: int) -> bool:
    """Check if a value looks like a valid ARM9 main RAM pointer."""
    return 0x02000000 <= val < 0x03000000


def is_heap_ptr(val: int) -> bool:
    """Check if a value looks like a heap pointer (higher RAM region)."""
    return 0x02200000 <= val < 0x02800000


def get_player_info(emu: DeSmuME) -> dict:
    """Read player position and map info."""
    general = read32(emu, SAVE_BLOCK_PTR_ADDR) + SAVE_BLOCK_PTR_OFFSET
    map_id = read16(emu, general + 0x1280)
    save_x = read16(emu, general + 0x1288)
    save_y = read16(emu, general + 0x128C)
    rt_x = read8(emu, FIXED_X_ADDR)
    rt_y = read8(emu, FIXED_Y_ADDR)

    # Use RT coords if they look valid, otherwise save coords
    if rt_x == 0 and rt_y in (0, 254):
        # RT coords not initialized, use save block
        use_x, use_y = save_x, save_y
        coord_source = "save_block"
    else:
        use_x, use_y = rt_x, rt_y
        coord_source = "realtime"

    return {
        "general": general,
        "map_id": map_id,
        "save_x": save_x,
        "save_y": save_y,
        "rt_x": rt_x,
        "rt_y": rt_y,
        "x": use_x,
        "y": use_y,
        "local_x": use_x % MAP_TILES_X,
        "local_y": use_y % MAP_TILES_Z,
        "coord_source": coord_source,
        "save_data_ptr": read32(emu, SAVE_BLOCK_PTR_ADDR),
    }


def scan_for_field_system(emu: DeSmuME, save_data_value: int) -> list[tuple[int, int]]:
    """Find FieldSystem by structural fingerprinting.

    FieldSystem has:
    - Many pointer fields at specific offsets
    - int bottomScreen at +0x18 (small value 0-3, NOT a pointer)
    - int unk_20 at +0x20 (small value, NOT a pointer)
    - saveData at +0x0C should relate to known save block
    """
    candidates: list[tuple[int, int]] = []

    # FieldSystem is heap-allocated
    scan_start = 0x02200000
    scan_end = 0x02800000

    print(f"  Structural scan {scan_start:#010x} - {scan_end:#010x}...")

    for addr in range(scan_start, scan_end, 4):
        # CRITICAL DISCRIMINATOR: +0x18 (bottomScreen) must NOT be a pointer
        val_18 = read32(emu, addr + 0x18)
        if is_valid_ptr(val_18):
            continue

        # +0x18 should be a small int (0-5 range for screen ID)
        if val_18 > 10:
            continue

        # +0x20 (unk_20) must also NOT be a pointer
        val_20 = read32(emu, addr + 0x20)
        if is_valid_ptr(val_20):
            continue

        # +0x28 and +0x2C must be valid pointers
        val_28 = read32(emu, addr + FS_LAND_DATA_MAN)
        if not is_valid_ptr(val_28):
            continue
        val_2c = read32(emu, addr + FS_MAP_MATRIX)
        if not is_valid_ptr(val_2c):
            continue

        # +0x0C (saveData) must be a valid pointer
        val_0c = read32(emu, addr + FS_SAVE_DATA)
        if not is_valid_ptr(val_0c):
            continue

        # +0x58 (terrainAttributes) should be valid if field map is active
        val_58 = read32(emu, addr + FS_TERRAIN_ATTRS)

        # Count valid pointers at known offsets
        ptr_count = 0
        for off in FS_POINTER_OFFSETS:
            val = read32(emu, addr + off)
            if is_valid_ptr(val):
                ptr_count += 1

        if ptr_count >= 12:
            candidates.append((addr, ptr_count))

    # Sort by pointer count (descending)
    candidates.sort(key=lambda x: -x[1])
    return candidates


def validate_terrain_chain(emu: DeSmuME, fs_addr: int, player: dict) -> dict | None:
    """Follow FieldSystem → LandDataManager → LoadedMap → terrainAttributes.

    Returns info dict if valid terrain data found, None otherwise.
    """
    ldm_addr = read32(emu, fs_addr + FS_LAND_DATA_MAN)
    if not is_valid_ptr(ldm_addr):
        return None

    local_x = player["local_x"]
    local_y = player["local_y"]
    player_tile_idx = local_y * MAP_TILES_X + local_x

    results: list[dict] = []

    for q in range(4):
        map_ptr = read32(emu, ldm_addr + LDM_LOADED_MAPS + q * 4)
        if not is_valid_ptr(map_ptr):
            continue

        # Read player's tile
        player_tile = read16(emu, map_ptr + player_tile_idx * 2)

        # Count collision stats for this block
        walkable = 0
        walls = 0
        for i in range(0, TERRAIN_SIZE * 2, 2):
            t = read16(emu, map_ptr + i)
            if t & COLLISION_BIT:
                walls += 1
            else:
                walkable += 1

        results.append({
            "quadrant": q,
            "map_ptr": map_ptr,
            "player_tile": player_tile,
            "player_walkable": not bool(player_tile & COLLISION_BIT),
            "walkable": walkable,
            "walls": walls,
        })

    if not results:
        return None

    return {
        "ldm_addr": ldm_addr,
        "maps": results,
    }


def read_terrain_grid(emu: DeSmuME, terrain_addr: int) -> list[int]:
    """Read 32x32 terrain attributes."""
    return [read16(emu, terrain_addr + i * 2) for i in range(TERRAIN_SIZE)]


def render_grid(tiles: list[int], player_local_x: int, player_local_y: int) -> str:
    """Render a 32x32 tile grid as ASCII."""
    lines: list[str] = []
    lines.append("    " + "".join(f"{x:>3}" for x in range(MAP_TILES_X)))

    for y in range(MAP_TILES_Z):
        row: list[str] = []
        for x in range(MAP_TILES_X):
            tile = tiles[y * MAP_TILES_X + x]
            collision = bool(tile & COLLISION_BIT)
            behavior = tile & BEHAVIOR_MASK

            if x == player_local_x and y == player_local_y:
                ch = "@"
            elif collision:
                ch = "#"
            elif behavior == 0x02:
                ch = "G"  # tall grass
            elif behavior in (0x10, 0x15):
                ch = "~"  # water
            elif behavior in (0x38, 0x39, 0x3A, 0x3B):
                ch = "J"  # jump/ledge
            elif behavior in (0x5D, 0x5E, 0x5F, 0x60, 0x62, 0x63, 0x64, 0x65, 0x69):
                ch = "D"  # door/warp
            elif behavior == 0x67:
                ch = "W"  # warp panel
            elif behavior == 0x83:
                ch = "P"  # PC
            elif behavior == 0x86:
                ch = "T"  # TV
            elif behavior == 0x80:
                ch = "="  # table
            elif behavior in (0xE0, 0xE1, 0xE2):
                ch = "B"  # bookshelf
            elif behavior == 0x00:
                ch = "."  # floor
            else:
                ch = "."  # other walkable
            row.append(ch)
        lines.append(f"{y:>3} " + " ".join(row))

    return "\n".join(lines)


def analyze_terrain(tiles: list[int]) -> dict:
    """Analyze terrain data statistics."""
    walkable = sum(1 for t in tiles if not (t & COLLISION_BIT))
    walls = sum(1 for t in tiles if t & COLLISION_BIT)
    behaviors: dict[int, int] = {}
    for t in tiles:
        b = t & BEHAVIOR_MASK
        behaviors[b] = behaviors.get(b, 0) + 1
    return {"walkable": walkable, "walls": walls, "behaviors": behaviors}


def dump_field_system(emu: DeSmuME, addr: int) -> None:
    """Dump FieldSystem struct fields for debugging."""
    names = [
        (0x00, "processManager"), (0x04, "unk_04"), (0x08, "bgConfig"),
        (0x0C, "saveData"), (0x10, "task"), (0x14, "mapHeaderData"),
        (0x18, "bottomScreen"), (0x1C, "location"), (0x20, "unk_20"),
        (0x24, "camera"), (0x28, "landDataMan"), (0x2C, "mapMatrix"),
        (0x30, "areaDataMan"), (0x34, "unk_34"), (0x38, "mapObjMan"),
        (0x3C, "playerAvatar"), (0x40, "fieldEffMan"), (0x44, "areaModelAttrs"),
        (0x48, "unk_48"), (0x4C, "areaLightMan"), (0x50, "mapPropAnimMan"),
        (0x54, "mapPropOneShotAnimMan"), (0x58, "terrainAttrs"),
        (0x5C, "terrainCollisionMan"),
    ]
    for off, name in names:
        val = read32(emu, addr + off)
        ptr_tag = " (ptr)" if is_valid_ptr(val) else ""
        print(f"    +{off:#04x} {name:28s} = {val:#010x}{ptr_tag}")


def main() -> None:
    # Find a good savestate
    default_paths = [
        Path("platinum_save/emulator.dst"),
        Path("tests/output/coord_search/walking.dst"),
        Path("tests/output/clean_intro/golden_gameplay.dst"),
    ]

    if len(sys.argv) > 1:
        savestate = Path(sys.argv[1])
    else:
        savestate = next((p for p in default_paths if p.exists()), default_paths[-1])

    if not savestate.exists():
        print(f"Savestate not found: {savestate}")
        sys.exit(1)

    print(f"Loading savestate: {savestate}")
    emu = DeSmuME()
    emu.open("roms/Pokemon - Platinum Version (USA).nds")
    emu.savestate.load_file(str(savestate))

    # Let game settle
    for _ in range(10):
        emu.cycle(with_joystick=False)

    # Get player info
    player = get_player_info(emu)
    print(f"\n=== Player Info ===")
    print(f"  General block: {player['general']:#010x}")
    print(f"  SaveData ptr:  {player['save_data_ptr']:#010x}")
    print(f"  Map ID:        {player['map_id']}")
    print(f"  Save coords:   ({player['save_x']}, {player['save_y']})")
    print(f"  RT coords:     ({player['rt_x']}, {player['rt_y']})")
    print(f"  Using:         {player['coord_source']} → ({player['x']}, {player['y']})")
    print(f"  Local tile:    ({player['local_x']}, {player['local_y']})")

    # Strategy 1: Structural fingerprinting scan
    print(f"\n=== Strategy 1: Structural Fingerprinting ===")
    density_candidates = scan_for_field_system(emu, player["save_data_ptr"])
    print(f"  Found {len(density_candidates)} candidates")

    for addr, count in density_candidates[:10]:
        print(f"\n  Candidate {addr:#010x} ({count} valid pointers):")
        dump_field_system(emu, addr)

        # Try to follow terrain chain
        result = validate_terrain_chain(emu, addr, player)
        if result:
            print(f"\n  LandDataManager @ {result['ldm_addr']:#010x}")
            for m in result["maps"]:
                walkable_tag = "WALKABLE" if m["player_walkable"] else "BLOCKED"
                print(f"    Quadrant {m['quadrant']}: LoadedMap @ {m['map_ptr']:#010x}")
                print(f"      Player tile: {m['player_tile']:#06x} ({walkable_tag})")
                print(f"      Stats: {m['walkable']} walkable, {m['walls']} walls")

            # Show terrain grids for maps where player tile is walkable
            for m in result["maps"]:
                if m["player_walkable"]:
                    tiles = read_terrain_grid(emu, m["map_ptr"])
                    stats = analyze_terrain(tiles)
                    print(f"\n  === Quadrant {m['quadrant']} Terrain Grid ===")
                    print(f"  Behaviors:")
                    sorted_b = sorted(stats["behaviors"].items(), key=lambda x: -x[1])
                    for bval, cnt in sorted_b[:8]:
                        bname = TILE_BEHAVIORS.get(bval, f"0x{bval:02x}")
                        print(f"    {bval:#04x} ({bname}): {cnt}")
                    print(render_grid(tiles, player["local_x"], player["local_y"]))

    # Also check TerrainAttributes path for best candidate
    if density_candidates:
        best_addr = density_candidates[0][0]
        ta_ptr = read32(emu, best_addr + FS_TERRAIN_ATTRS)
        if is_valid_ptr(ta_ptr):
            print(f"\n=== TerrainAttributes @ {ta_ptr:#010x} ===")
            print(f"  mapMatrixIndexToBlockIndex[0:16]:", end="")
            for i in range(16):
                print(f" {read8(emu, ta_ptr + i):02x}", end="")
            print()

            # Read block 0 terrain
            ta_data_start = ta_ptr + 225  # After the 225-byte lookup table
            tiles = read_terrain_grid(emu, ta_data_start)
            stats = analyze_terrain(tiles)
            print(f"  Block 0: {stats['walkable']} walkable, {stats['walls']} walls")

            sorted_b = sorted(stats["behaviors"].items(), key=lambda x: -x[1])
            for bval, cnt in sorted_b[:8]:
                bname = TILE_BEHAVIORS.get(bval, f"0x{bval:02x}")
                print(f"    {bval:#04x} ({bname}): {cnt}")
            print(render_grid(tiles, player["local_x"], player["local_y"]))

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
