"""Test the dialogue reader with the updated char table."""
import os
os.environ["SDL_VIDEODRIVER"] = "dummy"

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from desmume.emulator import DeSmuME

rom_path = Path(__file__).parent.parent / "roms" / "Pokemon - Platinum Version (USA).nds"
savestate_path = Path(__file__).parent / "output" / "clean_intro" / "golden_gameplay.dst"

emu = DeSmuME()
emu.open(str(rom_path))
emu.savestate.load_file(str(savestate_path))

for _ in range(10):
    emu.cycle(with_joystick=False)

from harness.dialogue import DialogueTranscript

dt = DialogueTranscript(emu)

# Scan for all buffers
print("Scanning for dialogue buffers...")
buffers = dt.read_all_buffers()

print(f"\nFound {len(buffers)} dialogue buffers with text:")
for addr, text in buffers:
    print(f"\n--- 0x{addr:08X} ---")
    print(text)

# Test the transcript formatting
if buffers:
    # Set the first buffer as active
    dt._buffer_addr = buffers[0][0]
    text = dt.read_current()
    if text:
        dt.poll()
        print("\n" + "=" * 60)
        print("Transcript format:")
        print(dt.format_transcript())
