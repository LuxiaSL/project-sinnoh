"""Name entry keyboard mapping for Pokemon Platinum (US).

Maps characters to touch coordinates on the bottom screen keyboard.
The keyboard has 3 pages: UPPER (A-Z), lower (a-z), Others (symbols).
Letters occupy the same grid positions on UPPER and lower pages.

Grid measurements (from manual mapping):
- Origin (center of first key): (34, 97)
- Column width: 16px
- Row y-centers: [97, 115, 136, 154]
- 12 columns per row, 4 rows of characters

Touch coordinates are in bottom screen space (0-255, 0-191).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from desmume.emulator import DeSmuME

# Grid parameters (measured from screenshot)
# 13 columns × 5 rows (letters, punctuation/symbols, digits)
_X_START = 34      # Center x of first column
_COL_WIDTH = 16    # Pixels between column centers
_ROW_Y = [97, 115, 136, 154, 172]  # Center y of each row

# Button positions (manually measured)
_BUTTON_UPPER = (40, 71)
_BUTTON_LOWER = (72, 69)
_BUTTON_OTHERS = (104, 70)
_BUTTON_BACK = (176, 70)
_BUTTON_OK = (214, 70)


def _grid_pos(col: int, row: int) -> tuple[int, int]:
    """Get touch coordinates for a grid cell."""
    x = _X_START + col * _COL_WIDTH
    y = _ROW_Y[row]
    return (x, y)


# Character → (col, row, page) mappings
# page: "upper", "lower", or "others"
# Grid is 13 columns × 5 rows:
#   Rows 0-2: letters (cols 0-9) + symbols (cols 10-12, top-right 2×3 block)
#   Row 3: empty / special
#   Row 4: digits (cols 0-9)
_CHAR_MAP: dict[str, tuple[int, int, str]] = {}

# Lowercase a-z (page: lower)
_LOWER_LAYOUT = [
    "abcdefghij",   # row 0, cols 0-9
    "klmnopqrst",   # row 1, cols 0-9
    "uvwxyz",        # row 2, cols 0-5
]
for row_idx, row_chars in enumerate(_LOWER_LAYOUT):
    for col_idx, ch in enumerate(row_chars):
        _CHAR_MAP[ch] = (col_idx, row_idx, "lower")

# Uppercase A-Z (page: upper) — same grid positions
_UPPER_LAYOUT = [
    "ABCDEFGHIJ",
    "KLMNOPQRST",
    "UVWXYZ",
]
for row_idx, row_chars in enumerate(_UPPER_LAYOUT):
    for col_idx, ch in enumerate(row_chars):
        _CHAR_MAP[ch] = (col_idx, row_idx, "upper")

# Digits 0-9 — row 4, cols 0-9 (bottom row)
for i in range(10):
    _CHAR_MAP[str(i)] = (i, 4, "lower")

# Punctuation — top-right 2×3 block (cols 11-12, rows 0-2)
# Row 0: , .
_CHAR_MAP[","] = (11, 0, "lower")
_CHAR_MAP["."] = (12, 0, "lower")
# Row 1: ' -
_CHAR_MAP["'"] = (11, 1, "lower")
_CHAR_MAP["-"] = (11, 1, "lower")  # TODO: verify col for dash
# Row 2: ♂ ♀ (gender symbols — not typeable as ASCII, skip)

# Space — not on the keyboard; Platinum uses underscore for spaces in names


@dataclass
class KeyboardTyper:
    """Types text on the Platinum name entry keyboard via touch input.

    Handles page switching (UPPER/lower) and character lookup.
    Each character is typed with a single touch at the mapped coordinates.
    """

    _emu: DeSmuME
    _current_page: str = "upper"  # Keyboard starts on uppercase

    # Timing — generous to ensure touches register reliably
    TOUCH_HOLD_FRAMES: int = 10
    TOUCH_RELEASE_FRAMES: int = 8

    def _touch(self, x: int, y: int) -> None:
        """Touch a point on the bottom screen and release."""
        self._emu.input.touch_set_pos(x, y)
        for _ in range(self.TOUCH_HOLD_FRAMES):
            self._emu.cycle(with_joystick=False)
        self._emu.input.touch_release()
        for _ in range(self.TOUCH_RELEASE_FRAMES):
            self._emu.cycle(with_joystick=False)

    def _switch_page(self, target: str) -> None:
        """Switch keyboard page if needed."""
        if self._current_page == target:
            return

        if target == "upper":
            self._touch(*_BUTTON_UPPER)
        elif target == "lower":
            self._touch(*_BUTTON_LOWER)
        elif target == "others":
            self._touch(*_BUTTON_OTHERS)

        self._current_page = target
        # Extra settle time for page switch animation
        for _ in range(20):
            self._emu.cycle(with_joystick=False)

    def type_char(self, ch: str) -> bool:
        """Type a single character. Returns True if successful."""
        entry = _CHAR_MAP.get(ch)
        if entry is None:
            return False

        col, row, page = entry
        self._switch_page(page)
        x, y = _grid_pos(col, row)
        self._touch(x, y)
        return True

    def type_text(self, text: str) -> str:
        """Type a full string. Returns what was typed (skipping unknown chars)."""
        typed: list[str] = []
        for ch in text:
            if self.type_char(ch):
                typed.append(ch)
        return "".join(typed)

    def press_ok(self) -> None:
        """Press the OK button to confirm the name."""
        self._touch(*_BUTTON_OK)

    def press_back(self) -> None:
        """Press BACK to delete a character."""
        self._touch(*_BUTTON_BACK)

    def clear_name(self, max_chars: int = 8) -> None:
        """Press BACK repeatedly to clear the name field."""
        for _ in range(max_chars):
            self.press_back()


def get_supported_chars() -> str:
    """Return all characters the keyboard can type."""
    return "".join(sorted(_CHAR_MAP.keys()))
