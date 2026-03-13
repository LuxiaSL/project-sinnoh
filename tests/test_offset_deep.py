"""
Deeper offset investigation. The base pointer at 0x02101D2C does NOT point
to the save block start. Need to find the actual save data in RAM.
"""

import os
os.environ["SDL_VIDEODRIVER"] = "dummy"

from pathlib import Path
from desmume.emulator import DeSmuME

SAVESTATE = Path(__file__).parent / "output" / "clean_intro" / "golden_gameplay.dst"
ROM_PATH = Path(__file__).parent.parent / "roms" / "Pokemon - Platinum Version (USA).nds"

def read32(emu, addr):
    return emu.memory.unsigned.read_long(addr)

def read16(emu, addr):
    return emu.memory.unsigned.read_short(addr)

def read8(emu, addr):
    return emu.memory.unsigned[addr]

def read_bytes(emu, addr, count):
    return bytes([emu.memory.unsigned[addr + i] for i in range(count)])

def read_unicode_str(emu, addr, max_chars=16):
    chars = []
    for i in range(max_chars):
        c = read16(emu, addr + i * 2)
        if c == 0xFFFF or c == 0:
            break
        chars.append(chr(c))
    return ''.join(chars)

def hexdump(data, addr, width=16):
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i+width]
        hex_part = ' '.join(f'{b:02X}' for b in chunk)
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f"  0x{addr+i:08X}: {hex_part:<{width*3}}  {ascii_part}")
    return '\n'.join(lines)

