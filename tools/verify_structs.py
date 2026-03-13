#!/usr/bin/env python3
"""Verify MapObject/NPC/Warp struct offsets against live RAM data."""

from __future__ import annotations
import os, sys
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "dummy"
sys.path.insert(0, str(Path(__file__).parent.parent))

from desmume.emulator import DeSmuME
from src.harness.collision import CollisionReader

# Offsets from pret/pokeplatinum
FS_MAP_HEADER_DATA = 0x14
FS_MAP_OBJ_MAN = 0x38
FS_PLAYER_AVATAR = 0x3C

# MapObjectManager
MOM_MAX_OBJECTS = 0x04
MOM_OBJECT_CNT = 0x08
MOM_MAP_OBJ_PTR = 0x124

# MapObject (296 bytes = 0x128 each)
MO_SIZE = 0x128
MO_STATUS = 0x00
MO_LOCAL_ID = 0x08
MO_MAP_ID = 0x0C
MO_GRAPHICS_ID = 0x10
MO_MOVEMENT_TYPE = 0x14
MO_SCRIPT = 0x20
MO_FACING_DIR = 0x28
MO_X = 0x64
MO_Y = 0x68
MO_Z = 0x6C

# Status flags
MO_STATUS_HIDDEN = 1 << 9

# MapHeaderData
MHD_NUM_OBJ_EVENTS = 0x04
MHD_NUM_WARP_EVENTS = 0x08
MHD_OBJ_EVENTS_PTR = 0x14
MHD_WARP_EVENTS_PTR = 0x18

# WarpEvent (12 bytes)
WE_SIZE = 0x0C
WE_X = 0x00
WE_Z = 0x02
WE_DEST_HEADER = 0x04
WE_DEST_WARP = 0x06

# PlayerAvatar
PA_MAP_OBJ = 0x30

DIR_NAMES = {0: "North", 1: "South", 2: "West", 3: "East"}


def read8(emu, addr):
    return emu.memory.unsigned[addr]

def read16(emu, addr):
    return emu.memory.unsigned.read_short(addr)

def read32(emu, addr):
    return emu.memory.unsigned.read_long(addr)

def is_ptr(v):
    return 0x02000000 <= v < 0x03000000


