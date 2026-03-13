"""Action execution layer for Pokemon Platinum.

Translates high-level actions (from Claude's tool calls) into frame-level
emulator input sequences. Handles button timing, multi-step movement,
touch screen input, and idle frame advancement.

Timing notes (from Phase 0/1 testing):
- Button press: 6 frames hold is reliable
- Touch: 10-12 frames hold
- Walking one tile: ~16 frames (8 frames per half-tile at normal speed)
- Running one tile: ~8 frames (with Running Shoes)
- Text advance (A press): 6 frames press, then ~30 frames for text to scroll
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from desmume.emulator import DeSmuME

# py-desmume key constants (imported at runtime to avoid import issues)
BUTTON_MAP: dict[str, str] = {
    "a": "KEY_A",
    "b": "KEY_B",
    "x": "KEY_X",
    "y": "KEY_Y",
    "l": "KEY_L",
    "r": "KEY_R",
    "up": "KEY_UP",
    "down": "KEY_DOWN",
    "left": "KEY_LEFT",
    "right": "KEY_RIGHT",
    "start": "KEY_START",
    "select": "KEY_SELECT",
}

DIRECTION_TO_KEY: dict[str, str] = {
    "up": "KEY_UP",
    "down": "KEY_DOWN",
    "left": "KEY_LEFT",
    "right": "KEY_RIGHT",
}

# Frame timing constants
FRAMES_BUTTON_HOLD = 6      # Frames to hold a button press
FRAMES_BUTTON_RELEASE = 4   # Frames to wait after releasing
FRAMES_TOUCH_HOLD = 10      # Frames to hold a touch input
FRAMES_TOUCH_RELEASE = 4    # Frames after touch release
FRAMES_WALK_STEP = 16       # Frames for one walking tile
FRAMES_RUN_STEP = 8         # Frames for one running tile
FRAMES_WALK_SETTLE = 4      # Extra frames after walk to let coords settle


class ActionResult(str, Enum):
    """Result of executing an action."""
    SUCCESS = "success"
    INVALID = "invalid"       # Action was malformed or impossible
    ERROR = "error"           # Execution error


@dataclass
class ActionOutcome:
    """Outcome of executing a single action."""
    result: ActionResult
    action_type: str
    detail: str = ""
    frames_advanced: int = 0


class ActionExecutor:
    """Translates high-level actions into emulator input sequences."""

    def __init__(self, emu: DeSmuME) -> None:
        self._emu = emu
        self._total_frames: int = 0

    @property
    def total_frames(self) -> int:
        """Total frames advanced across all actions."""
        return self._total_frames

    def _cycle(self, n: int = 1) -> None:
        """Advance the emulator by n frames."""
        for _ in range(n):
            self._emu.cycle(with_joystick=False)
            self._total_frames += 1

    def _get_keymask(self, key_name: str) -> int:
        """Get the keymask for a desmume key constant."""
        from desmume.controls import keymask, Keys
        key = getattr(Keys, key_name, None)
        if key is None:
            raise ValueError(f"Unknown key: {key_name}")
        return keymask(key)

    # === Core input methods ===

    def press_button(self, button: str, hold_frames: int = FRAMES_BUTTON_HOLD) -> ActionOutcome:
        """Press a single button for the specified number of frames.

        Args:
            button: Button name (a, b, x, y, l, r, up, down, left, right, start, select)
            hold_frames: How many frames to hold the button.

        Returns:
            ActionOutcome with result and frames advanced.
        """
        button_lower = button.lower().strip()
        key_name = BUTTON_MAP.get(button_lower)
        if key_name is None:
            return ActionOutcome(
                result=ActionResult.INVALID,
                action_type="press_button",
                detail=f"Unknown button: {button}. Valid: {', '.join(BUTTON_MAP.keys())}",
            )

        try:
            mask = self._get_keymask(key_name)
            frames = 0

            # Press and hold
            self._emu.input.keypad_add_key(mask)
            self._cycle(hold_frames)
            frames += hold_frames

            # Release
            self._emu.input.keypad_rm_key(mask)
            self._cycle(FRAMES_BUTTON_RELEASE)
            frames += FRAMES_BUTTON_RELEASE

            return ActionOutcome(
                result=ActionResult.SUCCESS,
                action_type="press_button",
                detail=f"Pressed {button_lower}",
                frames_advanced=frames,
            )
        except Exception as e:
            return ActionOutcome(
                result=ActionResult.ERROR,
                action_type="press_button",
                detail=f"Error pressing {button}: {e}",
            )

    def walk(self, direction: str, steps: int = 1) -> ActionOutcome:
        """Walk in a direction for the specified number of steps.

        Each step holds the direction key long enough for one tile of movement.

        Args:
            direction: "up", "down", "left", or "right"
            steps: Number of tiles to walk (1-20).

        Returns:
            ActionOutcome with result and frames advanced.
        """
        direction_lower = direction.lower().strip()
        key_name = DIRECTION_TO_KEY.get(direction_lower)
        if key_name is None:
            return ActionOutcome(
                result=ActionResult.INVALID,
                action_type="walk",
                detail=f"Unknown direction: {direction}. Valid: up, down, left, right",
            )

        # Clamp steps to reasonable range
        steps = max(1, min(steps, 20))

        try:
            mask = self._get_keymask(key_name)
            frames = 0

            for _ in range(steps):
                # Hold direction for one tile's worth of frames
                self._emu.input.keypad_add_key(mask)
                self._cycle(FRAMES_WALK_STEP)
                frames += FRAMES_WALK_STEP

                # Brief release between steps (prevents running in some cases)
                self._emu.input.keypad_rm_key(mask)
                self._cycle(FRAMES_WALK_SETTLE)
                frames += FRAMES_WALK_SETTLE

            return ActionOutcome(
                result=ActionResult.SUCCESS,
                action_type="walk",
                detail=f"Walked {direction_lower} {steps} step(s)",
                frames_advanced=frames,
            )
        except Exception as e:
            return ActionOutcome(
                result=ActionResult.ERROR,
                action_type="walk",
                detail=f"Error walking {direction}: {e}",
            )

    def touch(self, x: int, y: int, hold_frames: int = FRAMES_TOUCH_HOLD) -> ActionOutcome:
        """Tap the touch screen at (x, y).

        Bottom screen coordinates: x=0-255, y=0-191.

        Args:
            x: X coordinate on bottom screen.
            y: Y coordinate on bottom screen.
            hold_frames: How many frames to hold the touch.

        Returns:
            ActionOutcome with result and frames advanced.
        """
        if not (0 <= x <= 255) or not (0 <= y <= 191):
            return ActionOutcome(
                result=ActionResult.INVALID,
                action_type="touch",
                detail=f"Touch coordinates out of range: ({x}, {y}). Valid: x=0-255, y=0-191",
            )

        try:
            frames = 0

            self._emu.input.touch_set_pos(x, y)
            self._cycle(hold_frames)
            frames += hold_frames

            self._emu.input.touch_release()
            self._cycle(FRAMES_TOUCH_RELEASE)
            frames += FRAMES_TOUCH_RELEASE

            return ActionOutcome(
                result=ActionResult.SUCCESS,
                action_type="touch",
                detail=f"Touched ({x}, {y})",
                frames_advanced=frames,
            )
        except Exception as e:
            return ActionOutcome(
                result=ActionResult.ERROR,
                action_type="touch",
                detail=f"Error touching ({x}, {y}): {e}",
            )

    def wait(self, frames: int = 30) -> ActionOutcome:
        """Advance the emulator without any input.

        Used for: watching animations, letting dialogue play, taking in a scene,
        or just pausing to think.

        Args:
            frames: Number of frames to advance (1-600).

        Returns:
            ActionOutcome with frames advanced.
        """
        frames = max(1, min(frames, 600))

        try:
            self._cycle(frames)
            return ActionOutcome(
                result=ActionResult.SUCCESS,
                action_type="wait",
                detail=f"Waited {frames} frames",
                frames_advanced=frames,
            )
        except Exception as e:
            return ActionOutcome(
                result=ActionResult.ERROR,
                action_type="wait",
                detail=f"Error waiting: {e}",
            )

    def execute(self, action_type: str, **kwargs: object) -> ActionOutcome:
        """Execute an action by type name and keyword arguments.

        This is the main entry point from the action parser. Routes to the
        appropriate method based on action_type.

        Args:
            action_type: One of "press_button", "walk", "touch", "wait"
            **kwargs: Arguments for the specific action.

        Returns:
            ActionOutcome with result.
        """
        dispatch = {
            "press_button": self._exec_press_button,
            "press_sequence": self._exec_press_sequence,
            "type_name": self._exec_type_name,
            "walk": self._exec_walk,
            "touch": self._exec_touch,
            "wait": self._exec_wait,
        }

        handler = dispatch.get(action_type)
        if handler is None:
            return ActionOutcome(
                result=ActionResult.INVALID,
                action_type=action_type,
                detail=f"Unknown action type: {action_type}. Valid: {', '.join(dispatch.keys())}",
            )

        return handler(**kwargs)

    def _exec_press_button(self, **kwargs: object) -> ActionOutcome:
        button = str(kwargs.get("button", ""))
        hold = int(kwargs.get("hold_frames", FRAMES_BUTTON_HOLD))
        return self.press_button(button, hold_frames=hold)

    def _exec_walk(self, **kwargs: object) -> ActionOutcome:
        direction = str(kwargs.get("direction", ""))
        steps = int(kwargs.get("steps", 1))
        return self.walk(direction, steps=steps)

    def _exec_press_sequence(self, **kwargs: object) -> ActionOutcome:
        buttons = kwargs.get("buttons", [])
        if not isinstance(buttons, list) or not buttons:
            return ActionOutcome(
                result=ActionResult.INVALID,
                action_type="press_sequence",
                detail="buttons must be a non-empty list",
            )
        if len(buttons) > 20:
            buttons = buttons[:20]

        total_frames = 0
        pressed: list[str] = []
        for btn in buttons:
            outcome = self.press_button(str(btn))
            total_frames += outcome.frames_advanced
            pressed.append(str(btn))

        return ActionOutcome(
            result=ActionResult.SUCCESS,
            action_type="press_sequence",
            detail=f"Pressed sequence: {' → '.join(pressed)} ({len(pressed)} buttons, {total_frames} frames)",
            frames_advanced=total_frames,
        )

    def _exec_type_name(self, **kwargs: object) -> ActionOutcome:
        from .keyboard import KeyboardTyper
        name = str(kwargs.get("name", ""))
        confirm = bool(kwargs.get("confirm", True))

        if not name:
            return ActionOutcome(
                result=ActionResult.INVALID,
                action_type="type_name",
                detail="Name cannot be empty",
            )

        try:
            typer = KeyboardTyper(_emu=self._emu)

            # Wait for the keyboard to be fully loaded before touching
            # (the keyboard takes ~30 frames to appear after pressing A)
            self._cycle(60)

            # Clear any existing text first
            typer.clear_name()

            # Small pause after clearing
            self._cycle(10)

            # Type the name
            typed = typer.type_text(name)
            frames = self._total_frames  # rough — total includes waits
            if confirm:
                typer.press_ok()

            detail = f"Typed '{typed}'"
            if confirm:
                detail += " and pressed OK"
            if typed != name:
                detail += f" (requested '{name}', some chars unsupported)"

            return ActionOutcome(
                result=ActionResult.SUCCESS,
                action_type="type_name",
                detail=detail,
                frames_advanced=0,  # tracked via _cycle
            )
        except Exception as e:
            return ActionOutcome(
                result=ActionResult.ERROR,
                action_type="type_name",
                detail=f"Error typing name: {e}",
            )

    def _exec_touch(self, **kwargs: object) -> ActionOutcome:
        x = int(kwargs.get("x", -1))
        y = int(kwargs.get("y", -1))
        hold = int(kwargs.get("hold_frames", FRAMES_TOUCH_HOLD))
        return self.touch(x, y, hold_frames=hold)

    def _exec_wait(self, **kwargs: object) -> ActionOutcome:
        frames = int(kwargs.get("frames", 30))
        return self.wait(frames=frames)

    def __repr__(self) -> str:
        return f"ActionExecutor(total_frames={self._total_frames})"
