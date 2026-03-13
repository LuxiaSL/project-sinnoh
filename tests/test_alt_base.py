"""
Investigate the alternate base pointer at 0x02101D40.
This gave us Money=3000 with AR offsets — that's the correct value!
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

    old_base = read32(emu, 0x02101D2C)
    alt_base = read32(emu, 0x02101D40)
    print(f"Old base (0x02101D2C): 0x{old_base:08X}")
    print(f"Alt base (0x02101D40): 0x{alt_base:08X}")
    print(f"Difference: 0x{alt_base - old_base:04X} ({alt_base - old_base} bytes)")

    # ================================================================
    # Theory: AR offsets have a +0x14 shift vs PKHeX save file offsets.
    # AR money = 0x0090, PKHeX money = 0x007C, diff = 0x14
    # If so, alt_base points 0x14 bytes into the save block.
    # save_block_start = alt_base - 0x14
    # ================================================================
    
    save_start = alt_base  # Try both: alt_base directly and alt_base - 0x14
    
    print("\n" + "=" * 70)
    print("APPROACH 1: AR offsets from alt_base (0x02101D40)")
    print("=" * 70)
    
    # AR-confirmed offsets
    print(f"  Money (AR +0x90): {read32(emu, alt_base + 0x0090)}")
    print(f"  Badges (AR +0x96): {read8(emu, alt_base + 0x0096)}")
    
    # Try reading name — AR doesn't document name offset, but let's 
    # try PKHeX offset + 0x14 shift
    name_ar = read_unicode_str(emu, alt_base + 0x007C)  # PKHeX 0x68 + 0x14
    print(f"  Name (AR +0x7C = PKHeX 0x68+0x14): '{name_ar}'")

    # Hmm, let's also try: the alt_base might itself be a pointer table.
    # Dump the first 128 bytes from alt_base.
    print(f"\n  Hex dump of alt_base region (first 256 bytes):")
    raw = read_bytes(emu, alt_base, 256)
    print(hexdump(raw, alt_base))

    # ================================================================
    print("\n" + "=" * 70)
    print("APPROACH 2: PKHeX offsets from alt_base - 0x14")
    print("=" * 70)
    
    save = alt_base - 0x14
    print(f"  Assumed save block start: 0x{save:08X}")
    
    # PKHeX Trainer1 starts at 0x0068
    name_pk = read_unicode_str(emu, save + 0x0068)
    tid_pk = read16(emu, save + 0x0078)
    sid_pk = read16(emu, save + 0x007A)
    money_pk = read32(emu, save + 0x007C)
    gender_pk = read8(emu, save + 0x0080)
    badges_pk = read8(emu, save + 0x0082)
    hours_pk = read16(emu, save + 0x008A)
    mins_pk = read8(emu, save + 0x008C)
    secs_pk = read8(emu, save + 0x008D)
    
    print(f"  Name: '{name_pk}'")
    print(f"  TID: {tid_pk}, SID: {sid_pk}")
    print(f"  Money: {money_pk}")
    print(f"  Gender: {gender_pk}")
    print(f"  Badges: {badges_pk}")
    print(f"  Play time: {hours_pk}h {mins_pk}m {secs_pk}s")
    
    # Coordinates
    mapid_pk = read32(emu, save + 0x1280)
    x_pk = read32(emu, save + 0x1288)
    y_pk = read32(emu, save + 0x128C)
    print(f"  Map ID: {mapid_pk}")
    print(f"  X: {x_pk}, Y: {y_pk}")
    
    # Party
    party_pk = read8(emu, save + 0x009C)
    print(f"  Party count: {party_pk}")

    # ================================================================
    print("\n" + "=" * 70)
    print("APPROACH 3: Try various offsets to find name")
    print("=" * 70)
    
    # Scan around alt_base for unicode strings
    print("  Scanning alt_base region for ASCII-range Unicode strings...")
    for off in range(0x0000, 0x0200, 2):
        name = read_unicode_str(emu, alt_base + off, 8)
        if len(name) >= 3 and all(c.isalpha() or c.isspace() for c in name):
            raw = read_bytes(emu, alt_base + off, 16)
            print(f"    alt_base+0x{off:04X}: '{name}' raw=[{' '.join(f'{b:02X}' for b in raw)}]")

    # ================================================================
    print("\n" + "=" * 70)
    print("APPROACH 4: Direct scan for 'AAAA' pattern")
    print("=" * 70)
    # During the clean run, we A-mashed through naming. The resulting
    # name is probably "AAAAAAA" or similar (the keyboard's first letter
    # being typed repeatedly). In Gen 4 Unicode: A = 0x0041
    # So we'd expect: 41 00 41 00 41 00 41 00...
    
    # Search a wide range around alt_base
    aa_pattern = bytes([0x41, 0x00, 0x41, 0x00, 0x41, 0x00])
    print(f"  Searching for 'AAA' (0x41 0x00 × 3) near alt_base...")
    for off in range(0x0000, 0x5000, 2):
        chunk = read_bytes(emu, alt_base + off, 6)
        if chunk == aa_pattern:
            # Found! Read more context
            full = read_bytes(emu, alt_base + off, 24)
            name = read_unicode_str(emu, alt_base + off, 12)
            print(f"    FOUND at alt_base+0x{off:04X}: '{name}'")
            print(f"    raw: [{' '.join(f'{b:02X}' for b in full)}]")
    
    # Also search from old_base
    print(f"\n  Searching from old_base...")
    for off in range(0x0000, 0x15000, 2):
        chunk = read_bytes(emu, old_base + off, 6)
        if chunk == aa_pattern:
            full = read_bytes(emu, old_base + off, 24)
            name = read_unicode_str(emu, old_base + off, 12)
            print(f"    FOUND at old_base+0x{off:04X}: '{name}'")
            print(f"    raw: [{' '.join(f'{b:02X}' for b in full)}]")
            # Check what's near this — is it a trainer block?
            # Player name should be followed by TID/SID/Money
            possible_tid = read16(emu, old_base + off + 16)
            possible_money = read32(emu, old_base + off + 20)
            print(f"      +16: {possible_tid} (TID?), +20: {possible_money} (money?)")

    emu.destroy()

if __name__ == "__main__":
    main()
