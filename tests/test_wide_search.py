"""
Wide RAM search for player name + get to free movement + find coords.
"""

import os
os.environ["SDL_VIDEODRIVER"] = "dummy"

import struct
from pathlib import Path
from desmume.emulator import DeSmuME
from desmume.controls import keymask, Keys
import numpy as np
from PIL import Image

SAVESTATE = Path(__file__).parent / "output" / "clean_intro" / "golden_gameplay.dst"
ROM_PATH = Path(__file__).parent.parent / "roms" / "Pokemon - Platinum Version (USA).nds"
OUT = Path(__file__).parent / "output" / "coord_search"
OUT.mkdir(parents=True, exist_ok=True)

def read32(emu, addr):
    return emu.memory.unsigned.read_long(addr)
def read16(emu, addr):
    return emu.memory.unsigned.read_short(addr)
def read8(emu, addr):
    return emu.memory.unsigned[addr]

def capture(emu, label):
    buf = emu.display_buffer_as_rgbx()
    frame = np.frombuffer(buf, dtype=np.uint8).reshape(384, 256, 4)[:, :, :3].copy()
    Image.fromarray(frame[:192]).save(str(OUT / f"{label}_top.png"))

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

def main():
    emu = DeSmuME()
    emu.open(str(ROM_PATH))
    emu.savestate.load_file(str(SAVESTATE))
    wait(emu, 30)

    alt_base = read32(emu, 0x02101D40)
    old_base = read32(emu, 0x02101D2C)

    # ================================================================
    # STEP 1: Find player name "AAAAAAA" in all of main RAM
    # ================================================================
    print("=" * 70)
    print("STEP 1: Searching ALL main RAM for 'AAAAAAA' (Unicode)")
    print("=" * 70)
    
    # 'A' in Unicode = 0x0041. Pattern: 41 00 41 00 41 00 41 00 41 00 41 00 41 00
    pattern = bytes([0x41, 0x00] * 7)  # "AAAAAAA"
    
    # Read main RAM in chunks and search
    # Main RAM: 0x02000000 - 0x02FFFFFF (4MB in theory, usually ~3MB used)
    CHUNK_SIZE = 0x10000  # 64KB chunks
    found_addrs = []
    
    for chunk_start in range(0x02000000, 0x02400000, CHUNK_SIZE):
        try:
            chunk = bytes([emu.memory.unsigned[chunk_start + i] for i in range(CHUNK_SIZE)])
            # Search for pattern in this chunk
            idx = 0
            while True:
                idx = chunk.find(pattern, idx)
                if idx == -1:
                    break
                addr = chunk_start + idx
                found_addrs.append(addr)
                # Read more context
                name_bytes = bytes([emu.memory.unsigned[addr + i] for i in range(24)])
                hex_str = ' '.join(f'{b:02X}' for b in name_bytes)
                print(f"  FOUND at 0x{addr:08X}: [{hex_str}]")
                print(f"    Offset from old_base: 0x{addr - old_base:08X}")
                print(f"    Offset from alt_base: 0x{addr - alt_base:08X}")
                idx += 2
        except Exception as e:
            pass  # Some regions may not be readable
    
    print(f"\n  Total occurrences: {len(found_addrs)}")

    # For each found address, check what's nearby (TID, money, etc.)
    if found_addrs:
        print("\n  Checking nearby data for each occurrence:")
        for addr in found_addrs:
            # Name is 16 bytes (8 chars × 2 bytes), then:
            # If this is Trainer1 block: +0x10 = TID, +0x12 = SID, +0x14 = Money
            tid = read16(emu, addr + 0x10)
            sid = read16(emu, addr + 0x12)
            money = read32(emu, addr + 0x14)
            gender = read8(emu, addr + 0x18)
            badges = read8(emu, addr + 0x1A)
            print(f"    0x{addr:08X}: TID={tid} SID={sid} Money={money} "
                  f"Gender={gender} Badges={badges}")

    # ================================================================
    # STEP 2: Get to free movement — clear all rival dialogue
    # ================================================================
    print("\n" + "=" * 70)
    print("STEP 2: Clearing rival dialogue to reach free movement")
    print("=" * 70)
    
    for i in range(50):
        press(emu, Keys.KEY_A, hold=6, wait=90)
        if i % 10 == 9:
            capture(emu, f"clearing_{i+1}")
            print(f"  Pressed A {i+1} times...")

    wait(emu, 120)
    capture(emu, "after_all_clearing")

    # Try to move
    print("\n  Attempting movement...")
    press(emu, Keys.KEY_DOWN, hold=12, wait=60)
    capture(emu, "move_attempt_1")
    press(emu, Keys.KEY_DOWN, hold=12, wait=60)
    capture(emu, "move_attempt_2")
    press(emu, Keys.KEY_RIGHT, hold=12, wait=60)
    capture(emu, "move_attempt_3")

    # ================================================================
    # STEP 3: Now do the coordinate diff across ALL main RAM
    # ================================================================
    print("\n" + "=" * 70)
    print("STEP 3: Wide coordinate diff")
    print("=" * 70)
    
    # Save the current state for the diff
    emu.savestate.save_file(str(OUT / "pre_diff.dst"))
    
    # Take a snapshot of key regions (can't do ALL of RAM, too slow)
    # Focus on regions around the name addresses we found + broader areas
    scan_addrs = set()
    
    # Add regions around each name occurrence
    for name_addr in found_addrs:
        base_region = (name_addr & ~0xFFFF)
        for off in range(0, 0x20000, 4):
            scan_addrs.add(base_region + off)
    
    # Add broader scan regions
    for start in range(0x02000000, 0x02400000, 0x40000):
        for off in range(0, 0x40000, 4):
            scan_addrs.add(start + off)
    
    # Actually, this is too many addresses. Let me be smarter.
    # Just read 32-bit values across ALL main RAM (0x02000000-0x02400000)
    # at 4-byte alignment. That's 1M reads, might be slow but doable.
    
    print("  Snapshot before move (scanning 0x02000000-0x02300000)...")
    before = {}
    for addr in range(0x02000000, 0x02300000, 4):
        try:
            before[addr] = read32(emu, addr)
        except:
            pass
    
    print("  Moving DOWN...")
    press(emu, Keys.KEY_DOWN, hold=12, wait=60)
    
    print("  Snapshot after DOWN...")
    after_down = {}
    for addr in before:
        try:
            after_down[addr] = read32(emu, addr)
        except:
            pass
    
    # Find changes
    down_changes = {}
    for addr in before:
        if addr in after_down and before[addr] != after_down[addr]:
            down_changes[addr] = (before[addr], after_down[addr])
    
    print(f"  32-bit values changed after DOWN: {len(down_changes)}")
    
    # Show changes with small deltas (coordinate candidates)
    print("\n  Changes with delta in [-32, 32]:")
    for addr in sorted(down_changes):
        old, new = down_changes[addr]
        delta = new - old
        if abs(delta) <= 32:
            print(f"    0x{addr:08X}: {old} → {new} (delta={delta})")
    
    # Now RIGHT
    print("\n  Moving RIGHT...")
    before_right = dict(after_down)
    press(emu, Keys.KEY_RIGHT, hold=12, wait=60)
    
    after_right = {}
    for addr in before:
        try:
            after_right[addr] = read32(emu, addr)
        except:
            pass
    
    right_changes = {}
    for addr in before_right:
        if addr in after_right and before_right[addr] != after_right[addr]:
            right_changes[addr] = (before_right[addr], after_right[addr])
    
    print(f"  32-bit values changed after RIGHT: {len(right_changes)}")
    
    print("\n  Changes with delta in [-32, 32]:")
    for addr in sorted(right_changes):
        old, new = right_changes[addr]
        delta = new - old
        if abs(delta) <= 32:
            print(f"    0x{addr:08X}: {old} → {new} (delta={delta})")

    # DOWN-only addresses (Y coordinate candidates)
    down_only = set(down_changes.keys()) - set(right_changes.keys())
    right_only = set(right_changes.keys()) - set(down_changes.keys())
    both = set(down_changes.keys()) & set(right_changes.keys())
    
    print(f"\n  DOWN-only: {len(down_only)}, RIGHT-only: {len(right_only)}, BOTH: {len(both)}")
    
    print("\n  DOWN-only with small delta (Y candidates):")
    for addr in sorted(down_only):
        old, new = down_changes[addr]
        delta = new - old
        if abs(delta) <= 32:
            print(f"    0x{addr:08X}: {old} → {new} (delta={delta})")
    
    print("\n  RIGHT-only with small delta (X candidates):")
    for addr in sorted(right_only):
        old, new = right_changes[addr]
        delta = new - old
        if abs(delta) <= 32:
            print(f"    0x{addr:08X}: {old} → {new} (delta={delta})")

    # Save the movable state
    emu.savestate.save_file(str(OUT / "movable.dst"))
    print(f"\n  Saved movable state to {OUT / 'movable.dst'}")
    
    emu.destroy()

if __name__ == "__main__":
    main()
