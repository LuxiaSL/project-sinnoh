"""
Movement diff test: move the player and diff memory to find coordinate storage.
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

def dump_region(emu, start, size):
    """Dump a region of memory as a dict of addr -> byte value."""
    return {start + i: emu.memory.unsigned[start + i] for i in range(size)}

def diff_dumps(before, after):
    """Find addresses where values changed."""
    changes = []
    for addr in before:
        if before[addr] != after[addr]:
            changes.append((addr, before[addr], after[addr]))
    return changes

def main():
    emu = DeSmuME()
    emu.open(str(ROM_PATH))
    emu.savestate.load_file(str(SAVESTATE))
    for _ in range(60):
        emu.cycle(with_joystick=False)

    old_base = read32(emu, 0x02101D2C)
    alt_base = read32(emu, 0x02101D40)
    print(f"Old base: 0x{old_base:08X}")
    print(f"Alt base: 0x{alt_base:08X}")

    # Dump key regions BEFORE movement
    print("\nDumping memory before movement...")
    
    # Regions to scan: around both base pointers
    # Focus on regions where coordinates might live
    regions = [
        ("old_base+0x0000:0x0400", old_base, 0x400),
        ("old_base+0xD200:0xD400", old_base + 0xD200, 0x200),
        ("alt_base+0x0000:0x0400", alt_base, 0x400),
        # Also check some fixed addresses that might hold coords
        ("0x020F0000:0x020F0200", 0x020F0000, 0x200),
    ]
    
    before_dumps = {}
    for label, start, size in regions:
        before_dumps[label] = dump_region(emu, start, size)
    
    # Also dump a wider region around alt_base for coordinate scanning
    # Coordinates in Platinum should be 32-bit values, likely small numbers
    wide_before = dump_region(emu, alt_base - 0x100, 0x2000)
    
    # Move the player DOWN
    print("Moving player DOWN (holding 12 frames)...")
    emu.input.keypad_add_key(keymask(Keys.KEY_DOWN))
    for _ in range(12):
        emu.cycle(with_joystick=False)
    emu.input.keypad_rm_key(keymask(Keys.KEY_DOWN))
    for _ in range(30):
        emu.cycle(with_joystick=False)
    
    # Dump AFTER movement
    print("Dumping memory after movement...")
    after_dumps = {}
    for label, start, size in regions:
        after_dumps[label] = dump_region(emu, start, size)
    
    wide_after = dump_region(emu, alt_base - 0x100, 0x2000)
    
    # Find changes
    print("\n" + "=" * 70)
    print("CHANGES DETECTED")
    print("=" * 70)
    
    for label in before_dumps:
        changes = diff_dumps(before_dumps[label], after_dumps[label])
        if changes:
            print(f"\n  [{label}] — {len(changes)} bytes changed:")
            for addr, old, new in changes[:50]:  # limit output
                print(f"    0x{addr:08X}: {old:3d} (0x{old:02X}) → {new:3d} (0x{new:02X})")

    # Now look specifically for coordinate-like changes in the wide region
    print(f"\n  [Wide scan: alt_base-0x100 to alt_base+0x1F00] changes:")
    wide_changes = diff_dumps(wide_before, wide_after)
    
    # Filter for likely coordinate changes: look for 32-bit values that 
    # changed by exactly 1 (moved one tile down = Y increased by 1?)
    # Or look for any 32-bit value that changed
    print(f"  Total changed bytes: {len(wide_changes)}")
    
    if wide_changes:
        # Group changes by 4-byte alignment to find 32-bit changes
        aligned_addrs = set()
        for addr, old, new in wide_changes:
            aligned_addrs.add(addr & ~3)
        
        print(f"\n  32-bit values that changed:")
        for aligned_addr in sorted(aligned_addrs):
            # Read the 32-bit value before and after
            old_val = 0
            new_val = 0
            for i in range(4):
                a = aligned_addr + i
                if a in wide_before:
                    old_val |= wide_before[a] << (i * 8)
                if a in wide_after:
                    new_val |= wide_after[a] << (i * 8)
            
            offset_from_alt = aligned_addr - alt_base
            offset_from_old = aligned_addr - old_base
            
            if old_val != new_val:
                print(f"    0x{aligned_addr:08X} (alt+0x{offset_from_alt:04X}, old+0x{offset_from_old:04X}): "
                      f"{old_val} → {new_val} (delta={new_val - old_val})")

    # ================================================================
    # Now let's try moving RIGHT and see what changes
    # ================================================================
    print("\n" + "=" * 70)
    print("SECOND MOVEMENT: RIGHT")
    print("=" * 70)
    
    before2 = dump_region(emu, alt_base - 0x100, 0x2000)
    
    emu.input.keypad_add_key(keymask(Keys.KEY_RIGHT))
    for _ in range(12):
        emu.cycle(with_joystick=False)
    emu.input.keypad_rm_key(keymask(Keys.KEY_RIGHT))
    for _ in range(30):
        emu.cycle(with_joystick=False)
    
    after2 = dump_region(emu, alt_base - 0x100, 0x2000)
    
    changes2 = diff_dumps(before2, after2)
    if changes2:
        aligned_addrs2 = set()
        for addr, old, new in changes2:
            aligned_addrs2.add(addr & ~3)
        
        print(f"  32-bit values that changed:")
        for aligned_addr in sorted(aligned_addrs2):
            old_val = 0
            new_val = 0
            for i in range(4):
                a = aligned_addr + i
                if a in before2:
                    old_val |= before2[a] << (i * 8)
                if a in after2:
                    new_val |= after2[a] << (i * 8)
            
            offset_from_alt = aligned_addr - alt_base
            offset_from_old = aligned_addr - old_base
            
            if old_val != new_val:
                print(f"    0x{aligned_addr:08X} (alt+0x{offset_from_alt:04X}, old+0x{offset_from_old:04X}): "
                      f"{old_val} → {new_val} (delta={new_val - old_val})")

    # Check if any addresses changed in BOTH movements
    if wide_changes and changes2:
        addrs1 = {addr for addr, _, _ in wide_changes}
        addrs2 = {addr for addr, _, _ in changes2}
        common = addrs1 & addrs2
        if common:
            print(f"\n  Addresses that changed in BOTH movements ({len(common)}):")
            for addr in sorted(common):
                print(f"    0x{addr:08X} (alt+0x{addr - alt_base:04X})")

    emu.destroy()

if __name__ == "__main__":
    main()
