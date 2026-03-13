"""Deeper investigation of the dialogue buffers found."""
import os
os.environ["SDL_VIDEODRIVER"] = "dummy"

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from desmume.emulator import DeSmuME
from desmume.controls import keymask, Keys

rom_path = Path(__file__).parent.parent / "roms" / "Pokemon - Platinum Version (USA).nds"
savestate_path = Path(__file__).parent / "output" / "clean_intro" / "golden_gameplay.dst"

emu = DeSmuME()
emu.open(str(rom_path))
emu.savestate.load_file(str(savestate_path))

for _ in range(10):
    emu.cycle(with_joystick=False)

print("=" * 60)
print("Dialogue Buffer Deep Investigation")
print("=" * 60)

# We found two promising buffers:
# 0x022A5A30: "All right AAAAAAA the time has come Your very..."
# 0x022E1C2C: "Pokemon are by our side always I hope..."
#
# Both use save block encoding (A=0x012B)
# The unknown code 0x01DE appears between words - likely SPACE

from harness.data.chars import decode_gen4_string, TERMINATOR

# Dump the full content of both buffers
for buf_addr in [0x022A5A30, 0x022E1C2C]:
    print(f"\n--- Buffer at 0x{buf_addr:08X} ---")

    # Read header
    max_size = emu.memory.unsigned.read_short(buf_addr)
    size = emu.memory.unsigned.read_short(buf_addr + 2)
    integrity = emu.memory.unsigned.read_long(buf_addr + 4)
    print(f"  maxSize: 0x{max_size:04X} ({max_size})")
    print(f"  size: {size}")
    print(f"  integrity: 0x{integrity:08X}")

    # Read all charcodes
    codes = []
    for i in range(min(size, 200)):
        c = emu.memory.unsigned.read_short(buf_addr + 8 + i * 2)
        codes.append(c)
        if c == TERMINATOR:
            break

    # Print raw codes
    print(f"  Raw codes ({len(codes)}):")
    for i in range(0, len(codes), 16):
        chunk = codes[i:i+16]
        hex_str = " ".join(f"{c:04X}" for c in chunk)
        print(f"    {hex_str}")

    # Decode with space handling
    # 0x01DE is probably space - let's check the PKHeX char table
    text_parts = []
    for c in codes:
        if c == TERMINATOR:
            break
        if c == 0x01DE:
            text_parts.append(" ")
        elif c == 0x25BC:  # Clear screen
            text_parts.append("\n[CLEAR]\n")
        elif c == 0x25BD:  # Scroll
            text_parts.append("\n[SCROLL]\n")
        elif c == 0xE000:  # Newline / line break
            text_parts.append("\n")
        elif c == 0xFFFE:  # Format placeholder
            text_parts.append("[VAR]")
        else:
            # Try to decode using our table
            decoded = decode_gen4_string([c])
            if decoded and decoded != f"?{c:04X}":
                text_parts.append(decoded)
            else:
                text_parts.append(f"[{c:04X}]")

    full_text = "".join(text_parts)
    print(f"  Decoded text:")
    for line in full_text.split("\n"):
        if line.strip():
            print(f"    {line.strip()}")

# Check what code 0x01DE is in PKHeX's table
print("\n--- Character code investigation ---")
print("  0x01DE = possibly space (appears between all words)")
print("  0xE000 = newline (confirmed from pret)")
print("  0x25BC = clear screen")
print("  0x25BD = scroll up")

# Let's also check nearby unknown codes
special_codes = [0x01CD, 0x01CE, 0x01CF, 0x01D0, 0x01D1, 0x01D2,
                 0x01D3, 0x01D4, 0x01D5, 0x01D6, 0x01D7, 0x01D8,
                 0x01D9, 0x01DA, 0x01DB, 0x01DC, 0x01DD, 0x01DE,
                 0x01DF, 0x01E0, 0x01E1, 0x01E2, 0x01E3, 0x01E4,
                 0x01E5, 0x01E6, 0x01E7, 0x01E8, 0x01E9]
print("\n  Codes near 0x01DE:")
for c in special_codes:
    decoded = decode_gen4_string([c])
    print(f"    0x{c:04X} = '{decoded}'")

# Count how many of these buffers match the integrity value
integrity_0 = 0xB6F8D2ED  # From first buffer
print(f"\n--- Buffers with integrity=0x{integrity_0:08X} ---")
count = 0
for addr in range(0x02200000, 0x02800000, 4):
    try:
        if emu.memory.unsigned.read_long(addr + 4) == integrity_0:
            ms = emu.memory.unsigned.read_short(addr)
            s = emu.memory.unsigned.read_short(addr + 2)
            if ms == 0x0400 and 0 < s <= 0x0400:
                count += 1
                first = emu.memory.unsigned.read_short(addr + 8)
                print(f"  0x{addr:08X}: size={s}, first=0x{first:04X}")
    except Exception:
        continue
print(f"  Total: {count}")
