"""
Phase 1B integration tests.

Tests for:
- Inventory reader (needs golden savestate)
- Battle state reader (needs battle savestate — may not have one yet)
- Fog-of-war (pure logic, no emulator needed)
- Novelty detection (pure logic, no emulator needed)
- Formatter extensions (pure logic)
"""

import os
os.environ["SDL_VIDEODRIVER"] = "dummy"

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_fogofwar():
    """Test fog-of-war tracking."""
    print("[Test 1] Fog-of-War")

    from harness.fogofwar import FogOfWar

    fow = FogOfWar()

    # First visit should return True
    assert fow.visit(415, 4, 6) is True, "First visit should be new"
    assert fow.visit(415, 4, 7) is True
    assert fow.visit(415, 4, 6) is False, "Second visit should not be new"

    assert fow.tiles_visited(415) == 2
    assert fow.is_visited(415, 4, 6)
    assert not fow.is_visited(415, 10, 10)

    # New map detection
    assert fow.is_new_map(100) is True
    fow.visit(100, 0, 0)
    assert fow.is_new_map(100) is False

    assert 415 in fow.visited_maps()
    assert 100 in fow.visited_maps()

    print("  ✓ Basic visit tracking works")

    # Grid rendering
    grid = fow.render_grid(415, 4, 7, radius=2)
    lines = grid.split("\n")
    assert len(lines) == 5, f"Expected 5 rows, got {len(lines)}"
    # Player should be at center
    assert "@" in lines[2]
    # (4,6) was visited, which is at dy=-1 from player at (4,7)
    assert "·" in lines[1]  # y=6 row
    print("  ✓ Grid rendering works")

    # Persistence
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        save_path = f.name

    try:
        fow_save = FogOfWar(save_path=save_path)
        fow_save.visit(415, 1, 2)
        fow_save.visit(415, 3, 4)
        fow_save.save()

        # Load in new instance
        fow_load = FogOfWar(save_path=save_path)
        assert fow_load.is_visited(415, 1, 2)
        assert fow_load.is_visited(415, 3, 4)
        assert not fow_load.is_visited(415, 5, 6)
        print("  ✓ Persistence (save/load) works")
    finally:
        os.unlink(save_path)


def test_novelty():
    """Test novelty detection."""
    print("\n[Test 2] Novelty Detection")

    from harness.novelty import NoveltyTracker
    from harness.models import PlayerState, Party, Pokemon, Move

    tracker = NoveltyTracker()

    # Create a player state
    player = PlayerState(
        name="TEST",
        money=3000,
        map_id=415,
        map_name="Twinleaf Town",
        x=4, y=6,
    )
    party = Party(count=0, pokemon=[])

    # First check — should flag new map
    flags = tracker.check(player, party)
    assert any("First visit" in f for f in flags), f"Should flag new map, got: {flags}"
    print("  ✓ New map detection works")

    # Second check — same map, no flags
    flags = tracker.check(player, party)
    assert not any("First visit" in f for f in flags), "Should not re-flag same map"
    print("  ✓ No duplicate map flags")

    # New species encountered
    flags = tracker.check(player, party, encountered_species=25)  # Pikachu
    assert any("New Pokemon" in f for f in flags), f"Should flag new species, got: {flags}"
    print("  ✓ New species detection works")

    # Same species again
    flags = tracker.check(player, party, encountered_species=25)
    assert not any("New Pokemon" in f for f in flags), "Should not re-flag same species"
    print("  ✓ No duplicate species flags")

    # Persistence
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        save_path = f.name

    try:
        tracker2 = NoveltyTracker(save_path=save_path)
        tracker2.check(player, party)  # marks map 415
        tracker2.mark_species_seen(1)  # Bulbasaur
        tracker2.save()

        tracker3 = NoveltyTracker(save_path=save_path)
        assert 415 in tracker3._seen_maps
        assert 1 in tracker3._seen_species
        print("  ✓ Persistence works")
    finally:
        os.unlink(save_path)


def test_models():
    """Test new Pydantic models."""
    print("\n[Test 3] New Models")

    from harness.models import (
        InventoryItem, InventoryPocket, Inventory,
        BattlePokemon, BattleState,
    )

    # Inventory models
    item = InventoryItem(item_id=4, item_name="Poke Ball", quantity=5)
    assert item.item_name == "Poke Ball"

    pocket = InventoryPocket(name="Poke Balls", items=[item])
    assert pocket.count == 1

    inv = Inventory(pockets={"Poke Balls": pocket})
    assert inv.total_items == 1
    print("  ✓ Inventory models work")

    # Battle models
    bp = BattlePokemon(
        species_id=393,
        species_name="Piplup",
        level=5,
        hp_current=20,
        hp_max=20,
        types=["Water"],
    )
    assert bp.hp_fraction == 1.0

    bp2 = BattlePokemon(hp_current=10, hp_max=20)
    assert bp2.hp_fraction == 0.5

    battle = BattleState(
        is_wild=True,
        player_pokemon=bp,
        enemy_pokemon=bp2,
    )
    assert battle.is_wild
    print("  ✓ Battle models work")


