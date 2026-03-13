"""
Clean Platinum Intro Run — Phase 0 Dry Run

A patient, deliberate playthrough of Platinum's intro sequence.
Demonstrates the approach the harness should use:
- Wait for visual cues (text done, screen settled), then act
- Use button controls by default, touch only when required
- Capture at every meaningful state change
- No frame racing — let the game go at its own pace

This maps every screen transition from boot to gameplay.
"""

import os
os.environ["SDL_VIDEODRIVER"] = "dummy"

import sys
from pathlib import Path
from dataclasses import dataclass

import numpy as np
from PIL import Image

from desmume.emulator import DeSmuME
from desmume.controls import keymask, Keys


OUTPUT_DIR = Path(__file__).parent / "output" / "clean_intro"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ROM_PATH = Path(__file__).parent.parent / "roms" / "Pokemon - Platinum Version (USA).nds"

# Touch button coordinates (measured from pixel analysis)
TOUCH_YES = (119, 81)
TOUCH_NO = (119, 120)
TOUCH_POKEBALL_CENTER = (128, 96)


class Platinum:
    """Minimal wrapper for patient interaction with Platinum."""

    def __init__(self, rom_path: str):
        self.emu = DeSmuME()
        self.emu.open(rom_path)
        self.capture_count = 0

    def wait(self, frames: int = 60) -> None:
        """Advance frames without input."""
        for _ in range(frames):
            self.emu.cycle(with_joystick=False)

    def press(self, key: int, hold: int = 6) -> None:
        """Press a button for `hold` frames, then release. No extra wait."""
        self.emu.input.keypad_add_key(keymask(key))
        self.wait(hold)
        self.emu.input.keypad_rm_key(keymask(key))

    def touch(self, x: int, y: int, hold: int = 12) -> None:
        """Touch bottom screen at (x, y) for `hold` frames, then release."""
        self.emu.input.touch_set_pos(x, y)
        self.wait(hold)
        self.emu.input.touch_release()

    def press_a(self) -> None:
        """Press A and wait for game to process."""
        self.press(Keys.KEY_A)

    def settle(self, frames: int = 180) -> None:
        """Wait for screen to settle (text to finish typing, transitions to complete).

        In Pokemon Platinum, nothing is time-sensitive. The game waits for you.
        A full dialogue box takes ~120 frames to type out. 180 frames is generous.
        """
        self.wait(frames)

    def capture(self, label: str) -> tuple[np.ndarray, np.ndarray]:
        """Capture both screens with a descriptive label. Returns (top, bottom)."""
        self.capture_count += 1
        buf = self.emu.display_buffer_as_rgbx()
        frame = np.frombuffer(buf, dtype=np.uint8).reshape(384, 256, 4)[:, :, :3].copy()
        top = frame[:192]
        bot = frame[192:]

        prefix = f"{self.capture_count:03d}_{label}"
        Image.fromarray(top).save(str(OUTPUT_DIR / f"{prefix}_top.png"))
        Image.fromarray(bot).save(str(OUTPUT_DIR / f"{prefix}_bot.png"))
        print(f"  [{self.capture_count:03d}] {label}")
        return top, bot

    def save_state(self, name: str) -> str:
        """Save emulator state to a file."""
        path = str(OUTPUT_DIR / f"{name}.dst")
        self.emu.savestate.save_file(path)
        return path

    def load_state(self, path: str) -> None:
        """Load emulator state from a file."""
        self.emu.savestate.load_file(path)
        self.wait(10)

    def read_memory(self) -> dict:
        """Read basic game state from memory."""
        base_ptr = self.emu.memory.unsigned.read_long(0x02101D2C)
        result = {"base_ptr": f"0x{base_ptr:08X}"}
        if 0x02000000 < base_ptr < 0x03000000:
            result["money"] = self.emu.memory.unsigned.read_long(base_ptr + 0x7C)
            result["badges"] = self.emu.memory.unsigned[base_ptr + 0x82]
        return result

    def cleanup(self) -> None:
        """Clean shutdown."""
        self.emu.destroy()


# --- Touch keyboard mapping ---
# The DS naming keyboard in Platinum has a fixed layout.
# This maps printable characters to (x, y) touch coordinates on the bottom screen.
# Will be populated during the clean run by examining the keyboard screen.
# For now, we'll use d-pad navigation as fallback.

