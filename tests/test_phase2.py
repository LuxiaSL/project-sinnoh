"""Phase 2 tests — agent loop components.

Tests that don't require an API key (pure logic tests):
1. Game state detector (mode detection, idle check)
2. Action executor (button press, walk, touch, wait)
3. Journal system (write, read, pagination, persistence)
4. Type chart (effectiveness lookups)
5. Tool definitions (schema validation)
6. System prompt (builds without error)

Tests that DO require an API key are in test_phase2_live.py.
"""

import os
import sys
import json
import tempfile

# Ensure the src directory is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")


def test_journal_system():
    """Test journal write, read, pagination, and persistence."""
    print("Test 1: Journal system...")

    from harness.journal import Journal, SECTIONS

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name

    try:
        j = Journal(save_path=path)

        # Write to sections
        assert j.write("current_goals", "Get my first Pokemon and explore Twinleaf Town.")
        assert j.write("team_notes", "No team yet — haven't picked a starter.")
        assert j.write("adventure_log", "Woke up in my bedroom. Mom is downstairs.")
        assert j.write("adventure_log", "Got Running Shoes from Mom! Time to head out.", in_game_time="0:05:30")
        assert j.write("strategy", "Need to learn type matchups as I go.")

        # Verify counts
        assert j.entry_count("current_goals") == 1
        assert j.entry_count("adventure_log") == 2
        assert j.entry_count("strategy") == 1

        # Test replace_section (for living documents)
        j.replace_section("current_goals", "Head to Lake Verity with Barry.")
        assert j.entry_count("current_goals") == 1
        entries = j.read("current_goals")
        assert "Lake Verity" in entries[0].content

        # Test format_for_context (pagination)
        context = j.format_for_context()
        assert "YOUR JOURNAL" in context
        assert "Lake Verity" in context  # current_goals loaded
        assert "Running Shoes" in context  # recent adventure log loaded

        # Test persistence
        j2 = Journal(save_path=path)
        assert j2.entry_count("adventure_log") == 2
        assert j2.entry_count("current_goals") == 1

        # Test invalid section
        assert not j.write("invalid_section", "test")

        print("  PASS ✓")
    finally:
        os.unlink(path)


def test_type_chart():
    """Test type effectiveness lookups."""
    print("Test 2: Type chart...")

    from harness.data.type_chart import check_effectiveness, format_matchup, TYPES

    # Basic effectiveness
    r = check_effectiveness("Fire", ["Grass"])
    assert r["multiplier"] == 2.0, f"Fire vs Grass should be 2x, got {r['multiplier']}"

    r = check_effectiveness("Water", ["Fire"])
    assert r["multiplier"] == 2.0

    r = check_effectiveness("Electric", ["Ground"])
    assert r["multiplier"] == 0.0, "Electric vs Ground should be immune"

    r = check_effectiveness("Normal", ["Ghost"])
    assert r["multiplier"] == 0.0, "Normal vs Ghost should be immune"

    # Dual type
    r = check_effectiveness("Ice", ["Dragon", "Flying"])
    assert r["multiplier"] == 4.0, f"Ice vs Dragon/Flying should be 4x, got {r['multiplier']}"

    r = check_effectiveness("Ground", ["Electric", "Flying"])
    assert r["multiplier"] == 0.0, "Ground vs Electric/Flying — Flying gives immunity"

    # Format test
    text = format_matchup("Fire", ["Water"])
    assert "Not very effective" in text

    # Verify all 17 Gen 4 types present
    assert len(TYPES) == 17
    assert "Fairy" not in TYPES  # No Fairy in Gen 4

    print("  PASS ✓")


def test_tool_definitions():
    """Test that tool definitions are valid schemas."""
    print("Test 3: Tool definitions...")

    from harness.tools import (
        get_all_tools, get_tool_names,
        GAME_ACTION_NAMES, REFERENCE_TOOL_NAMES, JOURNAL_TOOL_NAMES,
    )

    tools = get_all_tools()
    names = get_tool_names()

    # Should have all expected tools
    expected = {
        "press_button", "walk", "touch", "wait",
        "check_type_chart", "check_bag", "check_party",
        "write_journal", "read_journal",
    }
    assert set(names) == expected, f"Missing tools: {expected - set(names)}"

    # Every tool should have name, description, input_schema
    for tool in tools:
        assert "name" in tool, f"Tool missing name: {tool}"
        assert "description" in tool, f"Tool {tool['name']} missing description"
        assert "input_schema" in tool, f"Tool {tool['name']} missing input_schema"
        assert tool["input_schema"]["type"] == "object"

    # Sets should be non-overlapping
    assert not (GAME_ACTION_NAMES & REFERENCE_TOOL_NAMES)
    assert not (GAME_ACTION_NAMES & JOURNAL_TOOL_NAMES)
    assert not (REFERENCE_TOOL_NAMES & JOURNAL_TOOL_NAMES)

    print("  PASS ✓")


def test_system_prompt():
    """Test that the system prompt builds correctly."""
    print("Test 4: System prompt...")

    from harness.prompt import build_system_prompt

    prompt = build_system_prompt()

    # Should contain key framing elements
    assert "Pokemon Platinum" in prompt
    assert "first time in Sinnoh" in prompt
    assert "journal" in prompt.lower()
    assert "walk" in prompt
    assert "press_button" in prompt

    # Should NOT contain task framing
    assert "AI agent" not in prompt
    assert "complete this game" not in prompt

    # Should be reasonable length
    assert len(prompt) > 500
    assert len(prompt) < 10000

    print("  PASS ✓")