def test_formatter_inventory():
    """Test inventory formatter."""
    print("\n[Test 4] Inventory Formatter")

    from harness.models import InventoryItem, InventoryPocket, Inventory
    from harness.formatter import format_inventory

    # Empty bag
    empty = Inventory(pockets={})
    assert format_inventory(empty) == "Bag is empty."
    print("  ✓ Empty bag formatted correctly")

    # Bag with items
    items = [
        InventoryItem(item_id=17, item_name="Potion", quantity=3),
        InventoryItem(item_id=26, item_name="Full Restore", quantity=1),
    ]
    pocket = InventoryPocket(name="Medicine", items=items)
    inv = Inventory(pockets={"Medicine": pocket})

    output = format_inventory(inv)
    assert "BAG" in output
    assert "Medicine" in output
    assert "Potion ×3" in output
    assert "Full Restore ×1" in output
    print("  ✓ Inventory formatting works")


def test_spatial_grid():
    """Test spatial grid generation."""
    print("\n[Test 5] Spatial Grid")

    from harness.spatial import SpatialGrid, TileType
    from harness.fogofwar import FogOfWar

    fow = FogOfWar()
    grid = SpatialGrid(fog_of_war=fow, radius=3)

    # Record some movement results
    # Player at (4, 6), moved down to (4, 7) — successful
    grid.record_move_result(415, 4, 6, 4, 7, "down")
    assert grid.get_tile(415, 4, 6) == TileType.WALKABLE
    assert grid.get_tile(415, 4, 7) == TileType.WALKABLE
    print("  ✓ Successful movement recorded correctly")

    # Player at (4, 7), tried to move left but stayed — wall
    grid.record_move_result(415, 4, 7, 4, 7, "left")
    assert grid.get_tile(415, 3, 7) == TileType.WALL
    print("  ✓ Failed movement (wall) recorded correctly")

    # Unknown tile
    assert grid.get_tile(415, 10, 10) == TileType.UNKNOWN
    print("  ✓ Unknown tiles reported correctly")

    # Render grid
    output = grid.render(415, 4, 7)
    lines = output.split("\n")
    assert len(lines) == 7, f"Expected 7 rows (radius=3), got {len(lines)}"
    assert "@" in output  # Player should be in the grid
    assert "#" in output  # Wall should be visible
    assert "." in output  # Walkable tiles should be visible
    print("  ✓ Grid rendering works")

    # Format with header
    formatted = grid.format_grid(415, 4, 7, map_name="Player's House")
    assert "SPATIAL GRID" in formatted
    assert "Player's House" in formatted
    print("  ✓ Grid formatting works")


def test_crypto_module():
    """Test the shared crypto module."""
    print("\n[Test 6] Shared Crypto Module (unchanged)")

    from harness.crypto import prng_next, decrypt_pokemon

    # Basic PRNG test
    seed = prng_next(0)
    assert seed == 0x00006073
    print("  ✓ PRNG works from shared module")

    # Full pipeline test
    import struct
    raw = bytearray(0xEC)
    pid = 0x12345678
    checksum = 0xABCD
    struct.pack_into("<I", raw, 0x00, pid)
    struct.pack_into("<H", raw, 0x06, checksum)

    # Set known data
    for i in range(0x08, 0xEC):
        raw[i] = i & 0xFF

    original = bytearray(raw)

    # Encrypt
    from harness.crypto import decrypt_blocks, decrypt_battle_stats
    encrypted = decrypt_blocks(bytearray(raw), checksum)
    encrypted = decrypt_battle_stats(encrypted, pid)

    # Decrypt
    decrypted = decrypt_blocks(bytearray(encrypted), checksum)
    decrypted = decrypt_battle_stats(decrypted, pid)

    # Round-trip should match
    for i in range(0x08, 0xEC):
        assert decrypted[i] == original[i], f"Mismatch at 0x{i:02X}"
    print("  ✓ Round-trip encryption works from shared module")