# The keyboard layout (uppercase mode) in Platinum is approximately:
# Row 0 (y~32):  A B C D E F G H I J K L M
# Row 1 (y~48):  N O P Q R S T U V W X Y Z
# Row 2 (y~64):  (lowercase / symbols toggle, etc.)
# Each character cell is roughly 16px wide starting at x~16
# This needs verification during the run.


def type_name_dpad(game: Platinum, name: str) -> None:
    """Type a name using d-pad navigation on the naming screen.

    The naming screen has a keyboard grid. We navigate to each letter
    with the d-pad and press A to select it, then navigate to OK/END
    to confirm.

    This is the fallback approach — touch mapping would be cleaner.
    For now, we'll capture the keyboard layout and map it.
    """
    # TODO: implement once we see the keyboard layout
    # For the clean run, we'll just capture the keyboard and note coordinates
    pass


def main():
    print("=" * 60)
    print("Pokemon Platinum — Clean Intro Run")
    print("=" * 60)
    print()

    game = Platinum(str(ROM_PATH))

    # ================================================================
    # STAGE 1: Boot through system screens
    # ================================================================
    print("[Stage 1] System screens...")

    # Health & safety warning — appears immediately, needs touch to dismiss
    game.settle(180)
    game.capture("health_safety")
    game.touch(128, 96)  # touch anywhere to dismiss
    game.settle(120)
    game.capture("after_health_dismiss")

    # Nintendo / Game Freak logos — A to skip each
    for i in range(6):
        game.press_a()
        game.settle(120)
    game.capture("after_logos")

    # ================================================================
    # STAGE 2: Title screen
    # ================================================================
    print("\n[Stage 2] Title screen...")

    # Wait for the full title animation (Giratina, Platinum logo)
    game.settle(1200)
    game.capture("title_screen")

    # Press A to proceed past title
    game.press_a()
    game.settle(300)
    game.capture("after_title")

    # ================================================================
    # STAGE 3: Main menu → New Game
    # ================================================================
    print("\n[Stage 3] Main menu...")

    # Select NEW GAME (first option)
    game.press_a()
    game.settle(300)
    game.capture("new_game_selected")

    # Handle "Delete all saved data?" if it appears
    # (appears if there's existing save data from previous test runs)
    # Cursor defaults to NO — press UP to YES, then A to confirm
    game.settle(180)
    game.capture("delete_check")

    # Select YES on delete prompt (UP → A)
    game.press(Keys.KEY_UP)
    game.wait(30)
    game.press_a()
    game.settle(300)
    game.capture("delete_confirm_1")

    # Second confirmation
    game.press(Keys.KEY_UP)
    game.wait(30)
    game.press_a()
    game.settle(600)
    game.capture("delete_confirm_2")

    # Game restarts to title after deletion
    game.settle(600)
    game.capture("title_after_delete")

    # Go through title → new game again
    game.press_a()
    game.settle(300)
    game.press_a()
    game.settle(300)
    game.capture("new_game_clean")

    # ================================================================
    # STAGE 4: Touch tutorial
    # ================================================================
    print("\n[Stage 4] Touch tutorial...")

    # "Please touch a button on the Touch Screen below" YES/NO
    game.settle(300)
    game.capture("touch_tutorial_prompt")

    # Touch YES to enter tutorial (must go through it — it's mandatory content)
    game.touch(*TOUCH_YES, hold=15)
    game.settle(200)
    game.capture("tutorial_entered")

    # A through tutorial pages (D-pad, A, B, X, Y explanations)
    for i in range(20):
        game.press_a()
        game.settle(100)
    game.capture("tutorial_pages_done")

    # "Do you understand everything so far?" — touch YES
    game.settle(120)
    game.touch(*TOUCH_YES, hold=15)
    game.settle(200)
    game.capture("understand_yes")

    # "Would you like to know more about anything else?"
    # Wait for text, then press A to open the 3-option menu
    game.settle(300)
    game.capture("know_more_text")

    game.press_a()
    game.settle(120)
    game.capture("know_more_menu")

    # Select "NO INFO NEEDED" (third option: DOWN DOWN A)
    game.press(Keys.KEY_DOWN)
    game.wait(30)
    game.press(Keys.KEY_DOWN)
    game.wait(30)
    game.capture("cursor_on_no_info")

    game.press_a()
    game.settle(200)
    game.capture("tutorial_complete")

    # Save state — we're past the tutorial
    game.save_state("past_tutorial")

    # ================================================================
    # STAGE 5: Professor Rowan's introduction
    # ================================================================
    print("\n[Stage 5] Professor Rowan intro...")

    # Rowan's intro dialogue — just A through it patiently
    for i in range(12):
        game.press_a()
        game.settle(150)
        if i % 4 == 3:
            game.capture(f"rowan_dialogue_{i+1:02d}")

    # Poke Ball appears on bottom screen — touch the center button
    game.settle(200)
    game.capture("pokeball_prompt")

    game.touch(*TOUCH_POKEBALL_CENTER, hold=15)
    game.settle(300)
    game.capture("munchlax_released")

    # More dialogue after releasing Munchlax
    for i in range(10):
        game.press_a()
        game.settle(150)
        if i % 5 == 4:
            game.capture(f"post_munchlax_{i+1:02d}")

    # ================================================================
    # STAGE 6: Name entry
    # ================================================================
    print("\n[Stage 6] Name entry...")

    # "Your name?" prompt should appear
    game.settle(200)
    game.capture("name_prompt")

    # Press A to proceed to name entry screen
    game.press_a()
    game.settle(200)
    game.capture("name_entry_screen")

    # Capture the keyboard layout carefully (top and bottom screens)
    # This is important for building the touch keyboard map
    game.press_a()
    game.settle(200)
    game.capture("keyboard_layout")

    # For this clean run, let's actually try to navigate the name entry
    # The default name in Platinum US is typically at the top of the presets
    # Or we can try to use the keyboard

    # First, let's see what's on screen and decide
    # If there are preset names, we can select one
    # If it's a keyboard, we need to type

    # Try pressing DOWN a few times to see preset names
    for i in range(4):
        game.press(Keys.KEY_DOWN)
        game.settle(60)
    game.capture("name_presets_check")

    # Go back up and try pressing A on what's there
    for i in range(4):
        game.press(Keys.KEY_UP)
        game.settle(60)
    game.capture("name_back_to_top")

    # For now: let's just accept whatever default/first option
    # by pressing A a few times, then looking for a "confirm" button
    game.press_a()
    game.settle(120)
    game.capture("name_select_1")

    game.press_a()
    game.settle(120)
    game.capture("name_select_2")

    game.press_a()
    game.settle(200)
    game.capture("name_select_3")

    # Keep pressing A to try to confirm
    for i in range(10):
        game.press_a()
        game.settle(100)
    game.capture("name_confirmed")

    # Save state after name entry
    game.save_state("after_name")

    # ================================================================
    # STAGE 7: Rival introduction
    # ================================================================
    print("\n[Stage 7] Rival intro & remaining dialogue...")

    for i in range(20):
        game.press_a()
        game.settle(120)
        if i % 5 == 4:
            game.capture(f"rival_intro_{i+1:02d}")

    # There may be rival name entry too
    game.settle(200)
    game.capture("rival_name_check")

    # Just A through any remaining prompts
    for i in range(30):
        game.press_a()
        game.settle(100)
        if i % 10 == 9:
            game.capture(f"intro_continue_{i+1:02d}")

    # ================================================================
    # STAGE 8: Gameplay begins
    # ================================================================
    print("\n[Stage 8] Gameplay check...")

    game.settle(300)
    game.capture("gameplay_start")

    # Try moving to verify we're in the overworld
    game.press(Keys.KEY_DOWN)
    game.settle(30)
    game.press(Keys.KEY_DOWN)
    game.settle(30)
    game.press(Keys.KEY_LEFT)
    game.settle(30)
    game.press(Keys.KEY_RIGHT)
    game.settle(60)
    game.capture("moved_around")

    # Save the golden state
    golden_path = game.save_state("golden_gameplay")
    print(f"\n  Golden state saved: {golden_path}")

    # Memory readout
    print("\n[Memory State]")
    mem = game.read_memory()
    for k, v in mem.items():
        print(f"  {k}: {v}")

    game.cleanup()
    print("\n" + "=" * 60)
    print("Clean intro run complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
