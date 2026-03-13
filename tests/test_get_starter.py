"""
Advance the game from the bedroom to getting the starter Pokemon.
In Platinum:
1. Player is in bedroom → go downstairs
2. Mom talks → exit house
3. Go to Route 201 → rival appears
4. Go to Lake Verity → Starly attack
5. Pick starter from briefcase (Turtwig/Chimchar/Piplup)
6. Battle wild Starly with starter

This creates a savestate with a Pokemon in the party for testing.
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

    def wait(frames: int = 60) -> None:
        for _ in range(frames):
            emu.cycle(with_joystick=False)

    def press(key: int, hold: int = 6, post_wait: int = 30) -> None:
        emu.input.keypad_add_key(keymask(key))
        wait(hold)
        emu.input.keypad_rm_key(keymask(key))
        wait(post_wait)

    def press_a(post_wait: int = 90) -> None:
        press(Keys.KEY_A, hold=6, post_wait=post_wait)

    def move(key: int, steps: int = 1) -> None:
        for _ in range(steps):
            press(key, hold=16, post_wait=30)

    def capture(label: str) -> None:
        buf = emu.display_buffer_as_rgbx()
        frame = np.frombuffer(buf, dtype=np.uint8).reshape(384, 256, 4)[:, :, :3].copy()
        Image.fromarray(frame[:192]).save(str(OUT / f"{label}_top.png"))
        Image.fromarray(frame[192:]).save(str(OUT / f"{label}_bot.png"))
        p = reader.read_player()
        print(f"  [{label}] Map:{p.map_id} ({p.x},{p.y}) Party:{p.party_count}")

    def mash_a(count: int = 20) -> None:
        for _ in range(count):
            press_a(post_wait=60)

    # Clear the intro dialogue (rival in bedroom + TV cutscene)
    print("Clearing intro dialogue...")
    mash_a(60)
    capture("after_clearing")

    # Navigate: we should be in the bedroom now, need to go downstairs
    # The stairs are typically at the bottom of the room
    print("\nNavigating to stairs...")
    move(Keys.KEY_DOWN, 5)
    capture("near_stairs")

    # Keep going down to exit the room
    move(Keys.KEY_DOWN, 5)
    wait(60)
    capture("going_down")

    # Press A through any mom dialogue
    mash_a(30)
    capture("after_mom")

    # Go down and out the door
    move(Keys.KEY_DOWN, 8)
    capture("heading_to_door")
    mash_a(10)
    move(Keys.KEY_DOWN, 5)
    capture("outside_attempt")

    # Check if we made it outside (map ID should change)
    p = reader.read_player()
    print(f"\nCurrent state: Map {p.map_id} at ({p.x}, {p.y})")

    # In Platinum after the bedroom scene, the rival runs off and you need
    # to go downstairs, talk to mom, then go outside to Route 201.
    # This is a scripted sequence. Let's keep pressing A and moving down.
    for attempt in range(5):
        mash_a(10)
        move(Keys.KEY_DOWN, 5)
        move(Keys.KEY_LEFT, 3)
        move(Keys.KEY_RIGHT, 3)
        p = reader.read_player()
        print(f"  Attempt {attempt}: Map {p.map_id} at ({p.x}, {p.y})")
        capture(f"attempt_{attempt}")

    # Go towards Route 201 (left/up from Twinleaf)
    print("\nHeading towards Route 201...")
    for _ in range(3):
        mash_a(5)
        move(Keys.KEY_UP, 10)
        move(Keys.KEY_LEFT, 5)
        p = reader.read_player()
        print(f"  Map {p.map_id} at ({p.x}, {p.y})")

    capture("route_attempt")

    # This is going to be a long scripted sequence. Let's just mash through it.
    # The key events:
    # 1. Go to Route 201 → rival stops you
    # 2. Prof Rowan appears → gives briefcase
    # 3. Pick a starter (Turtwig = left)
    # 4. Battle Starly
    print("\nMashing through scripted events...")
    for i in range(200):
        press_a(post_wait=30)
        if i % 50 == 49:
            p = reader.read_player()
            capture(f"mash_{i+1}")
            print(f"  Mash {i+1}: Map {p.map_id} at ({p.x}, {p.y}) Party:{p.party_count}")
            if p.party_count > 0:
                print(f"  *** GOT A POKEMON! ***")
                break

    # Check if we got a Pokemon
    p = reader.read_player()
    party = reader.read_party()
    print(f"\nFinal state: Map {p.map_id} at ({p.x}, {p.y})")
    print(f"Party count: {party.count}")

    if party.count > 0:
        for pkmn in party.pokemon:
            print(f"  {pkmn.nickname} ({pkmn.species_name}) Lv.{pkmn.level}")
            print(f"    HP: {pkmn.hp_current}/{pkmn.hp_max}")
            print(f"    Moves: {[m.name for m in pkmn.moves]}")
            print(f"    Nature: {pkmn.nature.name if pkmn.nature else '?'}")
            print(f"    PID: 0x{pkmn.pid:08X}")

        # Save this state!
        emu.savestate.save_file(str(OUT / "with_starter.dst"))
        print(f"\nSaved state with starter to {OUT / 'with_starter.dst'}")
    else:
        # Save current progress regardless
        emu.savestate.save_file(str(OUT / "progress.dst"))
        print(f"\nNo Pokemon yet. Saved progress to {OUT / 'progress.dst'}")
        capture("final_state")

    emu.destroy()


if __name__ == "__main__":
    main()
