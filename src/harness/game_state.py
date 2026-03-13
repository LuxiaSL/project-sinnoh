"""Game state detection for Pokemon Platinum (US).

Detects the current game mode (overworld, battle, menu, dialogue, transition)
and determines whether the game is waiting for player input.

This drives the agent loop: we only query Claude when the game is in a state
that requires a decision.

Signals used:
- Battle indicator (0x021D18F2): u8, values 0x41/0x97/0xC0 = in battle
- Battle menu state (anchor + 0x44878): what sub-menu is active in battle
- Dialogue buffer activity: whether dialogue text is on screen
- Pixel diff between frames: animation detection
- Coordinate stability: whether the player is moving or stationary
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Optional

import numpy as np

if TYPE_CHECKING:
    from desmume.emulator import DeSmuME


class GameMode(str, Enum):
    """Current game mode — determines what actions are available."""
    UNKNOWN = "unknown"
    OVERWORLD = "overworld"       # Walking around, interacting
    BATTLE = "battle"             # In a Pokemon battle
    BATTLE_MENU = "battle_menu"   # Battle with menu open (waiting for input)
    DIALOGUE = "dialogue"         # Dialogue box on screen
    MENU = "menu"                 # Start menu or sub-menus
    TRANSITION = "transition"     # Door fade, battle intro, etc. — wait
    EVOLUTION = "evolution"       # Evolution sequence — wait (unless move learn)
    TITLE = "title"               # Title/menu screen


class BattleMenuState(str, Enum):
    """Battle sub-menu states from RAM."""
    NONE = "none"                 # Not in battle or no menu
    MAIN = "main"                 # Fight/Bag/Pokemon/Run
    FIGHT = "fight"               # Move selection
    BAG = "bag"                   # Bag open
    POKEMON = "pokemon"           # Pokemon switch screen
    MOVE_LEARN = "move_learn"     # Learning a new move


# Fixed addresses
BATTLE_INDICATOR_ADDR = 0x021D18F2
BATTLE_VALUES = {0x41, 0x97, 0xC0}

# Trainer anchor pointer (for battle menu state)
TRAINER_ANCHOR_ADDR = 0x021C0794
BATTLE_MENU_OFFSET = 0x44878

# Battle menu state values
MENU_STATE_MAIN = 0x01
MENU_STATE_FIGHT = 0x03
MENU_STATE_BAG = 0x07
MENU_STATE_POKEMON = 0x09

# Pixel diff threshold for "animation finished" detection
# Below this = screen is stable. Above = something is animating.
PIXEL_DIFF_THRESHOLD = 0.005  # fraction of pixels that changed

# Minimum frames to advance for various transitions
MIN_FRAMES_DOOR = 30       # Door transition fade
MIN_FRAMES_BATTLE_INTRO = 120  # Battle intro animation
MIN_FRAMES_BUTTON = 6      # Button press registration


class GameStateDetector:
    """Detects the current game state and whether input is needed.

    The agent loop calls detect() each tick to determine:
    1. What mode the game is in (overworld, battle, dialogue, etc.)
    2. Whether the game is waiting for player input
    3. What actions are available in this mode
    """

    def __init__(self, emu: DeSmuME) -> None:
        self._emu = emu
        self._last_frame: Optional[np.ndarray] = None
        self._stable_frame_count: int = 0
        self._last_mode: GameMode = GameMode.UNKNOWN
        self._last_map_id: int = -1
        self._last_x: int = -1
        self._last_y: int = -1
        self._transition_frames: int = 0

    # === Low-level memory access ===

    def _read8(self, addr: int) -> int:
        return self._emu.memory.unsigned[addr]

    def _read16(self, addr: int) -> int:
        return self._emu.memory.unsigned.read_short(addr)

    def _read32(self, addr: int) -> int:
        return self._emu.memory.unsigned.read_long(addr)

    # === Detection methods ===

    def is_in_battle(self) -> bool:
        """Check the battle indicator byte."""
        try:
            value = self._read8(BATTLE_INDICATOR_ADDR)
            return value in BATTLE_VALUES
        except Exception:
            return False

    def get_battle_type(self) -> str:
        """Get the type of battle (wild/trainer/variant)."""
        try:
            value = self._read8(BATTLE_INDICATOR_ADDR)
            if value == 0x41:
                return "wild"
            elif value == 0x97:
                return "trainer"
            elif value == 0xC0:
                return "variant"
        except Exception:
            pass
        return "none"

    def get_battle_menu_state(self) -> BattleMenuState:
        """Read the battle menu state from RAM."""
        try:
            anchor = self._read32(TRAINER_ANCHOR_ADDR)
            if anchor < 0x02000000 or anchor > 0x02FFFFFF:
                return BattleMenuState.NONE
            state = self._read8(anchor + BATTLE_MENU_OFFSET)
            if state == MENU_STATE_MAIN:
                return BattleMenuState.MAIN
            elif state == MENU_STATE_FIGHT:
                return BattleMenuState.FIGHT
            elif state == MENU_STATE_BAG:
                return BattleMenuState.BAG
            elif state == MENU_STATE_POKEMON:
                return BattleMenuState.POKEMON
        except Exception:
            pass
        return BattleMenuState.NONE

    def compute_pixel_diff(self, current_frame: np.ndarray) -> float:
        """Compute fraction of pixels that changed between frames.

        Returns 0.0 if no previous frame, or a value 0.0-1.0 indicating
        what fraction of pixels changed significantly.
        """
        if self._last_frame is None:
            self._last_frame = current_frame.copy()
            return 0.0

        # Compare top screen only (more meaningful than bottom/Poketch)
        old_top = self._last_frame[:192]
        new_top = current_frame[:192]

        # Count pixels that changed by more than a small threshold
        diff = np.abs(new_top.astype(np.int16) - old_top.astype(np.int16))
        changed_pixels = np.any(diff > 10, axis=2).sum()
        total_pixels = old_top.shape[0] * old_top.shape[1]

        self._last_frame = current_frame.copy()
        return changed_pixels / total_pixels

    def detect(
        self,
        frame: Optional[np.ndarray] = None,
        has_dialogue: bool = False,
    ) -> GameMode:
        """Detect the current game mode.

        Args:
            frame: Current frame as numpy array (384, 256, 3). If None, skips
                   pixel diff analysis.
            has_dialogue: Whether the dialogue system detected active text.

        Returns:
            The detected GameMode.
        """
        # Check battle first (highest priority)
        if self.is_in_battle():
            menu_state = self.get_battle_menu_state()
            if menu_state != BattleMenuState.NONE:
                self._last_mode = GameMode.BATTLE_MENU
            else:
                self._last_mode = GameMode.BATTLE
            return self._last_mode

        # Check dialogue
        if has_dialogue:
            self._last_mode = GameMode.DIALOGUE
            return self._last_mode

        # Check pixel stability (transition detection)
        if frame is not None:
            diff = self.compute_pixel_diff(frame)
            if diff > PIXEL_DIFF_THRESHOLD:
                self._stable_frame_count = 0
                # If we were in a transition, stay in transition
                if self._last_mode == GameMode.TRANSITION:
                    return GameMode.TRANSITION
            else:
                self._stable_frame_count += 1

        # Default to overworld if stable and not in battle/dialogue
        self._last_mode = GameMode.OVERWORLD
        return self._last_mode

    def is_idle(
        self,
        frame: Optional[np.ndarray] = None,
        has_dialogue: bool = False,
        min_stable_frames: int = 3,
    ) -> bool:
        """Check if the game is idle and waiting for player input.

        This is the key signal for the agent loop: only query Claude when
        the game is idle.

        Args:
            frame: Current frame for pixel diff.
            has_dialogue: Whether dialogue is active.
            min_stable_frames: How many stable frames before we consider idle.

        Returns:
            True if the game appears to be waiting for input.
        """
        mode = self.detect(frame=frame, has_dialogue=has_dialogue)

        # Transitions are never idle — always wait
        if mode == GameMode.TRANSITION:
            return False

        # Battle without menu open — animation is playing, wait
        if mode == GameMode.BATTLE:
            return False

        # Battle with menu — idle (player needs to choose)
        if mode == GameMode.BATTLE_MENU:
            return True

        # Dialogue — idle (player needs to press A or make a choice)
        if mode == GameMode.DIALOGUE:
            return True

        # Overworld — idle if screen is stable
        if mode == GameMode.OVERWORLD:
            return self._stable_frame_count >= min_stable_frames

        return self._stable_frame_count >= min_stable_frames

    def reset_frame_tracking(self) -> None:
        """Reset the pixel diff tracking (call after loading a savestate)."""
        self._last_frame = None
        self._stable_frame_count = 0

    def available_action_types(self, mode: Optional[GameMode] = None) -> list[str]:
        """Return which action types are available in the current mode.

        This tells the agent what kinds of actions make sense right now.
        """
        m = mode or self._last_mode

        # Base actions available in all interactive modes
        base = ["press_button", "press_sequence", "touch", "wait", "use_tool"]

        if m == GameMode.OVERWORLD:
            return ["walk", "type_name"] + base
        elif m == GameMode.BATTLE_MENU:
            return base
        elif m == GameMode.BATTLE:
            return ["wait"]  # Animation playing, just wait
        elif m == GameMode.DIALOGUE:
            return ["type_name"] + base  # type_name for name entry during dialogue
        elif m == GameMode.MENU:
            return base
        elif m == GameMode.TRANSITION:
            return ["wait"]
        else:
            return base

    def __repr__(self) -> str:
        return (
            f"GameStateDetector(mode={self._last_mode.value}, "
            f"stable_frames={self._stable_frame_count})"
        )