def test_game_state_detector_modes():
    """Test game mode detection logic (without emulator)."""
    print("Test 5: Game state detector available actions...")

    from harness.game_state import GameMode, GameStateDetector

    # Test available_action_types for each mode
    # (We can't test the actual detection without an emulator,
    # but we can test the action routing)
    class FakeDetector:
        _last_mode = GameMode.OVERWORLD
        def available_action_types(self, mode=None):
            return GameStateDetector.available_action_types(self, mode)

    d = FakeDetector()

    overworld_actions = d.available_action_types(GameMode.OVERWORLD)
    assert "walk" in overworld_actions
    assert "press_button" in overworld_actions
    assert "use_tool" in overworld_actions

    battle_actions = d.available_action_types(GameMode.BATTLE)
    assert "wait" in battle_actions
    assert "walk" not in battle_actions

    battle_menu_actions = d.available_action_types(GameMode.BATTLE_MENU)
    assert "press_button" in battle_menu_actions
    assert "walk" not in battle_menu_actions

    dialogue_actions = d.available_action_types(GameMode.DIALOGUE)
    assert "press_button" in dialogue_actions

    transition_actions = d.available_action_types(GameMode.TRANSITION)
    assert "wait" in transition_actions
    assert len(transition_actions) == 1  # Only wait during transitions

    print("  PASS ✓")


def test_action_executor_with_emulator():
    """Test action execution with the live emulator."""
    print("Test 6: Action executor (live emulator)...")

    from desmume.emulator import DeSmuME
    emu = DeSmuME()
    rom_path = os.path.join(
        os.path.dirname(__file__), "..", "roms",
        "Pokemon - Platinum Version (USA).nds"
    )
    emu.open(rom_path)

    savestate = os.path.join(
        os.path.dirname(__file__), "output", "clean_intro",
        "golden_gameplay.dst"
    )
    emu.savestate.load_file(savestate)

    # Run some frames to stabilize
    for _ in range(30):
        emu.cycle(with_joystick=False)

    from harness.actions import ActionExecutor, ActionResult

    executor = ActionExecutor(emu)

    # Test button press
    result = executor.press_button("a")
    assert result.result == ActionResult.SUCCESS
    assert result.frames_advanced > 0

    # Test walk
    result = executor.walk("right", steps=1)
    assert result.result == ActionResult.SUCCESS
    assert result.frames_advanced > 0

    # Test wait
    result = executor.wait(frames=30)
    assert result.result == ActionResult.SUCCESS
    assert result.frames_advanced == 30

    # Test invalid button
    result = executor.press_button("invalid")
    assert result.result == ActionResult.INVALID

    # Test invalid direction
    result = executor.walk("diagonal")
    assert result.result == ActionResult.INVALID

    # Test invalid touch coords
    result = executor.touch(300, 200)
    assert result.result == ActionResult.INVALID

    # Test execute dispatcher
    result = executor.execute("press_button", button="b")
    assert result.result == ActionResult.SUCCESS

    result = executor.execute("unknown_action")
    assert result.result == ActionResult.INVALID

    # Check total frames advanced
    assert executor.total_frames > 0

    print(f"  PASS ✓ (total frames: {executor.total_frames})")


def test_game_state_detector_live():
    """Test game state detection with the live emulator."""
    print("Test 7: Game state detector (live emulator)...")

    import numpy as np
    from desmume.emulator import DeSmuME

    # Reuse the emulator from test 6 if possible, or create new
    emu = DeSmuME()
    rom_path = os.path.join(
        os.path.dirname(__file__), "..", "roms",
        "Pokemon - Platinum Version (USA).nds"
    )
    emu.open(rom_path)

    savestate = os.path.join(
        os.path.dirname(__file__), "output", "clean_intro",
        "golden_gameplay.dst"
    )
    emu.savestate.load_file(savestate)

    # Run frames to get past any dialogue
    for _ in range(120):
        emu.cycle(with_joystick=False)

    from harness.game_state import GameStateDetector, GameMode

    detector = GameStateDetector(emu)

    # Should not be in battle at the golden savestate
    assert not detector.is_in_battle(), "Should not be in battle at golden savestate"

    # Capture a frame
    buf = emu.display_buffer_as_rgbx()
    frame = np.frombuffer(buf, dtype=np.uint8).reshape(384, 256, 4)[:, :, :3].copy()

    # Detect mode — should be overworld (or dialogue during intro)
    mode = detector.detect(frame=frame, has_dialogue=False)
    assert mode in (GameMode.OVERWORLD, GameMode.DIALOGUE), f"Unexpected mode: {mode}"

    # After a few stable frames, should be idle
    for _ in range(20):
        emu.cycle(with_joystick=False)
    buf = emu.display_buffer_as_rgbx()
    frame2 = np.frombuffer(buf, dtype=np.uint8).reshape(384, 256, 4)[:, :, :3].copy()

    # Multiple detect calls to build up stable frame count
    for _ in range(5):
        detector.detect(frame=frame2, has_dialogue=False)

    idle = detector.is_idle(frame=frame2, has_dialogue=False, min_stable_frames=2)
    # May or may not be idle depending on intro state, but shouldn't crash
    assert isinstance(idle, bool)

    # Battle type should be "none"
    assert detector.get_battle_type() == "none"

    print(f"  PASS ✓ (mode={mode.value}, idle={idle})")


if __name__ == "__main__":
    print("=== Phase 2 Tests ===\n")

    # Pure logic tests (no emulator needed)
    test_journal_system()
    test_type_chart()
    test_tool_definitions()
    test_system_prompt()
    test_game_state_detector_modes()

    # Live emulator tests
    test_action_executor_with_emulator()
    test_game_state_detector_live()

    print("\n=== All Phase 2 tests passed! ===")
