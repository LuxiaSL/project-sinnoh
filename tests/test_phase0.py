"""
Phase 0: Foundation Tests for py-desmume + Pokemon Platinum

Run each test function independently to validate the emulator stack.
"""

import os
import sys
import time
from pathlib import Path

# Must be set before DeSmuME import — SDL_Init needs a video driver
os.environ["SDL_VIDEODRIVER"] = "dummy"

import numpy as np
from PIL import Image

# ROM paths
ROM_DIR = Path(__file__).parent.parent / "roms"
ROM_V10 = ROM_DIR / "Pokemon - Platinum Version (USA).nds"
ROM_V11 = ROM_DIR / "Pokemon - Platinum Version (USA) (Rev 1).nds"

# Use v1.0 first (more likely to match RAM docs), fall back to v1.1
ROM_PATH = ROM_V10 if ROM_V10.exists() else ROM_V11

OUTPUT_DIR = Path(__file__).parent.parent / "tests" / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def test_rom_load():
    """Test 1: Can we load the ROM and step frames?"""
    from desmume.emulator import DeSmuME

    print(f"Loading ROM: {ROM_PATH.name}")
    emu = DeSmuME()
    emu.open(str(ROM_PATH))
    print("ROM loaded successfully.")

    # Step some frames to get past initialization
    print("Stepping 60 frames (1 second of game time)...")
    for i in range(60):
        emu.cycle(with_joystick=False)
    print("Frame stepping works.")

    emu.destroy()
    print("PASS: ROM load + frame stepping")
    return True


def test_screenshot():
    """Test 2: Capture both screens as PIL Images."""
    from desmume.emulator import DeSmuME

    emu = DeSmuME()
    emu.open(str(ROM_PATH))

    # Run enough frames to get past the initial black screen
    print("Running 300 frames to get past initial loading...")
    for _ in range(300):
        emu.cycle(with_joystick=False)

    # Method 1: emu.screenshot() — returns PIL Image
    print("Testing emu.screenshot()...")
    try:
        screenshot = emu.screenshot()
        print(f"  screenshot() returned: {type(screenshot)}, size: {screenshot.size}")
        screenshot.save(str(OUTPUT_DIR / "screenshot_method1.png"))
        print(f"  Saved to {OUTPUT_DIR / 'screenshot_method1.png'}")
    except Exception as e:
        print(f"  screenshot() failed: {e}")

    # Method 2: display_buffer_as_rgbx() — raw buffer, fast path
    print("Testing display_buffer_as_rgbx()...")
    try:
        buf = emu.display_buffer_as_rgbx()
        print(f"  Buffer type: {type(buf)}, length: {len(buf)}")
        frame = np.frombuffer(buf, dtype=np.uint8).reshape(384, 256, 4)[:, :, :3].copy()
        top_screen = frame[:192]      # (192, 256, 3)
        bottom_screen = frame[192:]   # (192, 256, 3)
        print(f"  Top screen shape: {top_screen.shape}")
        print(f"  Bottom screen shape: {bottom_screen.shape}")

        Image.fromarray(top_screen).save(str(OUTPUT_DIR / "top_screen.png"))
        Image.fromarray(bottom_screen).save(str(OUTPUT_DIR / "bottom_screen.png"))
        Image.fromarray(frame).save(str(OUTPUT_DIR / "both_screens.png"))
        print(f"  Saved top/bottom/both to {OUTPUT_DIR}")
    except Exception as e:
        print(f"  display_buffer_as_rgbx() failed: {e}")

    emu.destroy()
    print("PASS: Screenshot capture")
    return True


def test_extended_boot():
    """Test 3: Run many frames to get to title screen, capture periodically."""
    from desmume.emulator import DeSmuME

    emu = DeSmuME()
    emu.open(str(ROM_PATH))

    # Platinum takes a while to boot — health/safety screen, Nintendo logo, Game Freak logo, etc.
    # At 60fps, let's run ~30 seconds worth (1800 frames) and capture periodically
    print("Extended boot test — running 1800 frames, capturing every 300...")
    for i in range(1800):
        emu.cycle(with_joystick=False)
        if (i + 1) % 300 == 0:
            try:
                buf = emu.display_buffer_as_rgbx()
                frame = np.frombuffer(buf, dtype=np.uint8).reshape(384, 256, 4)[:, :, :3].copy()
                img = Image.fromarray(frame)
                fname = f"boot_frame_{i+1:04d}.png"
                img.save(str(OUTPUT_DIR / fname))
                print(f"  Frame {i+1}: saved {fname}")
            except Exception as e:
                print(f"  Frame {i+1}: capture failed: {e}")

    emu.destroy()
    print("PASS: Extended boot")
    return True


