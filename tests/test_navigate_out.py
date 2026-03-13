"""
Smart navigation: use coordinate feedback to get out of the house.
Load from progress_v2 savestate (player on first floor at ~(1,5)).
"""

import os
os.environ["SDL_VIDEODRIVER"] = "dummy"

import sys
import numpy as np
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from desmume.emulator import DeSmuME
from desmume.controls import keymask, Keys
from harness.memory import MemoryReader

ROM_PATH = Path(__file__).parent.parent / "roms" / "Pokemon - Platinum Version (USA).nds"
OUT = Path(__file__).parent / "output" / "get_starter"

# Try progress savestate first, fall back to golden
SAVESTATE = OUT / "progress_v2.dst"
if not SAVESTATE.exists():
    SAVESTATE = Path(__file__).parent / "output" / "clean_intro" / "golden_gameplay.dst"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    emu = DeSmuME()
    emu.open(str(ROM_PATH))
    emu.savestate.load_file(str(SAVESTATE))
    reader = MemoryReader(emu)

    def wait(n=60):
        for _ in range(n):
            emu.cycle(with_joystick=False)

    def press(key, hold=6, pw=30):
        emu.input.keypad_add_key(keymask(key))
        wait(hold)
        emu.input.keypad_rm_key(keymask(key))
        wait(pw)

    def move_and_check(key, label=""):
        p = reader.read_player()
        x0, y0, m0 = p.x, p.y, p.map_id
        press(key, hold=16, pw=20)
        p = reader.read_player()
        moved = (p.x != x0 or p.y != y0 or p.map_id != m0)
        if moved:
            print(f"  {label}: ({x0},{y0}) → ({p.x},{p.y}) map:{p.map_id}")
        return p, moved

    def cap(label):
        buf = emu.display_buffer_as_rgbx()
        frame = np.frombuffer(buf, dtype=np.uint8).reshape(384, 256, 4)[:, :, :3].copy()
        Image.fromarray(frame[:192]).save(str(OUT / f"nav_{label}_top.png"))

    # Clear any pending dialogue
    print("Clearing dialogue...")
    for _ in range(100):
        press(Keys.KEY_A, hold=6, pw=30)
    wait(120)

    p = reader.read_player()
    print(f"Start: Map {p.map_id} ({p.x},{p.y}) Party:{p.party_count}")
    cap("start")

    # Strategy: try to reach the door by going DOWN and CENTER
    # The door in Twinleaf house is typically at the bottom-center
    # Try going RIGHT first (to get away from the wall), then DOWN
    print("\nNavigating: RIGHT then DOWN...")
    for _ in range(5):
        move_and_check(Keys.KEY_RIGHT, "RIGHT")
    for _ in range(15):
        p, moved = move_and_check(Keys.KEY_DOWN, "DOWN")
        if p.map_id != 415:
            print(f"  *** MAP CHANGED to {p.map_id}! ***")
            break

    cap("after_nav1")
    p = reader.read_player()
    print(f"After nav1: Map {p.map_id} ({p.x},{p.y})")

    # If still in house, try: clear dialogue, then navigate more
    if p.map_id == 415:
        print("\nStill in house. Clearing more dialogue...")
        for _ in range(50):
            press(Keys.KEY_A, hold=6, pw=30)
        wait(120)

        # Try going to center-bottom of the room
        for _ in range(5):
            move_and_check(Keys.KEY_RIGHT, "RIGHT")
        for _ in range(15):
            p, moved = move_and_check(Keys.KEY_DOWN, "DOWN")
            if p.map_id != 415:
                print(f"  *** MAP CHANGED to {p.map_id}! ***")
                break

    cap("after_nav2")
    p = reader.read_player()
    print(f"After nav2: Map {p.map_id} ({p.x},{p.y})")

    # If we made it outside, continue the adventure
    if p.map_id != 415:
        print("\n*** OUTSIDE! Continuing towards Lake Verity ***")
        # Mash A through all dialogue, move in all directions
        for cycle in range(50):
            # Alternate: mash A, then move
            for _ in range(10):
                press(Keys.KEY_A, hold=6, pw=30)
            # Move UP (towards Route 201)
            for _ in range(5):
                press(Keys.KEY_UP, hold=16, pw=16)
            for _ in range(3):
                press(Keys.KEY_LEFT, hold=16, pw=16)

            p = reader.read_player()
            if p.party_count > 0:
                print(f"  *** GOT POKEMON at cycle {cycle}! ***")
                break
            if cycle % 10 == 9:
                cap(f"outdoor_{cycle}")
                print(f"  Cycle {cycle}: Map {p.map_id} ({p.x},{p.y}) Party:{p.party_count}")
    else:
        # Still stuck. Save state and give up gracefully
        print("\nStill in house. This needs manual investigation.")
        # Let's try the EXACT door position. In many Pokemon houses,
        # the door mat is at the very bottom center.
        # Try pressing DOWN from various x positions
        for x_target in range(2, 8):
            # Move to x_target
            p = reader.read_player()
            while p.x < x_target:
                press(Keys.KEY_RIGHT, hold=16, pw=16)
                p = reader.read_player()
            while p.x > x_target:
                press(Keys.KEY_LEFT, hold=16, pw=16)
                p = reader.read_player()
            # Now press DOWN until we can't or map changes
            for _ in range(20):
                p, moved = move_and_check(Keys.KEY_DOWN, f"x={x_target}")
                if p.map_id != 415:
                    print(f"  *** DOOR at x={x_target}! Map → {p.map_id} ***")
                    break
                if not moved:
                    break
            if p.map_id != 415:
                break
        
        if p.map_id != 415:
            print(f"\nMade it outside! Map {p.map_id} ({p.x},{p.y})")

    # Final status
    p = reader.read_player()
    party = reader.read_party()
    cap("final")
    print(f"\n=== FINAL: Map {p.map_id} ({p.x},{p.y}) Party:{party.count} ===")

    if party.count > 0:
        for pk in party.pokemon:
            print(f"  {pk.nickname} ({pk.species_name}) Lv.{pk.level} HP:{pk.hp_current}/{pk.hp_max}")
            print(f"    Moves: {[m.name for m in pk.moves]}")
            print(f"    Nature: {pk.nature.name if pk.nature else '?'}")
        emu.savestate.save_file(str(OUT / "with_starter.dst"))
        print(f"\nSaved with starter!")
    else:
        emu.savestate.save_file(str(OUT / "progress_v3.dst"))

    emu.destroy()

if __name__ == "__main__":
    main()