def main():
    emu = DeSmuME()
    emu.open("roms/Pokemon - Platinum Version (USA).nds")

    for path_str in ["platinum_save/emulator.dst", "tests/output/coord_search/walking.dst"]:
        path = Path(path_str)
        if not path.exists():
            continue

        print(f"\n{'='*70}")
        print(f"  {path}")
        print(f"{'='*70}")

        emu.savestate.load_file(str(path))
        for _ in range(30):
            emu.cycle(with_joystick=False)

        # Find FieldSystem
        reader = CollisionReader(emu)
        if not reader.find_field_system():
            print("  FieldSystem not found!")
            continue

        fs = reader._field_system_addr
        print(f"  FieldSystem @ {fs:#010x}")

        # Player position for reference
        general = read32(emu, 0x02101D40) + 0x14
        map_id = read16(emu, general + 0x1280)
        rt_x = read8(emu, 0x021C5CE6)
        rt_y = read8(emu, 0x021C5CEE)
        print(f"  Player: ({rt_x}, {rt_y}) on map {map_id}")

        # === PlayerAvatar ===
        pa_addr = read32(emu, fs + FS_PLAYER_AVATAR)
        print(f"\n  --- PlayerAvatar @ {pa_addr:#010x} ---")
        if is_ptr(pa_addr):
            pa_mo = read32(emu, pa_addr + PA_MAP_OBJ)
            print(f"  MapObject ptr: {pa_mo:#010x}")
            if is_ptr(pa_mo):
                px = read32(emu, pa_mo + MO_X)
                pz = read32(emu, pa_mo + MO_Z)
                pdir = read32(emu, pa_mo + MO_FACING_DIR)
                print(f"  Player pos from MapObject: x={px}, z={pz}")
                print(f"  Player facing: {pdir} = {DIR_NAMES.get(pdir, '???')}")
                print(f"  Match RT coords? x={px==rt_x}, z={pz==rt_y}")

        # === MapObjectManager ===
        mom_addr = read32(emu, fs + FS_MAP_OBJ_MAN)
        print(f"\n  --- MapObjectManager @ {mom_addr:#010x} ---")
        if is_ptr(mom_addr):
            max_obj = read32(emu, mom_addr + MOM_MAX_OBJECTS)
            obj_cnt = read32(emu, mom_addr + MOM_OBJECT_CNT)
            map_obj_ptr = read32(emu, mom_addr + MOM_MAP_OBJ_PTR)
            print(f"  maxObjects: {max_obj}")
            print(f"  objectCnt: {obj_cnt}")
            print(f"  mapObj array: {map_obj_ptr:#010x}")

            if is_ptr(map_obj_ptr) and max_obj < 100:
                print(f"\n  NPCs (iterating {max_obj} slots):")
                for i in range(max_obj):
                    mo = map_obj_ptr + i * MO_SIZE
                    status = read32(emu, mo + MO_STATUS)

                    # Skip completely empty slots (status=0)
                    if status == 0:
                        continue

                    hidden = bool(status & MO_STATUS_HIDDEN)
                    local_id = read32(emu, mo + MO_LOCAL_ID)
                    gfx_id = read32(emu, mo + MO_GRAPHICS_ID)
                    mv_type = read32(emu, mo + MO_MOVEMENT_TYPE)
                    script = read32(emu, mo + MO_SCRIPT)
                    facing = read32(emu, mo + MO_FACING_DIR)
                    x = read32(emu, mo + MO_X)
                    z = read32(emu, mo + MO_Z)
                    map_id_obj = read32(emu, mo + MO_MAP_ID)

                    vis = "HIDDEN" if hidden else "visible"
                    dir_name = DIR_NAMES.get(facing, f"?{facing}")
                    print(f"    [{i}] id={local_id} gfx={gfx_id} pos=({x},{z}) "
                          f"face={dir_name} mv={mv_type} scr={script} "
                          f"map={map_id_obj} [{vis}] status={status:#010x}")

        # === MapHeaderData (warps) ===
        mhd_addr = read32(emu, fs + FS_MAP_HEADER_DATA)
        print(f"\n  --- MapHeaderData @ {mhd_addr:#010x} ---")
        if is_ptr(mhd_addr):
            num_obj = read32(emu, mhd_addr + MHD_NUM_OBJ_EVENTS)
            num_warps = read32(emu, mhd_addr + MHD_NUM_WARP_EVENTS)
            warp_ptr = read32(emu, mhd_addr + MHD_WARP_EVENTS_PTR)
            print(f"  numObjectEvents: {num_obj}")
            print(f"  numWarpEvents: {num_warps}")
            print(f"  warpEvents: {warp_ptr:#010x}")

            if is_ptr(warp_ptr) and num_warps < 50:
                # Try to load map names
                try:
                    from src.harness.data.map_headers import MAP_HEADERS
                except ImportError:
                    MAP_HEADERS = {}

                print(f"\n  Warps:")
                for i in range(num_warps):
                    we = warp_ptr + i * WE_SIZE
                    wx = read16(emu, we + WE_X)
                    wz = read16(emu, we + WE_Z)
                    dest_hdr = read16(emu, we + WE_DEST_HEADER)
                    dest_warp = read16(emu, we + WE_DEST_WARP)
                    dest_name = MAP_HEADERS.get(dest_hdr, f"map_{dest_hdr}")
                    print(f"    [{i}] pos=({wx},{wz}) → map {dest_hdr} ({dest_name}) warp#{dest_warp}")

    print("\n\nDone!")


if __name__ == "__main__":
    main()
