"""
Test the memory reader against the golden savestate.
Validates all confirmed values from the offset investigation.
"""

import os
os.environ["SDL_VIDEODRIVER"] = "dummy"

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from desmume.emulator import DeSmuME
from desmume.controls import keymask, Keys
from harness.memory import MemoryReader

SAVESTATE = Path(__file__).parent / "output" / "clean_intro" / "golden_gameplay.dst"
ROM_PATH = Path(__file__).parent.parent / "roms" / "Pokemon - Platinum Version (USA).nds"


def main():
    print("=" * 60)
    print("Memory Reader Test")
    print("=" * 60)

    emu = DeSmuME()
    emu.open(str(ROM_PATH))
    emu.savestate.load_file(str(SAVESTATE))

    # Let the game settle
    for _ in range(60):
        emu.cycle(with_joystick=False)

    # Clear dialogue (golden savestate is during intro cutscene)
    print("\nClearing intro dialogue...")
    for _ in range(60):
        emu.input.keypad_add_key(keymask(Keys.KEY_A))
        for _ in range(6):
            emu.cycle(with_joystick=False)
        emu.input.keypad_rm_key(keymask(Keys.KEY_A))
        for _ in range(90):
            emu.cycle(with_joystick=False)

    reader = MemoryReader(emu)

    # Test player state
    print("\n--- Player State ---")
    player = reader.read_player()
    print(f"  Name: '{player.name}' (may be empty before first save)")
    print(f"  Gender: {player.gender_name}")
    print(f"  Money: ¥{player.money}")
    print(f"  Badges: {player.badge_count}/8 {player.badge_list}")
    print(f"  Play Time: {player.play_time_str}")
    print(f"  Location: {player.map_name} (ID: {player.map_id})")
    print(f"  Position: ({player.x}, {player.y})")
    print(f"  Party count: {player.party_count}")
    print(f"  TID: {player.trainer_id}, SID: {player.secret_id}")

    # Validate known values
    errors = []
    if player.money != 3000:
        errors.append(f"Money expected 3000, got {player.money}")
    if player.gender != 0:
        errors.append(f"Gender expected 0 (Male), got {player.gender}")
    if player.badge_count != 0:
        errors.append(f"Badges expected 0, got {player.badge_count}")
    if player.map_id != 415:
        errors.append(f"Map ID expected 415, got {player.map_id}")
    # Coords should be reasonable small numbers
    if player.x < 1 or player.x > 100:
        errors.append(f"X coord {player.x} seems out of range for bedroom")
    if player.y < 1 or player.y > 100:
        errors.append(f"Y coord {player.y} seems out of range for bedroom")

    # Test movement
    print("\n--- Movement Test ---")
    x_before, y_before = player.x, player.y
    print(f"  Before: ({x_before}, {y_before})")

    # Move down
    emu.input.keypad_add_key(keymask(Keys.KEY_DOWN))
    for _ in range(16):
        emu.cycle(with_joystick=False)
    emu.input.keypad_rm_key(keymask(Keys.KEY_DOWN))
    for _ in range(30):
        emu.cycle(with_joystick=False)

    player_after = reader.read_player()
    print(f"  After DOWN: ({player_after.x}, {player_after.y})")
    dy = player_after.y - y_before
    if dy != 1:
        errors.append(f"DOWN should increase Y by 1, got delta={dy}")
    else:
        print(f"  ✓ Y increased by 1")

    # Test party read (should be empty at this point)
    print("\n--- Party ---")
    party = reader.read_party()
    print(f"  Party count: {party.count}")
    if party.count == 0:
        print(f"  (Empty — player hasn't received starter yet)")
    for pkmn in party.pokemon:
        print(f"  Slot {pkmn.slot}: {pkmn.nickname} ({pkmn.species_name}) "
              f"Lv.{pkmn.level} HP {pkmn.hp_current}/{pkmn.hp_max}")
        for move in pkmn.moves:
            print(f"    - {move.name} [{move.type}] PP {move.pp_current}/{move.pp_max}")

    # Test full state
    print("\n--- Full State ---")
    state = reader.read_state()
    print(f"  Player: {state.player.gender_name}, ¥{state.player.money}")
    print(f"  Location: {state.player.map_name} ({state.player.x}, {state.player.y})")
    print(f"  Party: {state.party.count} Pokemon")

    # Results
    print("\n" + "=" * 60)
    if errors:
        print(f"ISSUES ({len(errors)}):")
        for e in errors:
            print(f"  ✗ {e}")
    else:
        print("ALL CHECKS PASSED ✓")
    print("=" * 60)

    emu.destroy()


if __name__ == "__main__":
    main()
