"""Quick investigation of the battle indicator address."""
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

# Clear dialogue first
for _ in range(60):
    emu.input.keypad_add_key(keymask(Keys.KEY_A))
    emu.cycle(with_joystick=False)
emu.input.keypad_rm_key(keymask(Keys.KEY_A))
for _ in range(30):
    emu.cycle(with_joystick=False)

# Check battle indicator at various sizes
addr = 0x021D18F2
val_u8 = emu.memory.unsigned[addr]
val_u16 = emu.memory.unsigned.read_short(addr)
val_u32 = emu.memory.unsigned.read_long(addr)

print(f"Battle indicator at 0x{addr:08X}:")
print(f"  u8:  {val_u8} (0x{val_u8:02X})")
print(f"  u16: {val_u16} (0x{val_u16:04X})")
print(f"  u32: {val_u32} (0x{val_u32:08X})")

# Check nearby bytes
print(f"\nNearby bytes:")
for i in range(-4, 8):
    a = addr + i
    v = emu.memory.unsigned[a]
    print(f"  0x{a:08X}: {v} (0x{v:02X})")

# Check the trainer anchor pointer's battle-related offsets
anchor_ptr = 0x021C0794
anchor = emu.memory.unsigned.read_long(anchor_ptr)
print(f"\nTrainer anchor: 0x{anchor:08X}")

# Try reading facing direction to make sure anchor is valid
if 0x02000000 <= anchor <= 0x02FFFFFF:
    facing = emu.memory.unsigned.read_long(anchor + 0x238A4)
    print(f"  Facing direction (anchor+0x238A4): {facing}")

# What about checking if battle overlay is loaded?
# Let's look at some other potential battle flags
potential_flags = [
    (0x021D18F0, "0x021D18F0"),
    (0x021D18F2, "0x021D18F2 (battle indicator)"),
    (0x021D18F4, "0x021D18F4"),
    (0x027E3444, "0x027E3444 (alt battle flag?)"),
]

print("\nPotential battle flags:")
for addr, label in potential_flags:
    try:
        val = emu.memory.unsigned.read_short(addr)
        print(f"  {label}: {val} (0x{val:04X})")
    except Exception as e:
        print(f"  {label}: ERROR ({e})")
