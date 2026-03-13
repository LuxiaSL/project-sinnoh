"""
Phase 1A Integration Test

Tests the full perception pipeline:
1. Memory reader → player state, coordinates, party
2. Screenshot pipeline → base64 encoded images
3. State formatter → structured text output
4. Gen 4 character decoding
"""

import os
os.environ["SDL_VIDEODRIVER"] = "dummy"

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from desmume.emulator import DeSmuME
from desmume.controls import keymask, Keys
from harness.memory import MemoryReader
from harness.screenshot import ScreenshotPipeline
from harness.formatter import format_state

SAVESTATE = Path(__file__).parent / "output" / "clean_intro" / "golden_gameplay.dst"
ROM_PATH = Path(__file__).parent.parent / "roms" / "Pokemon - Platinum Version (USA).nds"


def main():
    print("=" * 60)
    print("Phase 1A Integration Test")
    print("=" * 60)

    emu = DeSmuME()
    emu.open(str(ROM_PATH))
    emu.savestate.load_file(str(SAVESTATE))

    # Settle + clear dialogue
    for _ in range(60):
        emu.cycle(with_joystick=False)
    for _ in range(60):
        emu.input.keypad_add_key(keymask(Keys.KEY_A))
        for _ in range(6):
            emu.cycle(with_joystick=False)
        emu.input.keypad_rm_key(keymask(Keys.KEY_A))
        for _ in range(90):
            emu.cycle(with_joystick=False)

    errors: list[str] = []

    # === Test 1: Memory Reader ===
    print("\n[Test 1] Memory Reader")
    reader = MemoryReader(emu)
    state = reader.read_state()

    print(f"  Player: {state.player.name}")
    print(f"  Money: ¥{state.player.money}")
    print(f"  Map: {state.player.map_id} ({state.player.x}, {state.player.y})")
    print(f"  Party: {state.party.count}")

    if state.player.money != 3000:
        errors.append(f"Money: expected 3000, got {state.player.money}")
    if state.player.gender != 0:
        errors.append(f"Gender: expected 0, got {state.player.gender}")
    if state.player.map_id != 415:
        errors.append(f"Map ID: expected 415, got {state.player.map_id}")

    print("  ✓ Memory reader OK" if not errors else f"  ✗ {len(errors)} errors")

    # === Test 2: Screenshot Pipeline ===
    print("\n[Test 2] Screenshot Pipeline")
    pipeline = ScreenshotPipeline(emu, format="png")
    capture = pipeline.capture(encode=True)

    print(f"  Top screen shape: {capture.top.shape}")
    print(f"  Bottom screen shape: {capture.bottom.shape}")
    print(f"  Top base64 length: {len(capture.top_b64)} chars")
    print(f"  Bottom base64 length: {len(capture.bottom_b64)} chars")
    print(f"  Media type: {pipeline.media_type}")

    if capture.top.shape != (192, 256, 3):
        errors.append(f"Top shape wrong: {capture.top.shape}")
    if capture.bottom.shape != (192, 256, 3):
        errors.append(f"Bottom shape wrong: {capture.bottom.shape}")
    if len(capture.top_b64) < 100:
        errors.append(f"Top base64 too short: {len(capture.top_b64)}")
    if len(capture.bottom_b64) < 100:
        errors.append(f"Bottom base64 too short: {len(capture.bottom_b64)}")

    # Test JPEG format too
    jpeg_pipeline = ScreenshotPipeline(emu, format="jpeg", jpeg_quality=85)
    jpeg_capture = jpeg_pipeline.capture(encode=True)
    print(f"  JPEG top base64 length: {len(jpeg_capture.top_b64)} chars")
    print(f"  PNG/JPEG size ratio: {len(capture.top_b64) / len(jpeg_capture.top_b64):.1f}x")

    print("  ✓ Screenshot pipeline OK")

    # === Test 3: State Formatter ===
    print("\n[Test 3] State Formatter")
    formatted = format_state(state, novelty_flags=["First visit to this area"])
    print("  --- Formatted output ---")
    for line in formatted.split("\n"):
        print(f"  {line}")
    print("  --- End ---")

    if "GAME STATE" not in formatted:
        errors.append("Formatter missing header")
    if "3,000" in formatted or "3000" in formatted:
        pass  # money present
    else:
        errors.append("Formatter missing money")

    print("  ✓ State formatter OK")

    # === Test 4: Movement tracking ===
    print("\n[Test 4] Position tracking across movement")
    positions: list[tuple[int, int]] = [(state.player.x, state.player.y)]

    for direction, name in [(Keys.KEY_DOWN, "DOWN"), (Keys.KEY_RIGHT, "RIGHT")]:
        emu.input.keypad_add_key(keymask(direction))
        for _ in range(16):
            emu.cycle(with_joystick=False)
        emu.input.keypad_rm_key(keymask(direction))
        for _ in range(30):
            emu.cycle(with_joystick=False)

        new_state = reader.read_state()
        positions.append((new_state.player.x, new_state.player.y))
        print(f"  After {name}: ({new_state.player.x}, {new_state.player.y})")

    # DOWN should increase Y
    if positions[1][1] <= positions[0][1]:
        errors.append(f"DOWN didn't increase Y: {positions[0]} → {positions[1]}")

    print("  ✓ Position tracking OK")

    # === Test 5: Gen 4 Character Encoding ===
    print("\n[Test 5] Gen 4 character encoding")
    from harness.data.chars import decode_gen4_string, encode_gen4_string

    # Test decode
    test_codes = [0x012B, 0x012B, 0x012B, 0xFFFF]  # "AAA"
    decoded = decode_gen4_string(test_codes)
    print(f"  Decode [0x012B, 0x012B, 0x012B, 0xFFFF] = '{decoded}'")
    if decoded != "AAA":
        errors.append(f"Decode failed: expected 'AAA', got '{decoded}'")

    # Test encode
    encoded = encode_gen4_string("HELLO", max_len=8)
    decoded_back = decode_gen4_string(encoded)
    print(f"  Encode 'HELLO' → decode = '{decoded_back}'")
    if decoded_back != "HELLO":
        errors.append(f"Round-trip failed: expected 'HELLO', got '{decoded_back}'")

    # Test player name from memory
    print(f"  Player name from RAM: '{state.player.name}'")
    if len(state.player.name) > 0:
        print(f"  ✓ Name reading works")
    else:
        print(f"  (Name empty — normal before first in-game save)")

    print("  ✓ Character encoding OK")

    # === Test 6: Lookup tables ===
    print("\n[Test 6] Lookup tables")
    from harness.data.species import SPECIES
    from harness.data.moves import MOVES
    from harness.data.items import ITEMS

    print(f"  Species: {len(SPECIES)} (expected 493)")
    print(f"  Moves: {len(MOVES)} (expected 467)")
    print(f"  Items: {len(ITEMS)} (expected 445+)")

    # Spot checks
    assert SPECIES[387] == ("Turtwig", "Grass", None), f"Turtwig wrong: {SPECIES[387]}"
    assert SPECIES[25][0] == "Pikachu", f"Pikachu wrong: {SPECIES[25]}"
    assert MOVES[33][0] == "Tackle", f"Tackle wrong: {MOVES[33]}"

    print("  ✓ Lookup tables OK")

    # === Results ===
    print("\n" + "=" * 60)
    if errors:
        print(f"ISSUES ({len(errors)}):")
        for e in errors:
            print(f"  ✗ {e}")
    else:
        print("ALL PHASE 1A TESTS PASSED ✓")
    print("=" * 60)

    emu.destroy()


if __name__ == "__main__":
    main()