def _get_emu():
    """Get or create the shared emulator instance for live tests."""
    if not hasattr(_get_emu, "_emu"):
        from desmume.emulator import DeSmuME

        savestate_path = Path(__file__).parent / "output" / "clean_intro" / "golden_gameplay.dst"
        rom_path = Path(__file__).parent.parent / "roms" / "Pokemon - Platinum Version (USA).nds"

        if not savestate_path.exists() or not rom_path.exists():
            _get_emu._emu = None
            return None

        emu = DeSmuME()
        emu.open(str(rom_path))
        emu.savestate.load_file(str(savestate_path))

        # Clear dialogue
        from desmume.controls import keymask, Keys
        for _ in range(60):
            emu.input.keypad_add_key(keymask(Keys.KEY_A))
            emu.cycle(with_joystick=False)
        emu.input.keypad_rm_key(keymask(Keys.KEY_A))
        for _ in range(30):
            emu.cycle(with_joystick=False)

        _get_emu._emu = emu

    return _get_emu._emu


def test_inventory_reader_live():
    """Test inventory reader against the golden savestate."""
    print("\n[Test 7] Inventory Reader (Live)")

    emu = _get_emu()
    if emu is None:
        print("  ⚠ Savestate/ROM not found, skipping live test")
        return

    from harness.inventory import InventoryReader

    reader = InventoryReader(emu)
    inv = reader.read_inventory()

    # At the golden savestate (post-intro, pre-starter), bag should be
    # mostly empty but may have a few items
    print(f"  Total items in bag: {inv.total_items}")
    for pocket_name, pocket in inv.pockets.items():
        if pocket.count > 0:
            print(f"    {pocket_name}: {pocket.count} items")
            for item in pocket.items:
                print(f"      {item.item_name} ×{item.quantity}")

    # The bag structure should at least parse without errors
    assert isinstance(inv.total_items, int)
    print("  ✓ Inventory reader runs without errors")


def test_dialogue_reader_live():
    """Test dialogue text reader against golden savestate.

    NOTE: Must reload savestate fresh because the shared emu instance
    already cleared the dialogue with A-mashing. The golden savestate
    starts during a dialogue cutscene — we need that text in RAM.
    """
    print("\n[Test 8] Dialogue Reader (Live)")

    emu = _get_emu()
    if emu is None:
        print("  ⚠ Savestate/ROM not found, skipping")
        return

    # Reload savestate to get dialogue text back in RAM
    savestate_path = Path(__file__).parent / "output" / "clean_intro" / "golden_gameplay.dst"
    emu.savestate.load_file(str(savestate_path))
    # Just a few frames to stabilize — DON'T clear dialogue
    for _ in range(10):
        emu.cycle(with_joystick=False)

    from harness.dialogue import DialogueTranscript

    dt = DialogueTranscript(emu)

    # Scan for all dialogue buffers
    buffers = dt.read_all_buffers()
    print(f"  Found {len(buffers)} dialogue buffers")
    assert len(buffers) >= 2, f"Expected at least 2 buffers, got {len(buffers)}"

    # Verify we can read recognizable text
    found_rowan = False
    found_pokemon = False
    for addr, text in buffers:
        if "AAAAAAA" in text:
            found_rowan = True
            print(f"  ✓ Found Rowan's dialogue at 0x{addr:08X}")
        if "Pokémon are by our side" in text:
            found_pokemon = True
            print(f"  ✓ Found TV narrator at 0x{addr:08X}")

    assert found_rowan, "Should find Rowan's dialogue mentioning AAAAAAA"
    assert found_pokemon, "Should find TV narrator dialogue"

    # Test transcript formatting
    dt._buffer_addr = buffers[0][0]
    dt.poll()
    transcript = dt.format_transcript()
    assert "RECENT DIALOGUE" in transcript
    print("  ✓ Transcript formatting works")
    print("  ✓ Dialogue reader fully working!")

    # Re-clear dialogue for subsequent tests
    from desmume.controls import keymask, Keys
    for _ in range(60):
        emu.input.keypad_add_key(keymask(Keys.KEY_A))
        emu.cycle(with_joystick=False)
    emu.input.keypad_rm_key(keymask(Keys.KEY_A))
    for _ in range(30):
        emu.cycle(with_joystick=False)


def test_battle_detection_live():
    """Test battle detection (should be False in golden savestate)."""
    print("\n[Test 9] Battle Detection (Live)")

    emu = _get_emu()
    if emu is None:
        print("  ⚠ Savestate/ROM not found, skipping")
        return

    from harness.battle import BattleReader

    reader = BattleReader(emu)
    in_battle = reader.is_in_battle()
    print(f"  Battle indicator: {in_battle}")
    assert not in_battle, "Should not be in battle at golden savestate"
    print("  ✓ Battle detection correctly returns False in overworld")


def main():
    print("=" * 60)
    print("Phase 1B Tests")
    print("=" * 60)

    test_fogofwar()
    test_novelty()
    test_models()
    test_formatter_inventory()
    test_spatial_grid()
    test_crypto_module()
    test_inventory_reader_live()
    test_dialogue_reader_live()
    test_battle_detection_live()

    print("\n" + "=" * 60)
    print("ALL PHASE 1B TESTS PASSED ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
