"""
Phase 1A.0: Offset Investigation

Load the golden savestate and systematically probe memory to find the correct
offset mapping from the base pointer.
"""

import os
os.environ["SDL_VIDEODRIVER"] = "dummy"

import struct
from pathlib import Path
from desmume.emulator import DeSmuME
from desmume.controls import keymask, Keys

SAVESTATE = Path(__file__).parent / "output" / "clean_intro" / "golden_gameplay.dst"
ROM_PATH = Path(__file__).parent.parent / "roms" / "Pokemon - Platinum Version (USA).nds"
BASE_PTR_ADDR = 0x02101D2C

def read32(emu, addr):
    return emu.memory.unsigned.read_long(addr)

def read16(emu, addr):
    return emu.memory.unsigned.read_short(addr)

def read8(emu, addr):
    return emu.memory.unsigned[addr]

def read_bytes(emu, addr, count):
    return bytes([emu.memory.unsigned[addr + i] for i in range(count)])

def read_unicode_str(emu, addr, max_chars=8):
    """Read a Gen 4 Unicode string (16-bit chars, 0xFFFF terminated)."""
    chars = []
    for i in range(max_chars):
        c = read16(emu, addr + i * 2)
        if c == 0xFFFF or c == 0:
            break
        chars.append(chr(c))
    return ''.join(chars)

def hexdump(data, addr, width=16):
    """Print a hex dump of bytes."""
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i+width]
        hex_part = ' '.join(f'{b:02X}' for b in chunk)
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f"  0x{addr+i:08X}: {hex_part:<{width*3}}  {ascii_part}")
    return '\n'.join(lines)

