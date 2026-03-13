"""Test the dialogue text buffer scanner and reader.

Strategy:
1. Load golden savestate (which starts during dialogue)
2. Before clearing dialogue, try to find the text buffer
3. Read whatever text is in it
4. Test both encoding hypotheses
"""
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

# Don't clear dialogue yet — we want to find the buffer while text is on screen
# Just advance a few frames to stabilize
for _ in range(10):
    emu.cycle(with_joystick=False)

print("=" * 60)
print("Dialogue Buffer Investigation")
print("=" * 60)

# First, let's look at what's on screen by checking the screenshot
from harness.screenshot import ScreenshotPipeline
pipeline = ScreenshotPipeline(emu)
cap = pipeline.capture(encode=False)
pipeline.save(cap, "tests/output/dialogue_test")
print("Screenshots saved to tests/output/dialogue_test_top/bot.png")

# Try scanning for the String struct header (maxSize=0x0400)
print("\n--- Scanning for String struct headers (maxSize=0x0400) ---")

SCAN_START = 0x02200000
SCAN_END = 0x02800000
STRING_MAX_SIZE = 0x0400

candidates = []
for addr in range(SCAN_START, SCAN_END - 2056, 4):
    try:
        max_size = emu.memory.unsigned.read_short(addr)
        if max_size != STRING_MAX_SIZE:
            continue

        size = emu.memory.unsigned.read_short(addr + 2)
        if size == 0 or size > max_size:
            continue

        # Check integrity field — should be a consistent magic number
        integrity = emu.memory.unsigned.read_long(addr + 4)

        # Read first few charcodes
        first_chars = []
        for i in range(min(size, 8)):
            c = emu.memory.unsigned.read_short(addr + 8 + i * 2)
            first_chars.append(c)

        # Plausibility check: charcodes should be in a reasonable range
        # Gen 4 text chars are typically 0x0001-0x0200, with control codes > 0x2500
        plausible = any(0x0100 <= c <= 0x0200 for c in first_chars)

        if plausible:
            candidates.append((addr, size, integrity, first_chars))
    except Exception:
        continue

print(f"Found {len(candidates)} candidate String structs")
for addr, size, integrity, chars in candidates[:20]:
    char_str = " ".join(f"0x{c:04X}" for c in chars)
    print(f"  0x{addr:08X}: size={size}, integrity=0x{integrity:08X}, first: {char_str}")

# Try to decode the first few candidates using our save block encoding
print("\n--- Attempting decode with save block encoding (A=0x012B) ---")
from harness.data.chars import decode_gen4_string

for addr, size, integrity, chars in candidates[:10]:
    try:
        codes = []
        for i in range(min(size, 50)):
            c = emu.memory.unsigned.read_short(addr + 8 + i * 2)
            if c == 0xFFFF:
                break
            codes.append(c)
        text = decode_gen4_string(codes)
        if text and len(text) > 2:
            print(f"  0x{addr:08X}: \"{text[:80]}\"")
    except Exception:
        continue

# Try with Bulbapedia offset (+8)
print("\n--- Attempting decode with Bulbapedia encoding (A=0x0133, offset +8) ---")
for addr, size, integrity, chars in candidates[:10]:
    try:
        codes = []
        for i in range(min(size, 50)):
            c = emu.memory.unsigned.read_short(addr + 8 + i * 2)
            if c == 0xFFFF:
                break
            # Subtract 8 to convert from 0x0133 table to our 0x012B table
            c_adjusted = c - 8 if c >= 8 else c
            codes.append(c_adjusted)
        text = decode_gen4_string(codes)
        if text and len(text) > 2:
            print(f"  0x{addr:08X}: \"{text[:80]}\"")
    except Exception:
        continue

# Also scan for the specific text that should be on screen
# At the golden savestate, we're in the TV cutscene dialogue
# The text likely contains common words. Let's search for "the" or "you"
# encoded both ways
print("\n--- Scanning for known text patterns ---")

from harness.data.chars import encode_gen4_string

for word in ["the", "you", "AAAAAAA", "Twinleaf"]:
    encoded = encode_gen4_string(word)
    if not encoded:
        continue
    pattern = b""
    for code in encoded:
        pattern += code.to_bytes(2, "little")

    # Search in heap region
    found_count = 0
    for chunk_start in range(SCAN_START, SCAN_END - len(pattern), 0x10000):
        try:
            chunk = bytes([emu.memory.unsigned[chunk_start + i] for i in range(min(0x10000 + len(pattern), SCAN_END - chunk_start))])
            idx = 0
            while True:
                idx = chunk.find(pattern, idx)
                if idx < 0:
                    break
                found_count += 1
                abs_addr = chunk_start + idx
                if found_count <= 3:
                    # Try to read surrounding context
                    context_codes = []
                    for j in range(-4, 20):
                        ca = abs_addr + j * 2
                        if SCAN_START <= ca < SCAN_END:
                            context_codes.append(emu.memory.unsigned.read_short(ca))
                    context_text = decode_gen4_string(context_codes)
                    print(f"  Found '{word}' at 0x{abs_addr:08X}: \"{context_text[:60]}\"")
                idx += 2
        except Exception:
            continue

    if found_count > 0:
        print(f"  '{word}' total occurrences: {found_count}")
    else:
        print(f"  '{word}' not found with save block encoding")

        # Try with +8 offset
        encoded_alt = [c + 8 for c in encoded]
        pattern_alt = b""
        for code in encoded_alt:
            pattern_alt += code.to_bytes(2, "little")

        found_alt = 0
        for chunk_start in range(SCAN_START, SCAN_END - len(pattern_alt), 0x10000):
            try:
                chunk = bytes([emu.memory.unsigned[chunk_start + i] for i in range(min(0x10000 + len(pattern_alt), SCAN_END - chunk_start))])
                idx = chunk.find(pattern_alt)
                if idx >= 0:
                    found_alt += 1
                    abs_addr = chunk_start + idx
                    print(f"  Found '{word}' (Bulbapedia enc) at 0x{abs_addr:08X}")
            except Exception:
                continue

        if found_alt == 0:
            print(f"  '{word}' not found with either encoding")

print("\n" + "=" * 60)
print("Investigation complete.")
print("=" * 60)