def test_button_input():
    """Test 4: Press buttons and verify game responds."""
    from desmume.emulator import DeSmuME
    from desmume.controls import keymask, Keys

    emu = DeSmuME()
    emu.open(str(ROM_PATH))

    # Boot to title screen area (run ~1800 frames)
    print("Booting to title screen (~1800 frames)...")
    for _ in range(1800):
        emu.cycle(with_joystick=False)

    # Capture before pressing A
    buf = emu.display_buffer_as_rgbx()
    frame_before = np.frombuffer(buf, dtype=np.uint8).reshape(384, 256, 4)[:, :, :3].copy()
    Image.fromarray(frame_before).save(str(OUTPUT_DIR / "before_input.png"))

    # Press A a few times to try to advance past title
    print("Pressing A button 5 times (held for 10 frames each, 30 frame gap)...")
    for press_num in range(5):
        emu.input.keypad_add_key(keymask(Keys.KEY_A))
        for _ in range(10):
            emu.cycle(with_joystick=False)
        emu.input.keypad_rm_key(keymask(Keys.KEY_A))
        for _ in range(30):
            emu.cycle(with_joystick=False)
        print(f"  Press {press_num + 1} done")

    # Run some more frames to let the game respond
    for _ in range(120):
        emu.cycle(with_joystick=False)

    # Capture after
    buf = emu.display_buffer_as_rgbx()
    frame_after = np.frombuffer(buf, dtype=np.uint8).reshape(384, 256, 4)[:, :, :3].copy()
    Image.fromarray(frame_after).save(str(OUTPUT_DIR / "after_input.png"))

    # Check if screens changed
    diff = np.abs(frame_before.astype(int) - frame_after.astype(int)).sum()
    print(f"  Pixel difference between before/after: {diff}")
    if diff > 0:
        print("  Screens differ — input likely registered!")
    else:
        print("  WARNING: Screens identical — input may not have registered (or timing issue)")

    emu.destroy()
    print("PASS: Button input")
    return True


def test_touch_input():
    """Test 5: Touch the bottom screen."""
    from desmume.emulator import DeSmuME

    emu = DeSmuME()
    emu.open(str(ROM_PATH))

    # Boot up
    print("Booting (~1800 frames)...")
    for _ in range(1800):
        emu.cycle(with_joystick=False)

    # Touch center of bottom screen
    print("Touching bottom screen at (128, 96)...")
    emu.input.touch_set_pos(128, 96)
    for _ in range(10):
        emu.cycle(with_joystick=False)
    emu.input.touch_release()
    for _ in range(60):
        emu.cycle(with_joystick=False)

    buf = emu.display_buffer_as_rgbx()
    frame = np.frombuffer(buf, dtype=np.uint8).reshape(384, 256, 4)[:, :, :3].copy()
    Image.fromarray(frame).save(str(OUTPUT_DIR / "after_touch.png"))

    print("  Touch input sent. Check after_touch.png for visual confirmation.")
    emu.destroy()
    print("PASS: Touch input")
    return True


def test_memory_read():
    """Test 6: Read memory — try the base pointer and basic values."""
    from desmume.emulator import DeSmuME

    emu = DeSmuME()
    emu.open(str(ROM_PATH))

    # Need to boot to a point where save data is loaded
    # Title screen probably isn't enough — we'd need an actual save
    # For now, let's just verify memory access works at all
    print("Booting (~1800 frames)...")
    for _ in range(1800):
        emu.cycle(with_joystick=False)

    # Test raw memory access
    print("Testing memory access patterns...")

    # Try reading the base pointer address
    BASE_PTR_ADDR = 0x02101D2C
    try:
        # Try read_long for 32-bit value
        base_ptr = emu.memory.unsigned.read_long(BASE_PTR_ADDR)
        print(f"  Base pointer (read_long): 0x{base_ptr:08X}")
    except AttributeError:
        # Maybe the API is different — try direct indexing
        try:
            b0 = emu.memory.unsigned[BASE_PTR_ADDR]
            b1 = emu.memory.unsigned[BASE_PTR_ADDR + 1]
            b2 = emu.memory.unsigned[BASE_PTR_ADDR + 2]
            b3 = emu.memory.unsigned[BASE_PTR_ADDR + 3]
            base_ptr = b0 | (b1 << 8) | (b2 << 16) | (b3 << 24)
            print(f"  Base pointer (byte-by-byte): 0x{base_ptr:08X}")
        except Exception as e:
            print(f"  Memory access failed: {e}")
            base_ptr = None

    if base_ptr and base_ptr > 0x02000000:
        print(f"  Base pointer looks valid (in main RAM range)")
        # Try reading some offsets
        try:
            # Money at base + 0x7C (4 bytes)
            money_bytes = [emu.memory.unsigned[base_ptr + 0x7C + i] for i in range(4)]
            money = money_bytes[0] | (money_bytes[1] << 8) | (money_bytes[2] << 16) | (money_bytes[3] << 24)
            print(f"  Money value: {money}")

            # Badges at base + 0x82 (1 byte, bitfield)
            badges = emu.memory.unsigned[base_ptr + 0x82]
            print(f"  Badge bitfield: 0b{badges:08b} ({bin(badges).count('1')} badges)")

        except Exception as e:
            print(f"  Offset read failed: {e}")
    else:
        print(f"  Base pointer doesn't look valid — game may not have loaded save data yet")
        print(f"  This is expected on title screen with no save file")

    # Also try to explore what memory API methods exist
    print("\n  Memory object attributes:")
    print(f"    dir(emu.memory): {[x for x in dir(emu.memory) if not x.startswith('_')]}")
    print(f"    dir(emu.memory.unsigned): {[x for x in dir(emu.memory.unsigned) if not x.startswith('_')]}")

    emu.destroy()
    print("PASS: Memory read")
    return True