def main():
    print("=" * 70)
    print("Phase 1A.0: Offset Investigation")
    print("=" * 70)

    if not SAVESTATE.exists():
        print(f"ERROR: Savestate not found: {SAVESTATE}")
        return

    emu = DeSmuME()
    emu.open(str(ROM_PATH))

    # Load the golden savestate
    emu.savestate.load_file(str(SAVESTATE))
    for _ in range(30):
        emu.cycle(with_joystick=False)

    # Get the base pointer
    base = read32(emu, BASE_PTR_ADDR)
    print(f"\nBase pointer: 0x{base:08X}")
    print(f"Base pointer address: 0x{BASE_PTR_ADDR:08X}")

    if base < 0x02000000 or base > 0x02FFFFFF:
        print("ERROR: Base pointer out of main RAM range!")
        emu.destroy()
        return

    # ================================================================
    # Test 1: Dump raw bytes around the base pointer
    # ================================================================
    print("\n" + "=" * 70)
    print("TEST 1: Raw hex dump at base pointer (first 256 bytes)")
    print("=" * 70)
    raw = read_bytes(emu, base, 256)
    print(hexdump(raw, base))

    # ================================================================
    # Test 2: Try reading player name at various offsets
    # ================================================================
    print("\n" + "=" * 70)
    print("TEST 2: Player name search")
    print("=" * 70)

    # The player name we set during intro was via A-mashing, so it might be
    # a default name or whatever the game assigned.
    # Try the documented offset (0x68 from save start)
    offsets_to_try = [0x0068, 0x0000, 0x0004, 0x0008, 0x0010, 0x0020, 0x0040]
    for off in offsets_to_try:
        name = read_unicode_str(emu, base + off)
        raw_bytes = read_bytes(emu, base + off, 16)
        hex_str = ' '.join(f'{b:02X}' for b in raw_bytes)
        print(f"  base+0x{off:04X}: name='{name}' raw=[{hex_str}]")

    # ================================================================
    # Test 3: Try coordinates at PKHeX offsets
    # ================================================================
    print("\n" + "=" * 70)
    print("TEST 3: Player coordinates")
    print("=" * 70)

    coord_offsets = {
        "Map ID (0x1280)": 0x1280,
        "X coord (0x1288)": 0x1288,
        "Y coord (0x128C)": 0x128C,
        "X2 (0x287E)": 0x287E,
        "Y2 (0x2882)": 0x2882,
        "Z (0x2886)": 0x2886,
    }
    for label, off in coord_offsets.items():
        val = read32(emu, base + off)
        print(f"  {label}: {val} (0x{val:08X})")

    # ================================================================
    # Test 4: Try party count and party data
    # ================================================================
    print("\n" + "=" * 70)
    print("TEST 4: Party Pokemon")
    print("=" * 70)

    # PKHeX offset: party count at base+0x9C, party data at base+0xA0
    party_count_pkhex = read8(emu, base + 0x009C)
    print(f"  Party count (base+0x9C): {party_count_pkhex}")

    # MKDasher offset: party at base+0xD2AC
    print(f"\n  --- PKHeX party offset (base+0xA0) ---")
    for slot in range(min(party_count_pkhex, 6) if party_count_pkhex <= 6 else 1):
        addr = base + 0xA0 + (slot * 0xEC)
        pid = read32(emu, addr)
        checksum = read16(emu, addr + 0x06)
        # Species is at 0x08 in the structure but may be encrypted
        raw_species = read16(emu, addr + 0x08)
        level_raw = read8(emu, addr + 0x8C)
        hp_raw = read16(emu, addr + 0x8E)
        maxhp_raw = read16(emu, addr + 0x90)
        raw_first32 = read_bytes(emu, addr, 32)
        print(f"  Slot {slot}: PID=0x{pid:08X} checksum=0x{checksum:04X}")
        print(f"    raw species (encrypted?)={raw_species} level={level_raw} HP={hp_raw}/{maxhp_raw}")
        print(f"    first 32 bytes: {' '.join(f'{b:02X}' for b in raw_first32)}")

    print(f"\n  --- MKDasher party offset (base+0xD2AC) ---")
    for slot in range(min(party_count_pkhex, 6) if party_count_pkhex <= 6 else 1):
        addr = base + 0xD2AC + (slot * 0xEC)
        pid = read32(emu, addr)
        checksum = read16(emu, addr + 0x06)
        raw_species = read16(emu, addr + 0x08)
        level_raw = read8(emu, addr + 0x8C)
        hp_raw = read16(emu, addr + 0x8E)
        maxhp_raw = read16(emu, addr + 0x90)
        raw_first32 = read_bytes(emu, addr, 32)
        print(f"  Slot {slot}: PID=0x{pid:08X} checksum=0x{checksum:04X}")
        print(f"    raw species (encrypted?)={raw_species} level={level_raw} HP={hp_raw}/{maxhp_raw}")
        print(f"    first 32 bytes: {' '.join(f'{b:02X}' for b in raw_first32)}")

    # ================================================================
    # Test 5: Money and badges
    # ================================================================
    print("\n" + "=" * 70)
    print("TEST 5: Money and badges")
    print("=" * 70)

    money = read32(emu, base + 0x007C)
    badges = read8(emu, base + 0x0082)
    gender = read8(emu, base + 0x0080)
    tid = read16(emu, base + 0x0078)
    sid = read16(emu, base + 0x007A)
    print(f"  Money (base+0x7C): {money}")
    print(f"  Badges (base+0x82): {badges} (0b{badges:08b})")
    print(f"  Gender (base+0x80): {gender}")
    print(f"  TID (base+0x78): {tid}")
    print(f"  SID (base+0x7A): {sid}")

    # Also try the AR-style offsets (which have slight differences)
    print("\n  --- AR-style offsets ---")
    money_ar = read32(emu, base + 0x0090)
    badges_ar = read8(emu, base + 0x0096)
    print(f"  Money (base+0x90): {money_ar}")
    print(f"  Badges (base+0x96): {badges_ar} (0b{badges_ar:08b})")

    # ================================================================
    # Test 6: Scan for player name in wider RAM region
    # ================================================================
    print("\n" + "=" * 70)
    print("TEST 6: Scan for player name pattern in RAM")
    print("=" * 70)
    # We A-mashed through name entry, so we likely got a default name.
    # Common Platinum default male names: Lucas, Diamond
    # In Gen 4 Unicode, 'L' = 0x004C, 'u' = 0x0075, etc.
    # But we probably got something random from A-mashing the keyboard.
    # Let's scan for any unicode-like string patterns near the base.

    # First, let's look at what the game shows us — take a screenshot label
    # Actually, let's just scan a wider area for 16-bit unicode patterns
    print("  Scanning base+0x0000 to base+0x2000 for Unicode strings...")
    for off in range(0, 0x2000, 0x10):
        # Check if this looks like a unicode string (non-zero chars, reasonable values)
        chars = []
        looks_like_string = True
        for i in range(8):
            c = read16(emu, base + off + i * 2)
            if c == 0xFFFF or c == 0:
                if i == 0:
                    looks_like_string = False
                break
            if c > 0x7F or c < 0x20:
                looks_like_string = False
                break
            chars.append(chr(c))

        if looks_like_string and len(chars) >= 2:
            name = ''.join(chars)
            print(f"    base+0x{off:04X}: '{name}'")

    # ================================================================
    # Test 7: Try reading play time
    # ================================================================
    print("\n" + "=" * 70)
    print("TEST 7: Play time")
    print("=" * 70)
    hours = read16(emu, base + 0x008A)
    minutes = read8(emu, base + 0x008C)
    seconds = read8(emu, base + 0x008D)
    print(f"  Play time (base+0x8A): {hours}h {minutes}m {seconds}s")

    # ================================================================
    # Test 8: Dump the trainer data region more carefully
    # ================================================================
    print("\n" + "=" * 70)
    print("TEST 8: Trainer region dump (base+0x60 to base+0xA0)")
    print("=" * 70)
    trainer_raw = read_bytes(emu, base + 0x60, 64)
    print(hexdump(trainer_raw, base + 0x60))

    emu.destroy()
    print("\n" + "=" * 70)
    print("Investigation complete!")
    print("=" * 70)

if __name__ == "__main__":
    main()
