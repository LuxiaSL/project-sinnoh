"""
Get the starter Pokemon by carefully navigating from the golden savestate.

From screenshots, the sequence is:
1. Golden savestate: TV cutscene → clear dialogue → bedroom
2. Rival enters, talks → clear dialogue → rival leaves
3. Go DOWNSTAIRS (stairs are at bottom-left of bedroom)
4. Mom talks → clear dialogue
5. Exit house (door at bottom of first floor)
6. Rival is outside → drags player to Route 201
7. Rowan + Dawn/Lucas appear → dialogue
8. Go to Lake Verity → Starly attack
9. Pick starter from briefcase
10. Battle Starly
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

SAVESTATE = Path(__file__).parent / "output" / "clean_intro" / "golden_gameplay.dst"
ROM_PATH = Path(__file__).parent.parent / "roms" / "Pokemon - Platinum Version (USA).nds"
OUT = Path(__file__).parent / "output" / "get_starter"

def main():
    OUT.mkdir(parents=True, exist_ok=True)

    emu = DeSmuME()
    emu.open(str(ROM_PATH))
    emu.savestate.load_file(str(SAVESTATE))

    reader = MemoryReader(emu)
    step = [0]

    def wait(frames=60):
        for _ in range(frames):
            emu.cycle(with_joystick=False)

    def press(key, hold=6, post=30):
        emu.input.keypad_add_key(keymask(key))
        wait(hold)
        emu.input.keypad_rm_key(keymask(key))
        wait(post)

    def press_a(n=1, post=60):
        for _ in range(n):
            press(Keys.KEY_A, hold=6, post_wait=post)

    def press(key, hold=6, post_wait=30):
        emu.input.keypad_add_key(keymask(key))
        wait(hold)
        emu.input.keypad_rm_key(keymask(key))
        wait(post_wait)

    def move(key, steps=1):
        for _ in range(steps):
            press(key, hold=16, post_wait=16)

    def mash_a(n=20, post=60):
        for _ in range(n):
            press(Keys.KEY_A, hold=6, post_wait=post)

    def cap(label):
        step[0] += 1
        buf = emu.display_buffer_as_rgbx()
        frame = np.frombuffer(buf, dtype=np.uint8).reshape(384, 256, 4)[:, :, :3].copy()
        Image.fromarray(frame[:192]).save(str(OUT / f"v2_{step[0]:03d}_{label}_top.png"))
        p = reader.read_player()
        print(f"  [{step[0]:03d}] {label}: Map {p.map_id} ({p.x},{p.y}) Party:{p.party_count}")
        return p

    def status():
        p = reader.read_player()
        return p.map_id, p.x, p.y, p.party_count

    # Phase 1: Clear the TV cutscene + rival dialogue
    print("=== Phase 1: Clear cutscene + rival dialogue ===")
    wait(60)
    mash_a(80, post=60)
    p = cap("after_clearing")

    # Phase 2: Navigate from bedroom to stairs
    # Bedroom layout (from screenshots): stairs are on the LEFT side
    # Player starts around (4,6). Need to go DOWN and LEFT to reach stairs.
    print("\n=== Phase 2: Navigate to stairs ===")
    move(Keys.KEY_DOWN, 4)
    move(Keys.KEY_LEFT, 3)
    move(Keys.KEY_DOWN, 3)
    cap("near_stairs")

    # Keep going down
    move(Keys.KEY_DOWN, 5)
    p = cap("going_down")

    # Check if map changed (stairs = map transition)
    if p.map_id != 415:
        print(f"  Map changed to {p.map_id}! Went downstairs.")
    else:
        # Try different path — stairs might be elsewhere
        move(Keys.KEY_LEFT, 3)
        move(Keys.KEY_DOWN, 3)
        move(Keys.KEY_RIGHT, 3)
        move(Keys.KEY_DOWN, 3)
        p = cap("alt_path")

    # Phase 3: Mom dialogue on first floor
    print("\n=== Phase 3: First floor / Mom ===")
    mash_a(30, post=60)
    p = cap("after_mom")

    # Phase 4: Exit house
    print("\n=== Phase 4: Exit house ===")
    move(Keys.KEY_DOWN, 10)
    mash_a(10, post=60)
    move(Keys.KEY_DOWN, 5)
    p = cap("exit_attempt")

    # Phase 5: Outside + rival sequence
    print("\n=== Phase 5: Outside ===")
    mash_a(40, post=30)
    move(Keys.KEY_UP, 10)
    mash_a(20, post=30)
    p = cap("outside_progress")

    # Phase 6: Route 201 / Lake Verity approach
    print("\n=== Phase 6: Route 201 ===")
    move(Keys.KEY_UP, 15)
    mash_a(30, post=30)
    move(Keys.KEY_LEFT, 10)
    mash_a(20, post=30)
    move(Keys.KEY_UP, 10)
    mash_a(20, post=30)
    p = cap("route_progress")

    # Phase 7: Keep pushing — alternate between moving and mashing A
    print("\n=== Phase 7: Push towards Lake Verity ===")
    for cycle in range(20):
        move(Keys.KEY_UP, 5)
        move(Keys.KEY_LEFT, 3)
        mash_a(10, post=30)
        _, _, _, party = status()
        if party > 0:
            print(f"  *** GOT POKEMON at cycle {cycle}! ***")
            break
        if cycle % 5 == 4:
            p = cap(f"push_{cycle}")

    # Final check
    p = cap("final")
    party = reader.read_party()
    print(f"\n=== RESULT ===")
    print(f"Map: {p.map_id} Position: ({p.x}, {p.y})")
    print(f"Party: {party.count}")

    if party.count > 0:
        for pkmn in party.pokemon:
            print(f"  {pkmn.nickname} ({pkmn.species_name}) Lv.{pkmn.level}")
            print(f"    HP: {pkmn.hp_current}/{pkmn.hp_max}")
            print(f"    Nature: {pkmn.nature.name if pkmn.nature else '?'}")
            print(f"    Moves: {[m.name for m in pkmn.moves]}")
            print(f"    PID: 0x{pkmn.pid:08X}")
            print(f"    Shiny: {pkmn.is_shiny}")
        emu.savestate.save_file(str(OUT / "with_starter.dst"))
        print(f"\nSaved: {OUT / 'with_starter.dst'}")
    else:
        emu.savestate.save_file(str(OUT / "progress_v2.dst"))
        print(f"\nNo Pokemon yet. Saved progress.")

    emu.destroy()


if __name__ == "__main__":
    main()
