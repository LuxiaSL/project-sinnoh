"""
Find player name and decode Gen 4 character encoding.
Rival name uses 0x012B for 'A'. Gen 4 has a custom char table.
Player name at General+0x68 is zeros — might be stored elsewhere at runtime.
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

def main():
    emu = DeSmuME()
    emu.open(str(ROM_PATH))
    emu.savestate.load_file(str(SAVESTATE))
    for _ in range(30):
        emu.cycle(with_joystick=False)

    alt_base = read32(emu, 0x02101D40)
    general = alt_base + 0x14

    # ================================================================
    # The rival name uses Gen 4 encoding: 0x012B = 'A'
    # Gen 4 char table: uppercase letters start at 0x0121
    # A=0x0121? or 0x012B? Let's check.
    # The rival name is "AAAAAAA" (7 A's, from A-mashing).
    # 0x012B = 299 decimal. If A=0x012B, then B=0x012C, etc.
    # 
    # Actually, Gen 4 encoding is well-documented:
    # Standard Latin uppercase: A=0x0121, B=0x0122, ..., Z=0x013A
    # Wait, but the rival name shows 0x012B for 'A'. 
    # 0x012B - 0x0121 = 0x0A = 10. So 0x012B would be 'K'?
    # That doesn't match — unless the name isn't "AAAAAAA".
    #
    # Hmm. Let me reconsider. The actual Gen 4 character encoding:
    # From Bulbapedia, Gen IV character encoding:
    # A=0x012B seems wrong for standard docs. Let me just build
    # the mapping empirically from what we know.
    # 
    # The player mashed A on the keyboard, but the keyboard might
    # start on a different character. Looking at the screenshot,
    # the name was "AAAAAAA" — so each of these 0x012B chars IS 'A'.
    # So in THIS game's encoding, 'A' = 0x012B.
    # ================================================================

    # Let's search for the player name pattern (0x012B repeated)
    pattern = bytes([0x2B, 0x01] * 4)  # At least 4 'A's
    
    print("Searching for player name (0x012B pattern) in RAM...")
    for chunk_start in range(0x02000000, 0x02400000, 0x10000):
        try:
            chunk = bytes([emu.memory.unsigned[chunk_start + i] for i in range(0x10000)])
            idx = 0
            while True:
                idx = chunk.find(pattern, idx)
                if idx == -1:
                    break
                addr = chunk_start + idx
                # Read full potential name (up to 16 bytes = 8 chars)
                name_raw = read_bytes(emu, addr, 18)
                chars = []
                for i in range(9):
                    c = read16(emu, addr + i * 2)
                    if c == 0xFFFF:
                        break
                    chars.append(f"0x{c:04X}")
                offset_from_general = addr - general
                print(f"  0x{addr:08X} (General+0x{offset_from_general:04X}): "
                      f"[{' '.join(f'{b:02X}' for b in name_raw)}]")
                print(f"    chars: [{', '.join(chars)}]")
                idx += 2
        except:
            pass

    # ================================================================
    # Also: dump the General+0x68 area more carefully — is it truly zero?
    # And check if maybe the player name is at a different offset
    # relative to General
    # ================================================================
    print("\n=== General+0x00 to General+0xA0 dump (all trainer data) ===")
    for off in range(0x00, 0xA0, 16):
        raw = read_bytes(emu, general + off, 16)
        hex_str = ' '.join(f'{b:02X}' for b in raw)
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in raw)
        print(f"  General+0x{off:04X}: {hex_str}  {ascii_part}")

    # ================================================================
    # Check if player name is in a different save block or section
    # The "Trainer1" offset in PKHeX is 0x68, and name is at Trainer1+0
    # But maybe in the runtime RAM, the trainer name is stored in a 
    # separate runtime structure, not in the save block copy.
    # ================================================================
    
    # Let's check the ADVENTURE INFO block at General+0x00
    print("\n=== Adventure Info block (General+0x00) ===")
    adv_raw = read_bytes(emu, general, 0x68)
    for off in range(0, 0x68, 16):
        raw = adv_raw[off:off+16]
        hex_str = ' '.join(f'{b:02X}' for b in raw)
        print(f"  General+0x{off:04X}: {hex_str}")

    emu.destroy()

if __name__ == "__main__":
    main()
