"""
Final offset verification using PKHeX-derived relationship:
General_start = alt_base + 0x14

PKHeX says (SAV4Pt.cs + SAV4.cs):
- Trainer1 = 0x68 from General
- Name at General[0x68..0x78] (16 bytes, 8 x u16)
- TID at General[0x78] (u16)
- SID at General[0x7A] (u16)
- Money at General[0x7C] (u32) — CONFIRMED: General_start + 0x7C = alt_base + 0x14 + 0x7C = alt_base + 0x90 = 3000
- Gender at General[0x80] (u8)
- Badges at General[0x82] (u8)
- Hours at General[0x8A] (u16)
- Party count at General[0x9C] (u8)
- Party data at General[0xA0] (236 bytes each)
- Map ID at General[0x1280] (u16 NOT u32!)
- X at General[0x1288] (u16)
- Y at General[0x128C] (u16)
"""

import os
os.environ["SDL_VIDEODRIVER"] = "dummy"

from pathlib import Path
from desmume.emulator import DeSmuME
from desmume.controls import keymask, Keys

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

def main():
    emu = DeSmuME()
    emu.open(str(ROM_PATH))
    emu.savestate.load_file(str(SAVESTATE))
    for _ in range(30):
        emu.cycle(with_joystick=False)

    alt_base = read32(emu, 0x02101D40)
    old_base = read32(emu, 0x02101D2C)
    general = alt_base + 0x14  # Our hypothesis
    
    print(f"alt_base (0x02101D40 →): 0x{alt_base:08X}")
    print(f"old_base (0x02101D2C →): 0x{old_base:08X}")
    print(f"General_start (hypothesis): 0x{general:08X}")
    print(f"  alt_base - old_base = 0x{alt_base - old_base:04X} ({alt_base - old_base})")
    print(f"  general - old_base = 0x{general - old_base:04X} ({general - old_base})")

    # ================================================================
    # Read all PKHeX fields from General_start
    # ================================================================
    print("\n" + "=" * 70)
    print("PKHeX OFFSETS from General_start")
    print("=" * 70)

    # Trainer name — dump raw bytes to see encoding
    name_raw = read_bytes(emu, general + 0x68, 16)
    print(f"\n  Name raw (General+0x68): [{' '.join(f'{b:02X}' for b in name_raw)}]")
    # Try interpreting as UTF-16LE
    try:
        name_utf16 = name_raw.decode('utf-16-le').rstrip('\x00').split('\uffff')[0]
        print(f"  Name (UTF-16LE): '{name_utf16}'")
    except:
        print(f"  Name (UTF-16LE decode failed)")
    # Try each u16 individually
    name_chars = []
    for i in range(8):
        c = read16(emu, general + 0x68 + i * 2)
        name_chars.append(c)
        if c == 0xFFFF:
            break
    print(f"  Name u16 values: [{', '.join(f'0x{c:04X}' for c in name_chars)}]")

    # TID/SID
    tid = read16(emu, general + 0x78)
    sid = read16(emu, general + 0x7A)
    print(f"\n  TID (General+0x78): {tid}")
    print(f"  SID (General+0x7A): {sid}")

    # Money
    money = read32(emu, general + 0x7C)
    print(f"  Money (General+0x7C): {money}")

    # Gender
    gender = read8(emu, general + 0x80)
    print(f"  Gender (General+0x80): {gender} ({'Male' if gender == 0 else 'Female' if gender == 1 else f'unknown({gender})'})")

    # Badges
    badges = read8(emu, general + 0x82)
    print(f"  Badges (General+0x82): {badges} (0b{badges:08b})")

    # Play time
    hours = read16(emu, general + 0x8A)
    mins = read8(emu, general + 0x8C)
    secs = read8(emu, general + 0x8D)
    print(f"  Play time (General+0x8A): {hours}h {mins}m {secs}s")

    # Party count
    party_count = read8(emu, general + 0x9C)
    print(f"  Party count (General+0x9C): {party_count}")

    # Coordinates — u16 not u32!
    map_id = read16(emu, general + 0x1280)
    x = read16(emu, general + 0x1288)
    y = read16(emu, general + 0x128C)
    print(f"\n  Map ID (General+0x1280, u16): {map_id}")
    print(f"  X coord (General+0x1288, u16): {x}")
    print(f"  Y coord (General+0x128C, u16): {y}")

    # Also check secondary coords
    x2 = read16(emu, general + 0x287E)
    y2 = read16(emu, general + 0x2882)
    z = read16(emu, general + 0x2886)
    print(f"  X2 (General+0x287E): {x2}")
    print(f"  Y2 (General+0x2882): {y2}")
    print(f"  Z  (General+0x2886): {z}")

    # ================================================================
    # VERIFICATION: Move player and check if coords change
    # ================================================================
    print("\n" + "=" * 70)
    print("MOVEMENT VERIFICATION")
    print("=" * 70)

    # First clear any blocking dialogue
    print("  Clearing dialogue...")
    for _ in range(60):
        emu.input.keypad_add_key(keymask(Keys.KEY_A))
        for _ in range(6):
            emu.cycle(with_joystick=False)
        emu.input.keypad_rm_key(keymask(Keys.KEY_A))
        for _ in range(90):
            emu.cycle(with_joystick=False)

    x_before = read16(emu, general + 0x1288)
    y_before = read16(emu, general + 0x128C)
    map_before = read16(emu, general + 0x1280)
    print(f"  Before: map={map_before} x={x_before} y={y_before}")

    # Move DOWN
    print("  Moving DOWN...")
    emu.input.keypad_add_key(keymask(Keys.KEY_DOWN))
    for _ in range(16):
        emu.cycle(with_joystick=False)
    emu.input.keypad_rm_key(keymask(Keys.KEY_DOWN))
    for _ in range(30):
        emu.cycle(with_joystick=False)

    x_after = read16(emu, general + 0x1288)
    y_after = read16(emu, general + 0x128C)
    map_after = read16(emu, general + 0x1280)
    print(f"  After DOWN: map={map_after} x={x_after} y={y_after}")
    print(f"  Delta: dx={x_after - x_before} dy={y_after - y_before}")

    # Move RIGHT
    print("  Moving RIGHT...")
    emu.input.keypad_add_key(keymask(Keys.KEY_RIGHT))
    for _ in range(16):
        emu.cycle(with_joystick=False)
    emu.input.keypad_rm_key(keymask(Keys.KEY_RIGHT))
    for _ in range(30):
        emu.cycle(with_joystick=False)

    x_after2 = read16(emu, general + 0x1288)
    y_after2 = read16(emu, general + 0x128C)
    print(f"  After RIGHT: map={map_after} x={x_after2} y={y_after2}")
    print(f"  Delta: dx={x_after2 - x_after} dy={y_after2 - y_after}")

    # ================================================================
    # Also check: what about the MKDasher base (old_base)?
    # old_base relationship to general
    # ================================================================
    print("\n" + "=" * 70)
    print("CHECKING old_base RELATIONSHIP")
    print("=" * 70)
    
    # If old_base is also related to general somehow:
    offset = general - old_base
    print(f"  General - old_base = 0x{offset:04X} ({offset})")
    # The MKDasher party offset from old_base is 0xD2AC
    # PKHeX party offset from General is 0xA0
    # If MKDasher uses old_base: old_base + 0xD2AC = General + 0xA0?
    # old_base + 0xD2AC = general + 0xA0 → general - old_base = 0xD2AC - 0xA0 = 0xD20C
    mk_party_addr = old_base + 0xD2AC
    pk_party_addr = general + 0xA0
    print(f"  MKDasher party: 0x{mk_party_addr:08X}")
    print(f"  PKHeX party: 0x{pk_party_addr:08X}")
    print(f"  Same? {mk_party_addr == pk_party_addr}")
    print(f"  Diff: {mk_party_addr - pk_party_addr}")
    
    # Verify offset
    if offset == 0xD20C:
        print("  ✓ Confirmed: General = old_base + 0xD20C")
        print("  ✓ MKDasher offsets = PKHeX offsets + 0xD20C from old_base")
    
    # ================================================================
    # DUMP first party Pokemon raw data (if any)
    # ================================================================
    if party_count > 0 and party_count <= 6:
        print(f"\n  Party Pokemon (slot 0) raw (first 32 bytes at General+0xA0):")
        party_raw = read_bytes(emu, general + 0xA0, 32)
        print(f"    [{' '.join(f'{b:02X}' for b in party_raw)}]")
    
    # ================================================================
    # Rival name  
    # ================================================================
    rival_raw = read_bytes(emu, general + 0x27E8, 16)
    print(f"\n  Rival name raw (General+0x27E8): [{' '.join(f'{b:02X}' for b in rival_raw)}]")
    rival_chars = []
    for i in range(8):
        c = read16(emu, general + 0x27E8 + i * 2)
        rival_chars.append(c)
        if c == 0xFFFF:
            break
    print(f"  Rival u16 values: [{', '.join(f'0x{c:04X}' for c in rival_chars)}]")

    emu.destroy()

if __name__ == "__main__":
    main()
