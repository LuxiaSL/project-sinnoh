"""Dialogue transcript system for Pokemon Platinum (US).

Reads dialogue text from RAM and maintains a rolling window of recent lines.
This gives Claude short-term dialogue memory that a human player has naturally.

The game stores the current dialogue in a String struct (from pret/pokeplatinum):
    struct String {
        u16 maxSize;     // +0x00: typically 0x0400 (1024)
        u16 size;        // +0x02: current string length
        u32 integrity;   // +0x04: magic validation number
        charcode_t data[]; // +0x08: u16 charcodes (Gen 4 encoding)
    }

The buffer is heap-allocated and must be found by scanning RAM.
Once found, the address is cached (it persists for the session).

Character encoding note:
    Save block uses A=0x012B (confirmed from in-game data).
    Message text MIGHT use A=0x0133 (Bulbapedia).
    We try both encodings when scanning.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Optional

from .data.chars import decode_gen4_string

if TYPE_CHECKING:
    from desmume.emulator import DeSmuME

# String struct constants
STRING_HEADER_SIZE = 8  # maxSize(2) + size(2) + integrity(4)

# Valid maxSize values for dialogue String structs:
# - 1024 (0x0400): overworld/script dialogue (msgBuf, tmpBuf)
# - 320 (0x0140): battle messages ("PIPLUP used Pound!")
# We scan for both to catch all dialogue text.
STRING_MAX_SIZES = frozenset({0x0400, 0x0140})
STRING_MAX_SIZE_TYPICAL = 0x0400  # Legacy compat — largest expected size
STRING_TOTAL_SIZE = STRING_HEADER_SIZE + STRING_MAX_SIZE_TYPICAL * 2  # 2056 bytes

# Integrity magic number for live String structs.
# From pret/pokeplatinum src/string_gf.c: STRING_MAGIC_NUMBER = 0xB6F8D2EC
# Note: freed strings use 0xB6F8D2ED (magic + 1) as a tombstone.
# We previously scanned for 0xB6F8D2ED by mistake — finding only dead buffers.
STRING_INTEGRITY_MAGIC = 0xB6F8D2EC

# Gen 4 control codes
CTRL_NEWLINE = 0xE000
CTRL_CLEAR_SCREEN = 0x25BC
CTRL_SCROLL_UP = 0x25BD
CTRL_FORMAT = 0xFFFE
CTRL_TERMINATOR = 0xFFFF

# Default rolling window size
DEFAULT_WINDOW_SIZE = 30

# RAM scan range for heap-allocated buffers
# NDS main RAM is 4MB: 0x02000000-0x023FFFFF.
# 0x02400000-0x027FFFFF is a mirror — skip it.
SCAN_START = 0x02200000  # Skip the fixed data region
SCAN_END = 0x02400000    # End of real main RAM (mirror starts here)


class DialogueTranscript:
    """Reads dialogue text from RAM and maintains a rolling transcript.

    Maintains a set of known buffer addresses (discovered via periodic RAM
    scans) and reads ALL of them each poll. New text from any buffer is
    appended to the transcript.
    """

    # How often to do a full RAM scan for new buffers (in poll() calls).
    # Set high to avoid slowing down the settle loop (~45 polls per
    # button press). The forced rescan in _capture_game_context() handles
    # finding new buffers after scene changes — this is just a safety net.
    RESCAN_INTERVAL = 50

    def __init__(
        self,
        emu: DeSmuME,
        window_size: int = DEFAULT_WINDOW_SIZE,
    ) -> None:
        self._emu = emu
        self._window_size = window_size
        self._transcript: deque[str] = deque(maxlen=window_size)
        self._last_text: str = ""  # For deduplication
        self._buffer_addr: int | None = None  # Primary buffer (for compat)
        self._scan_attempted: bool = False

        # Multi-buffer tracking
        self._known_addrs: set[int] = set()  # All discovered buffer addresses
        self._last_texts: dict[int, str] = {}  # Last text per buffer (dedup)
        self._seen_texts: set[str] = set()  # All unique texts seen (global dedup)
        self._poll_count: int = 0  # For periodic rescan

        # Staleness tracking — detect when dialogue is no longer visually active.
        # The RAM buffer lingers after the dialogue box closes. We track when
        # the text last changed; if it hasn't changed in STALE_POLLS polls,
        # we consider it stale (dialogue box has closed).
        self._last_change_poll: int = 0  # poll_count when text last changed
        self._current_text: str | None = None  # Most recent text from any buffer

        # We support two possible encodings — save block (0x012B=A) and
        # message text (0x0133=A). We'll detect which one works.
        self._encoding_offset: int = 0  # 0 for save block, 8 for message

    # === Low-level memory access ===

    def _read8(self, addr: int) -> int:
        return self._emu.memory.unsigned[addr]

    def _read16(self, addr: int) -> int:
        return self._emu.memory.unsigned.read_short(addr)

    def _read32(self, addr: int) -> int:
        return self._emu.memory.unsigned.read_long(addr)

    # === Buffer scanning ===

    def find_buffer(self, known_text: str | None = None) -> int | None:
        """Scan RAM for dialogue text buffers.

        If known_text is provided, scan for that encoded text.
        Otherwise, look for String struct headers (maxSize=0x0400).

        Also populates the known buffer set for multi-buffer tracking.

        Returns the primary buffer address if found, None otherwise.
        """
        if known_text:
            addr = self._scan_for_text(known_text)
            if addr is not None:
                self._buffer_addr = addr
                self._known_addrs.add(addr)
        else:
            # Find ALL buffers, not just the first
            all_addrs = self.scan_all_buffers()
            for a in all_addrs:
                self._known_addrs.add(a)
            if all_addrs:
                self._buffer_addr = all_addrs[0]

        self._scan_attempted = True
        return self._buffer_addr

    def _scan_for_string_header(self) -> int | None:
        """Scan for String struct headers in the heap region.

        Look for known maxSize values with the integrity magic and a valid
        size field. Matches both overworld dialogue (maxSize=1024) and
        battle messages (maxSize=320).
        """
        step = 4  # Structs are word-aligned
        candidates: list[int] = []

        for addr in range(SCAN_START, SCAN_END - STRING_TOTAL_SIZE, step):
            try:
                max_size = self._read16(addr)
                if max_size not in STRING_MAX_SIZES:
                    continue

                size = self._read16(addr + 2)
                if size == 0 or size > max_size:
                    continue

                # Check integrity magic — this is the strongest signal
                integrity = self._read32(addr + 4)
                if integrity == STRING_INTEGRITY_MAGIC:
                    candidates.append(addr)
            except Exception:
                continue

        # Return the first candidate (typically the active dialogue buffer)
        return candidates[0] if candidates else None

    def scan_all_buffers(self) -> list[int]:
        """Scan for ALL dialogue String struct buffers in RAM.

        Matches both overworld dialogue (maxSize=1024) and battle messages
        (maxSize=320). Returns list of addresses.
        """
        step = 4
        results: list[int] = []

        for addr in range(SCAN_START, SCAN_END - STRING_TOTAL_SIZE, step):
            try:
                max_size = self._read16(addr)
                if max_size not in STRING_MAX_SIZES:
                    continue

                size = self._read16(addr + 2)
                if size == 0 or size > max_size:
                    continue

                integrity = self._read32(addr + 4)
                if integrity == STRING_INTEGRITY_MAGIC:
                    results.append(addr)
            except Exception:
                continue

        return results

    def _scan_for_text(self, text: str) -> int | None:
        """Scan RAM for a specific text string in Gen 4 encoding.

        Tries both save block encoding (A=0x012B) and the
        Bulbapedia message encoding (A=0x0133).
        """
        from .data.chars import encode_gen4_string

        # Encode using save block table (A=0x012B)
        encoded = encode_gen4_string(text)
        if not encoded:
            return None

        # Build the byte pattern to search for
        pattern = b""
        for code in encoded:
            pattern += code.to_bytes(2, "little")

        # Scan RAM for this pattern
        addr = self._scan_for_pattern(pattern)
        if addr is not None:
            # Found using save block encoding — the buffer starts 8 bytes before
            self._encoding_offset = 0
            return addr - STRING_HEADER_SIZE

        # Try with offset +8 (Bulbapedia encoding: A=0x0133 vs A=0x012B)
        encoded_alt = [c + 8 for c in encoded]
        pattern_alt = b""
        for code in encoded_alt:
            pattern_alt += code.to_bytes(2, "little")

        addr = self._scan_for_pattern(pattern_alt)
        if addr is not None:
            self._encoding_offset = 8
            return addr - STRING_HEADER_SIZE

        return None

    def _scan_for_pattern(self, pattern: bytes) -> int | None:
        """Scan RAM for a byte pattern. Returns first match address."""
        pattern_len = len(pattern)
        if pattern_len < 4:
            return None

        # Read in chunks for efficiency
        chunk_size = 0x10000  # 64KB chunks
        for chunk_start in range(SCAN_START, SCAN_END - pattern_len, chunk_size):
            try:
                chunk = bytes([
                    self._emu.memory.unsigned[chunk_start + i]
                    for i in range(min(chunk_size + pattern_len, SCAN_END - chunk_start))
                ])
                idx = chunk.find(pattern)
                if idx >= 0:
                    return chunk_start + idx
            except Exception:
                continue

        return None

    # === Text reading ===

    def read_current(self) -> str | None:
        """Read the current dialogue text from any known buffer.

        Tries all known buffers and returns the first non-empty text found.
        Returns None if no buffers are known or all are empty.
        """
        # Try known buffers
        for addr in list(self._known_addrs):
            text = self._read_buffer_at(addr)
            if text:
                return text

        # Fall back to primary buffer (compat)
        if self._buffer_addr is not None and self._buffer_addr not in self._known_addrs:
            return self._read_buffer_at(self._buffer_addr)

        return None

    def read_all_buffers(self) -> list[tuple[int, str]]:
        """Read text from all dialogue buffers in RAM.

        Returns list of (address, text) tuples.
        Useful for seeing all active dialogue at once.
        """
        addrs = self.scan_all_buffers()
        results: list[tuple[int, str]] = []

        for addr in addrs:
            saved = self._buffer_addr
            self._buffer_addr = addr
            text = self.read_current()
            self._buffer_addr = saved

            if text:
                results.append((addr, text))

        return results

    def poll(self) -> str | None:
        """Poll for new dialogue text from ALL known buffers.

        Call this periodically. Reads all known buffer addresses (fast),
        and periodically rescans RAM for new buffers (slower but necessary
        when scenes change and new buffers are allocated).

        Also tracks staleness: updates _last_change_poll whenever the
        buffer content changes. The is_active property uses this to
        distinguish live dialogue from stale lingering buffers.

        Returns the newest text found, or None if nothing changed.
        """
        self._poll_count += 1

        # Periodic rescan: discover new buffers
        # Also rescan if we have no buffers at all (fresh start)
        if not self._known_addrs or self._poll_count % self.RESCAN_INTERVAL == 0:
            self._rescan_buffers()

        # Read all known buffers, tracking what the current text is
        newest_text: str | None = None
        any_text: str | None = None

        for addr in list(self._known_addrs):
            text = self._read_buffer_at(addr)
            if text is None:
                continue

            # Track the most recent text from any buffer (for staleness)
            any_text = text

            # Skip if we've already seen this exact text from this buffer
            if text == self._last_texts.get(addr):
                continue

            self._last_texts[addr] = text

            # Skip if we've seen this exact text from ANY buffer (mirror dedup)
            if text in self._seen_texts:
                continue

            self._seen_texts.add(text)
            newest_text = text

            # Split multi-line text and add each line to transcript
            for line in text.split("\n"):
                line = line.strip()
                if line:
                    self._transcript.append(line)

        # Track staleness: if the current text differs from what we had,
        # the dialogue is actively changing (new page, new speaker, etc.)
        if any_text != self._current_text:
            self._current_text = any_text
            self._last_change_poll = self._poll_count

        # Update compat field
        if newest_text:
            self._last_text = newest_text

        return newest_text

    def _rescan_buffers(self) -> None:
        """Scan RAM for dialogue buffers and update the known set."""
        try:
            new_addrs = self.scan_all_buffers()
            for addr in new_addrs:
                if addr not in self._known_addrs:
                    self._known_addrs.add(addr)
                    # Also set the primary buffer for compat
                    if self._buffer_addr is None:
                        self._buffer_addr = addr
        except Exception:
            pass

    def _read_buffer_at(self, addr: int) -> str | None:
        """Read dialogue text from a specific buffer address."""
        try:
            # Validate header is still intact
            max_size = self._read16(addr)
            if max_size not in STRING_MAX_SIZES:
                return None

            integrity = self._read32(addr + 4)
            if integrity != STRING_INTEGRITY_MAGIC:
                # Buffer was freed or overwritten — remove from known set
                self._known_addrs.discard(addr)
                return None

            size = self._read16(addr + 2)
            if size == 0 or size > max_size:
                return None

            # Read charcode data
            data_addr = addr + STRING_HEADER_SIZE
            codes: list[int] = []
            for i in range(size):
                code = self._read16(data_addr + i * 2)
                if code == CTRL_TERMINATOR:
                    break
                if code == CTRL_SCROLL_UP:
                    continue
                if code == CTRL_FORMAT:
                    continue
                codes.append(code)

            text = decode_gen4_string(codes)
            if not text:
                return None
            text = text.strip()

            # Validate: if the text contains raw hex codes (?XXXX), it's
            # either corrupt data or the raw template buffer (tmpBuf) before
            # name substitution. Either way, skip it — the formatted msgBuf
            # has the human-readable version.
            import re
            hex_codes = re.findall(r'\?[0-9A-Fa-f]{4}', text)
            if hex_codes:
                return None

            return text if text else None
        except Exception:
            return None

    # === Transcript access ===

    def get_transcript(self, n: int | None = None) -> list[str]:
        """Get the last N lines of dialogue (or all if n is None)."""
        lines = list(self._transcript)
        if n is not None:
            return lines[-n:]
        return lines

    def format_transcript(self, n: int = 10) -> str:
        """Format recent dialogue for inclusion in agent prompt.

        Returns empty string if no dialogue recorded.
        """
        lines = self.get_transcript(n)
        if not lines:
            return ""

        formatted = ["--- RECENT DIALOGUE ---"]
        for line in lines:
            formatted.append(line)
        return "\n".join(formatted)

    def clear(self) -> None:
        """Clear the transcript."""
        self._transcript.clear()
        self._last_text = ""

    # How many polls without a text change before we consider it stale.
    # At ~4 frames per poll tick, 30 polls ≈ 120 frames ≈ 2 seconds.
    # This is generous — dialogue pages change much faster than this.
    STALE_THRESHOLD = 30

    @property
    def is_active(self) -> bool:
        """Whether dialogue is currently active (not stale).

        The RAM buffer lingers long after the dialogue box has closed.
        This property checks whether the buffer text has changed recently.
        If the same text has been sitting unchanged for STALE_THRESHOLD
        polls (~2 seconds), we consider the dialogue inactive.

        Use this instead of `buffer_found` for game state detection.
        """
        if not self._known_addrs:
            return False
        if self._current_text is None:
            return False
        polls_since_change = self._poll_count - self._last_change_poll
        return polls_since_change < self.STALE_THRESHOLD

    @property
    def buffer_found(self) -> bool:
        """Whether a dialogue buffer has been located in RAM."""
        return self._buffer_addr is not None

    @property
    def line_count(self) -> int:
        """Number of lines in the transcript."""
        return len(self._transcript)

    def __repr__(self) -> str:
        buf_str = f"0x{self._buffer_addr:08X}" if self._buffer_addr else "not found"
        return f"DialogueTranscript(buffer={buf_str}, lines={self.line_count})"