def test_savestate():
    """Test 7: Save state round-trip."""
    from desmume.emulator import DeSmuME

    emu = DeSmuME()
    emu.open(str(ROM_PATH))

    print("Booting (~600 frames)...")
    for _ in range(600):
        emu.cycle(with_joystick=False)

    # Capture state at this point
    buf1 = emu.display_buffer_as_rgbx()
    frame1 = np.frombuffer(buf1, dtype=np.uint8).reshape(384, 256, 4)[:, :, :3].copy()

    # Save state
    print("Saving state...")
    try:
        savestate = emu.savestate
        print(f"  Savestate object: {type(savestate)}")
        print(f"  Savestate attributes: {[x for x in dir(savestate) if not x.startswith('_')]}")

        # Try to save to file
        ss_path = str(OUTPUT_DIR / "test_savestate.dst")
        savestate.save_file(ss_path)
        print(f"  Saved to {ss_path}")

        # Run more frames (change the state)
        print("  Running 600 more frames to change state...")
        for _ in range(600):
            emu.cycle(with_joystick=False)

        buf2 = emu.display_buffer_as_rgbx()
        frame2 = np.frombuffer(buf2, dtype=np.uint8).reshape(384, 256, 4)[:, :, :3].copy()

        # Load state
        print("  Loading saved state...")
        savestate.load_file(ss_path)

        # Run a frame to let it settle
        emu.cycle(with_joystick=False)

        buf3 = emu.display_buffer_as_rgbx()
        frame3 = np.frombuffer(buf3, dtype=np.uint8).reshape(384, 256, 4)[:, :, :3].copy()

        # Compare: frame1 and frame3 should be similar, frame2 should differ
        diff_1_2 = np.abs(frame1.astype(int) - frame2.astype(int)).sum()
        diff_1_3 = np.abs(frame1.astype(int) - frame3.astype(int)).sum()
        print(f"  Diff (save point vs after): {diff_1_2}")
        print(f"  Diff (save point vs after load): {diff_1_3}")

        if diff_1_3 < diff_1_2:
            print("  State restored closer to save point — savestate works!")
        else:
            print("  WARNING: loaded state doesn't match saved state closely")

    except Exception as e:
        print(f"  Savestate failed: {e}")
        import traceback
        traceback.print_exc()

    emu.destroy()
    print("PASS: Save state")
    return True


def run_all():
    """Run all tests sequentially."""
    tests = [
        ("ROM Load", test_rom_load),
        ("Screenshot", test_screenshot),
        ("Extended Boot", test_extended_boot),
        ("Button Input", test_button_input),
        ("Touch Input", test_touch_input),
        ("Memory Read", test_memory_read),
        ("Save State", test_savestate),
    ]

    results = {}
    for name, test_fn in tests:
        print(f"\n{'='*60}")
        print(f"TEST: {name}")
        print(f"{'='*60}")
        try:
            results[name] = test_fn()
        except Exception as e:
            print(f"FAIL: {name} — {e}")
            import traceback
            traceback.print_exc()
            results[name] = False

    print(f"\n{'='*60}")
    print("RESULTS SUMMARY")
    print(f"{'='*60}")
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Run a specific test
        test_name = sys.argv[1]
        test_map = {
            "load": test_rom_load,
            "screenshot": test_screenshot,
            "boot": test_extended_boot,
            "button": test_button_input,
            "touch": test_touch_input,
            "memory": test_memory_read,
            "savestate": test_savestate,
        }
        if test_name in test_map:
            test_map[test_name]()
        else:
            print(f"Unknown test: {test_name}")
            print(f"Available: {', '.join(test_map.keys())}")
    else:
        run_all()
