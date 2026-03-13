"""
Try to get the player actually moving, then find coordinates.
First clear any dialogue, then do a wider RAM scan.
"""

import os
os.environ["SDL_VIDEODRIVER"] = "dummy"

import numpy as np
from pathlib import Path
from PIL import Image
from desmume.emulator import DeSmuME
from desmume.controls import keymask, Keys

SAVESTATE = Path(__file__).parent / "output" / "clean_intro" / "golden_gameplay.dst"
ROM_PATH = Path(__file__).parent.parent / "roms" / "Pokemon - Platinum Version (USA).nds"
OUT = Path(__file__).parent / "output" / "coord_search"
OUT.mkdir(parents=True, exist_ok=True)

def read32(emu, addr):
    return emu.memory.unsigned.read_long(addr)
def read8(emu, addr):
    return emu.memory.unsigned[addr]

def capture(emu, label):
    buf = emu.display_buffer_as_rgbx()
    frame = np.frombuffer(buf, dtype=np.uint8).reshape(384, 256, 4)[:, :, :3].copy()
    Image.fromarray(frame[:192]).save(str(OUT / f"{label}_top.png"))
    Image.fromarray(frame[192:]).save(str(OUT / f"{label}_bot.png"))
    print(f"  Captured: {label}")

def press(emu, key, hold=6, wait=30):
    emu.input.keypad_add_key(keymask(key))
    for _ in range(hold):
        emu.cycle(with_joystick=False)
    emu.input.keypad_rm_key(keymask(key))
    for _ in range(wait):
        emu.cycle(with_joystick=False)

def wait(emu, frames):
    for _ in range(frames):
        emu.cycle(with_joystick=False)

def dump_wide(emu, base_addr, size):
    """Dump RAM region as dict of aligned 32-bit values."""
    result = {}
    for off in range(0, size, 4):
        result[base_addr + off] = read32(emu, base_addr + off)
    return result

def main():
    emu = DeSmuME()
    emu.open(str(ROM_PATH))
    emu.savestate.load_file(str(SAVESTATE))
    wait(emu, 30)

    alt_base = read32(emu, 0x02101D40)
    old_base = read32(emu, 0x02101D2C)
    print(f"Old base: 0x{old_base:08X}")
    print(f"Alt base: 0x{alt_base:08X}")

    # Check what's on screen
    capture(emu, "01_initial_state")

    # Clear any dialogue — press A a bunch
    print("\nClearing dialogue (20 A presses)...")
    for i in range(20):
        press(emu, Keys.KEY_A, hold=6, wait=60)
        if i % 5 == 4:
            capture(emu, f"02_clearing_{i+1}")

    # Wait and check
    wait(emu, 120)
    capture(emu, "03_after_clearing")

    # Try to move now
    print("\nAttempting to move DOWN...")
    press(emu, Keys.KEY_DOWN, hold=12, wait=30)
    capture(emu, "04_after_down")

    # Try a few more moves
    for i in range(5):
        press(emu, Keys.KEY_DOWN, hold=12, wait=30)
    capture(emu, "05_after_more_down")

    # Save this state — we should be freely walking now
    emu.savestate.save_file(str(OUT / "walking.dst"))
    print("\nSaved walking state.")

    # NOW do the coordinate diff
    print("\n" + "=" * 70)
    print("COORDINATE DIFF: scanning wider RAM region")
    print("=" * 70)

    # Scan MUCH wider: most of main RAM around the game data area
    # The coordinates could be ANYWHERE in 0x02000000-0x02FFFFFF
    # Let's focus on 0x02000000-0x02300000 (3MB) reading 32-bit aligned
    # That's too much for byte-by-byte. Let's be strategic.
    # 
    # Key regions to check:
    # 1. Around old_base (0x02271xxx)
    # 2. Around alt_base (0x0227Exxx)  
    # 3. Field overlay area (varies)
    # 4. Known coordinate breakpoints suggest code at 0x0205EA__, 
    #    which loads FROM somewhere into r0. The data is elsewhere.
    
    # Let's scan a focused but wider set of regions
    scan_regions = [
        ("old_base-0x1000:+0x16000", old_base - 0x1000, 0x16000),
        ("0x020D0000:+0x10000", 0x020D0000, 0x10000),
        ("0x020E0000:+0x10000", 0x020E0000, 0x10000),
        ("0x020F0000:+0x10000", 0x020F0000, 0x10000),
        ("0x02100000:+0x10000", 0x02100000, 0x10000),
    ]
    
    print("Taking snapshot before move...")
    before = {}
    for label, start, size in scan_regions:
        before.update(dump_wide(emu, start, size))
    
    # Move DOWN once
    print("Moving DOWN...")
    press(emu, Keys.KEY_DOWN, hold=12, wait=30)
    
    print("Taking snapshot after move...")
    after_down = {}
    for label, start, size in scan_regions:
        after_down.update(dump_wide(emu, start, size))
    
    # Find 32-bit values that changed
    down_changes = {}
    for addr in before:
        if before[addr] != after_down[addr]:
            down_changes[addr] = (before[addr], after_down[addr])
    
    print(f"\n32-bit values changed after DOWN: {len(down_changes)}")
    
    # Now move RIGHT
    print("Moving RIGHT...")
    before_right = dict(after_down)  # current state
    press(emu, Keys.KEY_RIGHT, hold=12, wait=30)
    
    after_right = {}
    for label, start, size in scan_regions:
        after_right.update(dump_wide(emu, start, size))
    
    right_changes = {}
    for addr in before_right:
        if before_right[addr] != after_right[addr]:
            right_changes[addr] = (before_right[addr], after_right[addr])
    
    print(f"32-bit values changed after RIGHT: {len(right_changes)}")
    
    # Addresses changed in BOTH movements are likely coordinate-related
    both = set(down_changes.keys()) & set(right_changes.keys())
    print(f"\nChanged in BOTH movements: {len(both)}")
    
    # Show details
    if both:
        for addr in sorted(both):
            d_old, d_new = down_changes[addr]
            r_old, r_new = right_changes[addr]
            print(f"  0x{addr:08X}:")
            print(f"    DOWN:  {d_old} → {d_new} (delta={d_new - d_old})")
            print(f"    RIGHT: {r_old} → {r_new} (delta={r_new - r_old})")
    
    # Also show DOWN-only changes with delta=1 (likely Y coordinate)
    print(f"\n  DOWN-only changes with small deltas:")
    for addr in sorted(down_changes.keys()):
        if addr not in both:
            old, new = down_changes[addr]
            delta = new - old
            if -10 <= delta <= 10 and delta != 0:
                print(f"    0x{addr:08X}: {old} → {new} (delta={delta})")
    
    # RIGHT-only changes with delta=1 (likely X coordinate)
    print(f"\n  RIGHT-only changes with small deltas:")
    for addr in sorted(right_changes.keys()):
        if addr not in both:
            old, new = right_changes[addr]
            delta = new - old
            if -10 <= delta <= 10 and delta != 0:
                print(f"    0x{addr:08X}: {old} → {new} (delta={delta})")

    emu.destroy()

if __name__ == "__main__":
    main()