def main():
    emu = DeSmuME()
    emu.open(str(ROM_PATH))
    emu.savestate.load_file(str(SAVESTATE))
    for _ in range(30):
        emu.cycle(with_joystick=False)

    base = read32(emu, 0x02101D2C)
    print(f"Base pointer (0x02101D2C): 0x{base:08X}")

    # ================================================================
    # Try alternate AR base pointer at 0x02101D40
    # ================================================================
    print("\n=== Alternate base pointer at 0x02101D40 ===")
    try:
        alt_base = read32(emu, 0x02101D40)
        print(f"Alt base pointer: 0x{alt_base:08X}")
        if 0x02000000 < alt_base < 0x03000000:
            # Try AR money offset (0x0090)
            money_ar = read32(emu, alt_base + 0x0090)
            badges_ar = read8(emu, alt_base + 0x0096)
            print(f"  Money (alt+0x90): {money_ar}")
            print(f"  Badges (alt+0x96): {badges_ar}")
    except Exception as e:
        print(f"  Error: {e}")

    # ================================================================
    # The base pointer might point to a structure that CONTAINS a pointer
    # to the save block. Dereference pointers at the base.
    # ================================================================
    print("\n=== Dereferencing pointers at base ===")
    for off in range(0, 0x40, 4):
        val = read32(emu, base + off)
        if 0x02000000 < val < 0x03000000:
            # This looks like a pointer — try reading data from it
            sub_name = read_unicode_str(emu, val + 0x0068)
            sub_money = read32(emu, val + 0x007C)
            sub_badges = read8(emu, val + 0x0082)
            sub_party = read8(emu, val + 0x009C)
            sub_mapid = read32(emu, val + 0x1280)
            sub_x = read32(emu, val + 0x1288)
            sub_y = read32(emu, val + 0x128C)
            print(f"  base+0x{off:02X} → 0x{val:08X}:")
            print(f"    name='{sub_name}' money={sub_money} badges={sub_badges}")
            print(f"    party={sub_party} map={sub_mapid} x={sub_x} y={sub_y}")

    # ================================================================
    # Try scanning the wider pointer table area
    # ================================================================
    print("\n=== Scanning 0x02101D00 - 0x02101D80 for pointers ===")
    for addr in range(0x02101D00, 0x02101D80, 4):
        val = read32(emu, addr)
        if 0x02000000 < val < 0x03000000:
            print(f"  0x{addr:08X} → 0x{val:08X}")

    # ================================================================
    # The base pointer in the MKDasher script is used differently.
    # Let's check if the save data is simply at a fixed address.
    # Try some common Platinum save block RAM locations.
    # ================================================================
    print("\n=== Trying common save block locations ===")
    # Sometimes the save block is loaded to a heap address.
    # Let's try reading player name from the values we found as pointers.
    
    # The first 3 values at base look like pointers:
    # 0x021D0D81, 0x021D0E21, 0x021D0F7D
    # These are in a different RAM region. Let's check them.
    
    ptr1 = read32(emu, base + 0x00)  # 0x021D0D81
    ptr2 = read32(emu, base + 0x04)  # 0x021D0E21
    ptr3 = read32(emu, base + 0x08)  # 0x021D0F7D
    print(f"  Ptr at base+0: 0x{ptr1:08X}")
    print(f"  Ptr at base+4: 0x{ptr2:08X}")
    print(f"  Ptr at base+8: 0x{ptr3:08X}")

    # ================================================================
    # Let's try finding the save block by searching for known patterns.
    # We know badges=0 on a fresh game. Money should be 0 or 3000.
    # The player name should be a valid unicode string.
    # 
    # Alternative: look at how the MKDasher Lua script ACTUALLY uses
    # the base pointer. It reads party at base+0xD2AC.
    # But party count was 0 — maybe we genuinely don't have Pokemon yet
    # at this savestate. Let's verify by advancing the game to get a
    # Pokemon, or just check what's at 0xD2AC.
    # ================================================================
    print("\n=== MKDasher party region dump (base+0xD2AC, 64 bytes) ===")
    mkd_raw = read_bytes(emu, base + 0xD2AC, 64)
    print(hexdump(mkd_raw, base + 0xD2AC))

    # ================================================================
    # Actually, wait. In Platinum, the player doesn't have a Pokemon in
    # their bedroom. They get it at Lake Verity. So party=0 might be
    # CORRECT. But coordinates and name should still be valid.
    #
    # The save block offsets from PKHeX are for the SAVE FILE, not live
    # RAM. The live RAM structure might use different offsets.
    # 
    # Let's look at what the Lua scripts actually do more carefully.
    # The MKDasher script subtracts a "pokemon data offset" from base.
    # Let me try: are coordinates RELATIVE to base or at fixed addrs?
    # ================================================================
    
    # Try reading coordinates at the ARM9 breakpoint addresses directly
    # These are CODE addresses, not data, so this won't work directly.
    # But let's try scanning for coordinate-like values.
    
    # In the bedroom in Twinleaf, coordinates should be small numbers
    # (like single/double digits for X and Y within the room)
    
    print("\n=== Scanning for coordinate-like values (looking for small ints) ===")
    # The player is in their bedroom. Room coords are typically small.
    # Scan base+0x0000 to base+0x3000 for 32-bit values in range 1-1000
    found_coords = []
    for off in range(0, 0x3000, 4):
        val = read32(emu, base + off)
        if 1 <= val <= 1000:
            found_coords.append((off, val))
    
    # Too many results probably. Let's look for PAIRS of small values
    print("  Looking for adjacent pairs of reasonable coordinates...")
    for i in range(len(found_coords) - 1):
        off1, val1 = found_coords[i]
        off2, val2 = found_coords[i + 1]
        if off2 - off1 == 4 and 1 <= val1 <= 600 and 1 <= val2 <= 600:
            print(f"    base+0x{off1:04X}: ({val1}, {val2})")

    # ================================================================
    # Let's try yet another approach. PKHeX's SAV4.cs probably has
    # offsets that are relative to the start of the SAVE BLOCK in the
    # file. The game loads this save block into RAM somewhere. The
    # base pointer at 0x02101D2C might point to a GAME STATE structure,
    # not the save block.
    # 
    # Let me look for the save block by searching for its magic/header.
    # Gen 4 saves have a specific structure with a footer containing
    # block size and checksum.
    # ================================================================
    
    # Try to find where name data actually lives
    # The name we entered was via A-mashing. Let's see what happened.
    # Try scanning broader RAM for any Pokemon trainer name pattern.
    
    # Actually, let's try a smarter approach: find where the save data
    # was loaded. The save block for Platinum small block is 0xCF2C bytes.
    # Its size (0xCF2C = 53036) might appear as a metadata value.
    print("\n=== Looking for save block size markers (0xCF2C) ===")
    for addr in range(0x02100000, 0x02110000, 4):
        val = read32(emu, addr)
        if val == 0xCF2C or val == 0x0000CF2C:
            print(f"  Found 0xCF2C at 0x{addr:08X}")
    
    # ================================================================
    # NEW APPROACH: The base pointer goes to a structure.
    # The MKDasher script for Platinum uses different offsets than PKHeX.
    # MKDasher party is at base+0xD2AC (runtime), PKHeX party is at
    # save+0x00A0 (file). Difference: 0xD20C.
    # 
    # If we apply that same offset to other PKHeX values:
    # - Name: PKHeX 0x0068 + 0xD20C = 0xD274
    # - Money: PKHeX 0x007C + 0xD20C = 0xD288
    # - Badges: PKHeX 0x0082 + 0xD20C = 0xD28E
    # - Map ID: PKHeX 0x1280 + 0xD20C = 0xE48C
    # Let's try these!
    # ================================================================
    print("\n=== Trying MKDasher-derived offsets (PKHeX + 0xD20C) ===")
    mk_name = read_unicode_str(emu, base + 0xD274)
    mk_money = read32(emu, base + 0xD288)
    mk_badges = read8(emu, base + 0xD28E)
    mk_gender = read8(emu, base + 0xD28C)
    mk_tid = read16(emu, base + 0xD284)
    mk_sid = read16(emu, base + 0xD286)
    mk_mapid = read32(emu, base + 0xE48C)
    mk_x = read32(emu, base + 0xE494)
    mk_y = read32(emu, base + 0xE498)
    mk_party = read8(emu, base + 0xD2A8)
    mk_hours = read16(emu, base + 0xD296)
    mk_mins = read8(emu, base + 0xD298)
    mk_secs = read8(emu, base + 0xD299)
    
    print(f"  Name: '{mk_name}'")
    print(f"  TID: {mk_tid}, SID: {mk_sid}")
    print(f"  Money: {mk_money}")
    print(f"  Gender: {mk_gender}")
    print(f"  Badges: {mk_badges} (0b{mk_badges:08b})")
    print(f"  Party count: {mk_party}")
    print(f"  Map ID: {mk_mapid}")
    print(f"  X: {mk_x}, Y: {mk_y}")
    print(f"  Play time: {mk_hours}h {mk_mins}m {mk_secs}s")

    # ================================================================
    # Also try: the offset might not be exactly 0xD20C. Let's compute
    # it more carefully. PKHeX party offset = 0xA0. MKDasher = 0xD2AC.
    # Diff = 0xD2AC - 0xA0 = 0xD20C. OK so that's confirmed.
    # But wait — maybe the structure isn't a simple offset. Let me
    # just try reading name from the MKDasher party region minus 
    # the expected distance.
    # ================================================================
    
    # Alternative: scan near base+0xD200 for unicode strings
    print("\n=== Scanning near base+0xD200 for unicode strings ===")
    for off in range(0xD200, 0xD300, 2):
        chars = []
        for i in range(8):
            c = read16(emu, base + off + i * 2)
            if c == 0xFFFF or c == 0:
                break
            if 0x20 <= c <= 0x7F:
                chars.append(chr(c))
            else:
                break
        if len(chars) >= 3:
            print(f"    base+0x{off:04X}: '{''.join(chars)}'")

    emu.destroy()

if __name__ == "__main__":
    main()
